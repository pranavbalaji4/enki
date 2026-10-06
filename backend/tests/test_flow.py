"""End-to-end with the offline FakeLLM: import a claude.ai export -> analyze -> topics, judged turns, patterns, profile."""

import copy
import io
import json
import os
import zipfile
from pathlib import Path

import pytest

os.environ["ENKI_FAKE_LLM"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from enki import db as enki_db  # noqa: E402
from enki.api import app  # noqa: E402
from enki.jobs import run_pending  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "conversations.json").read_text(encoding="utf-8"))


@pytest.fixture()
def client(tmp_path):
    enki_db.configure(f"sqlite:///{tmp_path / 'test.db'}")
    enki_db.init_db()
    return TestClient(app)  # no `with`: the lifespan worker stays off; tests drain jobs via run_pending()


def export_zip(conversations=FIXTURE) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data-2026-10-05/conversations.json", json.dumps(conversations))
        z.writestr("data-2026-10-05/users.json", "[]")
    return buf.getvalue()


def upload(client, blob: bytes) -> dict:
    r = client.post("/api/imports", content=blob, headers={"Content-Type": "application/zip"})
    assert r.status_code == 200, r.text
    return r.json()


def analyze(client, limit=None) -> dict:
    r = client.post("/api/analysis", json={"limit": limit})
    assert r.status_code == 200, r.text
    run_pending()
    return client.get("/api/analysis/latest").json()


def chat_id(client, title: str) -> int:
    return next(n["id"] for n in client.get("/api/tree").json() if n["kind"] == "session" and n["title"] == title)


def test_import_is_idempotent_and_estimates(client):
    r = upload(client, export_zip())
    assert (r["new"], r["updated"], r["unchanged"], r["empty"]) == (4, 0, 0, 1)
    assert r["pending_chats"] == 4
    assert r["estimate"]["chats"] == 4 and r["estimate"]["turns"] == 8 and r["estimate"]["usd"] > 0

    r = upload(client, export_zip())
    assert (r["new"], r["unchanged"]) == (0, 4)

    # A bare conversations.json works too; junk doesn't.
    assert upload(client, json.dumps(FIXTURE).encode())["unchanged"] == 4
    assert client.post("/api/imports", content=b"PK\x03\x04nope").status_code == 400


def test_parsing_keeps_main_branch_and_flattens_content(client):
    upload(client, export_zip())
    stacks = client.get(f"/api/chats/{chat_id(client, 'Stacks')}").json()
    texts = [m["content"] for m in stacks["messages"]]
    assert len(texts) == 4 and not any("ABANDONED" in t for t in texts)
    assert stacks["claude_url"] == "https://claude.ai/chat/c-stacks"

    queues = client.get(f"/api/chats/{chat_id(client, 'Queues')}").json()
    assert queues["messages"][1]["content"] == "Formally, a queue is a first-in-first-out collection."  # thinking dropped
    assert queues["messages"][2]["content"] == "I don't get it"  # `text` used when content is empty
    assert "[attachment: notes.txt]" in queues["messages"][4]["content"]


def test_full_analysis(client):
    upload(client, export_zip())
    run = analyze(client)
    assert run["status"] == "done", run
    assert run["counts"]["learning"] == 3 and run["counts"]["skipped"] == 1 and run["counts"]["reviewed"] == 3
    assert run["errors"] == []

    tree = client.get("/api/tree").json()
    folders = {n["id"]: n for n in tree if n["kind"] == "folder"}
    paths = set()
    for f in folders.values():
        if f["parent_id"]:
            paths.add(f"{folders[f['parent_id']]['title']} / {f['title']}")
    assert paths == {"Computer Science / Data Structures", "Finance / Markets"}
    email = next(n for n in tree if n["title"] == "Email to landlord")
    assert email["status"] == "skipped" and email["parent_id"] is None

    q = client.get(f"/api/chats/{chat_id(client, 'Queues')}").json()
    assert [c["title"] for c in q["breadcrumbs"]] == ["Computer Science", "Data Structures"]
    replies = [m for m in q["messages"] if m["role"] == "assistant"]
    anns = {a["message_id"]: a for a in q["annotations"]}
    assert len(anns) == len(replies) == 3
    first, second, last = (anns[m["id"]] for m in replies)
    assert first["verdict"] == "confusion" and first["level_probs"].index(max(first["level_probs"])) == 0
    assert second["verdict"] == "paraphrase_correct" and "analogy" in second["strategies"]
    assert abs(sum(second["level_probs"]) - 1) < 1e-6
    assert last["verdict"] == "no_signal" and last["level_probs"] is None
    assert q["chat"]["status"] == "analyzed" and q["chat"]["judged_turns"] == 2
    (ep,) = q["episodes"]
    assert ep["outcome"] == "clicked" and ep["winning_message_id"] == replies[1]["id"]

    o = client.get("/api/overview").json()
    assert o["stats"]["analyzed_chats"] == 3 and o["stats"]["pending_chats"] == 0
    assert o["mix"] == {"understood": 3, "iffy": 0, "not_understood": 1}
    assert o["snapshot"] and o["snapshot"]["headline"]
    # The analogy pattern held in two topics, so it rolled up to a global pattern backed by both.
    (g,) = o["global_patterns"]
    assert g["source"] == "rollup" and g["evidence_count"] == 3
    assert sorted(g["topics"]) == ["Computer Science / Data Structures", "Finance / Markets"]
    ds = next(t for t in o["topics"] if t["title"] == "Data Structures")
    assert ds["chat_count"] == 2 and ds["judged_turns"] == 3 and ds["line"]

    topic = client.get(f"/api/topics/{ds['id']}").json()
    assert {c["title"] for c in topic["chats"]} == {"Queues", "Stacks"}
    assert topic["patterns"][0]["strategy"] == "analogy" and topic["summary"]
    domain = client.get(f"/api/topics/{ds['parent_id']}").json()
    assert [c["title"] for c in domain["children"]] == ["Data Structures"]


