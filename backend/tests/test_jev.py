"""Jev as the per-turn understanding judge, with the TypeSafe API replaced by a stand-in classifier."""

import os

os.environ["ENKI_FAKE_LLM"] = "1"

import pytest  # noqa: E402
from langchain_typesafe import ClassifierResponse, Choice, Noul, Score  # noqa: E402
from langchain_typesafe.client import TypeSafeAPIConnectionError  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

from enki import db as enki_db  # noqa: E402
from enki import evaluators  # noqa: E402
from enki.evaluators import ClaudeEvaluator, FallbackEvaluator, JevEvaluator  # noqa: E402
from enki.taxonomy import LEVEL_DESCRIPTIONS  # noqa: E402


def jev_response(probs=(0.05, 0.15, 0.80), verdict="paraphrase_correct", reused=0.9, frustrated=0.02):
    score = sum(i * p for i, p in enumerate(probs))
    return ClassifierResponse.model_validate(
        {
            "model": "jev-latest",
            "answers": {
                "understanding": {
                    "type": "score",
                    "score": score,
                    "legend": dict(enumerate(LEVEL_DESCRIPTIONS)),
                    "probabilities": dict(enumerate(probs)),
                    "confidence": 0.7,
                },
                "verdict": {
                    "type": "choice",
                    "choice": verdict,
                    "probabilities": {verdict: 0.8},
                    "confidence": 0.6,
                },
                "reused_explanation": {"type": "noul", "noul": reused},
                "frustrated": {"type": "noul", "noul": frustrated},
            },
            "request_id": "req_test",
        }
    )


class StubClassifier:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.requests = response, error, []

    def invoke(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


def test_request_carries_tutor_output_and_next_prompt():
    req = JevEvaluator.request("What is a heap?", "Think of a tournament bracket…", "So the winner is the root?")
    assert req["state"] == {
        "learner_question": "What is a heap?",
        "tutor_explanation": "Think of a tournament bracket…",
        "learner_next_message": "So the winner is the root?",
    }
    q = req["questions"]
    assert isinstance(q["understanding"], Score) and len(q["understanding"].criteria) == 3
    assert isinstance(q["verdict"], Choice) and "confusion" in q["verdict"].criteria
    assert isinstance(q["reused_explanation"], Noul) and isinstance(q["frustrated"], Noul)


def test_long_replies_are_trimmed_head_and_tail():
    reply = "A" * 6000 + "MIDDLE" + "Z" * 6000
    state = JevEvaluator.request("q", reply, "n")["state"]
    assert len(state["tutor_explanation"]) < len(reply)
    assert state["tutor_explanation"].startswith("A") and state["tutor_explanation"].endswith("Z")


def test_jev_answers_map_to_judgement():
    stub = StubClassifier(jev_response())
    j = JevEvaluator(stub).judge("What is a heap?", "Think of a tournament bracket…", "So the winner is the root?")
    assert j.evaluator == "jev"
    assert j.verdict == "paraphrase_correct"
    assert j.level_probs == [0.05, 0.15, 0.8]
    assert j.understanding == pytest.approx((0.15 + 2 * 0.8) / 2, abs=1e-3)
    assert j.confidence == 0.7
    assert j.signals == {"reused_explanation": 0.9, "frustrated": 0.02}
    assert "understood 80%" in j.reasoning


def test_unknown_verdict_label_is_treated_as_ambiguous():
    j = JevEvaluator(StubClassifier(jev_response(verdict="something_new"))).judge("q", "r", "n")
    assert j.verdict == "ambiguous_ack"


def test_falls_back_to_claude_when_jev_fails():
    stub = StubClassifier(error=TypeSafeAPIConnectionError("network down"))
    j = FallbackEvaluator(JevEvaluator(stub), ClaudeEvaluator()).judge("What is a queue?", "Like a line…", "I don't get it")
    assert j.evaluator == "fake"  # the offline stand-in for Claude answered
    assert j.verdict == "confusion" and j.level_probs is None


def test_pipeline_stores_jev_distribution(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from enki.api import app
    from enki.jobs import run_pending
    from tests.test_flow import chat, make_session

    enki_db.configure(f"sqlite:///{tmp_path / 'jev.db'}")
    enki_db.init_db()
    import enki.pipeline

    monkeypatch.setattr(enki.pipeline, "get_evaluator", lambda: JevEvaluator(StubClassifier(jev_response())))

    client = TestClient(app)
    _, _, sess = make_session(client)
    chat(client, sess["id"], "What is a heap?")
    chat(client, sess["id"], "So the smallest is always on top?")
    run_pending()

    s = client.get(f"/api/sessions/{sess['id']}").json()
    (ann,) = [a for a in s["annotations"] if a["verdict"]]
    assert ann["evaluator"] == "jev"
    assert ann["level_probs"] == [0.05, 0.15, 0.8]
    assert ann["signals"]["reused_explanation"] == 0.9

    from enki.models import Message
    from enki.pipeline import build_transcript

    with enki_db.SessionLocal() as db:
        from enki.models import TurnAnnotation

        msgs = db.query(Message).order_by(Message.id).all()
        anns = {a.message_id: a for a in db.query(TurnAnnotation)}
        transcript = build_transcript(msgs, anns)
    assert "p(not,iffy,understood)=0.05,0.15,0.80" in transcript
    assert "p(reused_explanation)=0.90" in transcript


def test_existing_database_gains_new_columns(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    eng = create_engine(url)
    with eng.begin() as conn:  # a turn_annotations table from before the Jev columns existed
        conn.execute(text("CREATE TABLE turn_annotations (id INTEGER PRIMARY KEY, message_id INTEGER, session_id INTEGER)"))
    eng.dispose()

    enki_db.configure(url)
    enki_db.init_db()
    cols = {c["name"] for c in inspect(enki_db.engine).get_columns("turn_annotations")}
    assert {"evaluator", "level_probs", "signals", "verdict"} <= cols


def test_evaluator_selection(monkeypatch):
    s = evaluators.settings
    monkeypatch.setattr(s, "fake_llm", False)
    for mode, key, expected in [
        ("auto", None, ClaudeEvaluator),
        ("claude", "k", ClaudeEvaluator),
        ("auto", "k", FallbackEvaluator),
        ("jev", "k", JevEvaluator),
    ]:
        monkeypatch.setattr(s, "evaluator", mode)
        monkeypatch.setattr(s, "typesafe_api_key", key)
        evaluators.get_evaluator.cache_clear()
        assert isinstance(evaluators.get_evaluator(), expected), (mode, key)
    evaluators.get_evaluator.cache_clear()
