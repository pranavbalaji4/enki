"""End-to-end loop with the offline FakeLLM: chat -> tag/evaluate -> wrap-up review -> patterns -> insights -> feedback."""

import json
import os

import pytest

os.environ["ENKI_FAKE_LLM"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from enki import db as enki_db  # noqa: E402
from enki.api import app  # noqa: E402
from enki.jobs import run_pending  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    enki_db.configure(f"sqlite:///{tmp_path / 'test.db'}")
    enki_db.init_db()
    return TestClient(app)  # no `with`: the lifespan worker stays off; tests drain jobs via run_pending()


def chat(client, session_id: int, text: str) -> dict:
    events = []
    with client.stream("POST", f"/api/sessions/{session_id}/messages", json={"content": text}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert events[-1]["type"] == "done", events[-1]
    return {"reply": "".join(e["text"] for e in events if e["type"] == "delta"), "id": events[-1]["id"]}


def make_session(client, topic_title="Data Structures", lecture="Lec 7: Queues"):
    domain = client.post("/api/nodes", json={"kind": "folder", "title": "CS"}).json()
    topic = client.post("/api/nodes", json={"kind": "folder", "title": topic_title, "parent_id": domain["id"]}).json()
    sess = client.post("/api/nodes", json={"kind": "session", "title": lecture, "parent_id": topic["id"]}).json()
    return domain, topic, sess


def test_full_learning_loop(client):
    domain, topic, sess = make_session(client)

    chat(client, sess["id"], "What is a queue?")
    chat(client, sess["id"], "I don't get it")
    chat(client, sess["id"], "Oh so the first one in leaves first?")
    run_pending()

    s = client.get(f"/api/sessions/{sess['id']}").json()
    assert s["path"] == "CS / Data Structures / Lec 7: Queues"
    assert len(s["messages"]) == 6
    anns = {a["message_id"]: a for a in s["annotations"]}
    replies = [m for m in s["messages"] if m["role"] == "assistant"]
    assert "analogy" in anns[replies[0]["id"]]["strategies"]
    assert anns[replies[0]["id"]]["verdict"] == "confusion"
    assert anns[replies[1]["id"]]["verdict"] == "paraphrase_correct"
    assert anns[replies[2]["id"]]["verdict"] is None  # no learner reply yet

    assert client.post(f"/api/sessions/{sess['id']}/wrap-up").json()["ok"]
    run_pending()

    s = client.get(f"/api/sessions/{sess['id']}").json()
    assert s["node"]["status"] == "reviewed"
    assert s["pending_jobs"] == 0 and s["failed_jobs"] == []
    (ep,) = s["episodes"]
    assert ep["outcome"] == "clicked" and ep["winning_message_id"] == replies[1]["id"]

    prof = client.get(f"/api/profile/{topic['id']}").json()
    (pat,) = prof["patterns"]
    assert pat["strategy"] == "analogy" and pat["evidence_count"] == 1
    assert prof["stickies"] and "coffee shop" in prof["stickies"][0]["excerpt"]
    assert "analogies" in prof["markdown"].lower()
    assert "Everyday analogies" in prof["tutor_sees"]

    # The next session in the same topic sees the pattern, the topic summary and the sticky explanation.
    sess2 = client.post("/api/nodes", json={"kind": "session", "title": "Lec 8", "parent_id": topic["id"]}).json()
    from enki.context import build_tutor_request
    from enki.models import Node

    with enki_db.SessionLocal() as db:
        system, _ = build_tutor_request(db, db.get(Node, sess2["id"]))
    assert "Everyday analogies" in system and "coffee shop" in system and "Data Structures:" in system

    # A sibling domain does not see Data Structures' patterns.
    other = client.post("/api/nodes", json={"kind": "folder", "title": "Biology"}).json()
    bio = client.post("/api/nodes", json={"kind": "session", "title": "Cells", "parent_id": other["id"]}).json()
    with enki_db.SessionLocal() as db:
        system, _ = build_tutor_request(db, db.get(Node, bio["id"]))
    assert "Everyday analogies" not in system

    recaps = [i for i in client.get("/api/insights").json() if i["kind"] == "recap"]
    assert len(recaps) == 1 and recaps[0]["scope"] == "CS / Data Structures"


def test_pattern_insight_surfaces_and_feedback(client):
    _, topic, _ = make_session(client)
    for i in range(3):
        s = client.post("/api/nodes", json={"kind": "session", "title": f"L{i}", "parent_id": topic["id"]}).json()
        chat(client, s["id"], "What is a stack?")
        chat(client, s["id"], "So the last one in comes out first?")
        client.post(f"/api/sessions/{s['id']}/wrap-up")
        run_pending()

    cards = [i for i in client.get("/api/insights").json() if i["kind"] == "pattern"]
    assert len(cards) == 1
    card = cards[0]
    assert len(card["evidence"]) == 3 and "3 of 3" in card["body"]

    client.post(f"/api/insights/{card['id']}/feedback", json={"action": "confirm", "note": "especially for data structures"})
    prof = client.get(f"/api/profile/{topic['id']}").json()
    (pat,) = prof["patterns"]
    assert pat["user_status"] == "confirmed" and "especially" in pat["user_note"]
    assert "stated/confirmed by the learner" in prof["tutor_sees"]


def test_rewrap_does_not_double_count(client):
    _, topic, sess = make_session(client)
    chat(client, sess["id"], "What is a queue?")
    chat(client, sess["id"], "So first in first out?")
    for _ in range(2):
        client.post(f"/api/sessions/{sess['id']}/wrap-up")
        run_pending()
    (pat,) = client.get(f"/api/profile/{topic['id']}").json()["patterns"]
    assert pat["evidence_count"] == 1
    assert len([i for i in client.get("/api/insights").json() if i["kind"] == "recap"]) == 1


def test_rejected_pattern_leaves_tutor_prompt(client):
    _, topic, sess = make_session(client)
    chat(client, sess["id"], "What is a queue?")
    chat(client, sess["id"], "So first in first out?")
    client.post(f"/api/sessions/{sess['id']}/wrap-up")
    run_pending()
    from enki.models import Insight, Pattern

    with enki_db.SessionLocal() as db:
        p = db.query(Pattern).one()
        db.add(Insight(node_id=topic["id"], pattern_id=p.id, kind="pattern", title=p.claim, body=""))
        db.commit()
    card = next(i for i in client.get("/api/insights").json() if i["kind"] == "pattern")
    client.post(f"/api/insights/{card['id']}/feedback", json={"action": "reject"})
    prof = client.get(f"/api/profile/{topic['id']}").json()
    assert prof["patterns"] == [] and prof["tutor_sees"] == ""


def test_tree_operations(client):
    domain, topic, sess = make_session(client)
    r = client.patch(f"/api/nodes/{domain['id']}", json={"move": True, "parent_id": topic["id"]})
    assert r.status_code == 400
    assert client.post("/api/nodes", json={"kind": "session", "title": "x", "parent_id": sess["id"]}).status_code == 404
    client.delete(f"/api/nodes/{domain['id']}")
    assert client.get("/api/tree").json() == []