def test_global_insight_card_and_confirmation(client):
    upload(client, export_zip())
    analyze(client)
    cards = [i for i in client.get("/api/insights?kind=pattern").json() if i["scope"] == "Global"]
    assert len(cards) == 1 and "2 topics" in cards[0]["body"]
    client.post(f"/api/insights/{cards[0]['id']}/feedback", json={"action": "confirm"})

    # Re-deriving the roll-up (on the next run) keeps the confirmation's weight.
    from enki.analysis import rollup_global_patterns

    with enki_db.SessionLocal() as db:
        (g,) = rollup_global_patterns(db)
        db.commit()
        assert g.user_status == "confirmed" and g.evidence_count == 5


def test_changed_chat_is_reanalyzed_without_double_counting(client):
    upload(client, export_zip())
    analyze(client)
    convs = copy.deepcopy(FIXTURE)
    queues = convs[0]
    queues["updated_at"] = "2026-09-20T10:00:00Z"
    queues["chat_messages"] += [
        {"uuid": "q7", "sender": "human", "created_at": "2026-09-20T10:00:00Z", "content": [{"type": "text", "text": "What about a priority queue?"}]},
        {"uuid": "q8", "sender": "assistant", "created_at": "2026-09-20T10:00:05Z", "content": [{"type": "text", "text": "Like an ER: most urgent first."}]},
    ]
    r = upload(client, export_zip(convs))
    assert (r["updated"], r["unchanged"], r["pending_chats"]) == (1, 3, 1)
    assert r["estimate"]["chats"] == 1

    run = analyze(client)
    assert run["status"] == "done" and run["chats"] == 1
    o = client.get("/api/overview").json()
    assert o["global_patterns"][0]["evidence_count"] == 3  # the old review's evidence was taken back out
    q = client.get(f"/api/chats/{chat_id(client, 'Queues')}").json()
    assert len(q["messages"]) == 8 and q["chat"]["status"] == "analyzed"


def test_limit_and_learning_override(client):
    upload(client, export_zip())
    assert client.get("/api/analysis/estimate?limit=1").json()["chats"] == 1
    run = analyze(client, limit=1)
    assert run["chats"] == 1  # the most recent pending chat: the email
    email = chat_id(client, "Email to landlord")
    assert client.get(f"/api/chats/{email}").json()["chat"]["status"] == "skipped"

    r = client.patch(f"/api/chats/{email}", json={"is_learning": True}).json()
    assert r["status"] == "pending" and r["is_learning"] is True
    assert client.get("/api/analysis/estimate").json()["chats"] == 4


def test_nothing_to_analyze(client):
    assert client.post("/api/analysis", json={}).status_code == 400


def test_ask_streams_and_keeps_history(client):
    upload(client, export_zip())
    analyze(client)
    events = []
    with client.stream("POST", "/api/ask", json={"content": "How do I learn best?"}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "user_message" and "tool" in kinds and kinds[-1] == "done"
    answer = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "3 replies landed" in answer and "(/chats/" in answer

    hist = client.get("/api/ask").json()
    assert [m["role"] for m in hist] == ["user", "assistant"] and hist[1]["tools_used"]
    client.delete("/api/ask")
    assert client.get("/api/ask").json() == []


def test_ask_tools_validate_input(client):
    from enki.ask import run_tool

    upload(client, export_zip())
    analyze(client)
    out, err = run_tool("search_turns", {"level": "not_understood"})
    assert not err and json.loads(out)[0]["verdict"] == "confusion"
    assert run_tool("get_topic", {"topic_id": "x"})[1] is True
    assert run_tool("get_chat", {"chat_id": 99999})[1] is True
    assert run_tool("nope", {})[1] is True


def test_tree_operations(client):
    upload(client, export_zip())
    analyze(client)
    tree = client.get("/api/tree").json()
    domain = next(n for n in tree if n["kind"] == "folder" and n["parent_id"] is None)
    topic = next(n for n in tree if n["parent_id"] == domain["id"])
    assert client.patch(f"/api/nodes/{domain['id']}", json={"move": True, "parent_id": topic["id"]}).status_code == 400
    assert client.patch(f"/api/nodes/{topic['id']}", json={"title": "DS"}).json()["title"] == "DS"
