import json
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import pipeline  # noqa: F401  (registers job handlers)
from .config import settings
from .context import build_tutor_request, path_title, profile_slice, render_profile_md, stickies_under
from .db import SessionLocal, get_db, init_db
from .evaluators import get_evaluator
from .feedback import apply_profile_edit, insight_feedback
from .jobs import Worker, enqueue
from .llm import LLMError, get_llm
from .models import Episode, Insight, Job, Message, Node, Pattern, PatternEvidence, TurnAnnotation

log = logging.getLogger("enki.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    worker = Worker()
    worker.start()
    yield
    worker.stop()


app = FastAPI(title="Enki", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"]
)


# ---------- schemas ----------

class NodeOut(BaseModel):
    id: int
    parent_id: int | None
    kind: str
    title: str
    status: str
    created_at: datetime


class NodeCreate(BaseModel):
    parent_id: int | None = None
    kind: Literal["folder", "session"]
    title: str


class NodeUpdate(BaseModel):
    title: str | None = None
    parent_id: int | None = None
    move: bool = False  # parent_id=None is meaningful (move to root), so moving is explicit


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class AnnotationOut(BaseModel):
    message_id: int
    concept: str | None
    concept_type: str | None
    strategies: list[str]
    ordering: str | None
    verdict: str | None
    understanding: float | None
    confidence: float | None
    referenced_part: str | None
    reasoning: str | None
    evaluator: str | None
    level_probs: list[float] | None  # P(not understood), P(iffy), P(understood)
    signals: dict[str, float] | None


class EpisodeOut(BaseModel):
    id: int
    session_id: int
    concept: str
    concept_type: str
    outcome: str
    message_ids: list[int]
    click_message_id: int | None
    winning_message_id: int | None
    path_summary: str
    why_it_clicked: str
    prompting_moves: list[str]


class SessionOut(BaseModel):
    node: NodeOut
    path: str
    summary: str
    messages: list[MessageOut]
    annotations: list[AnnotationOut]
    episodes: list[EpisodeOut]
    pending_jobs: int
    failed_jobs: list[str]


class SendMessage(BaseModel):
    content: str


class PatternOut(BaseModel):
    id: int
    claim: str
    strategy: str
    concept_type: str | None
    confidence: float
    evidence_count: int
    user_status: str
    user_note: str
    source: str


class StickyOut(BaseModel):
    id: int
    session_id: int
    concept: str
    excerpt: str
    why: str


class ProfileOut(BaseModel):
    node_id: int | None
    title: str
    summary: str
    markdown: str
    patterns: list[PatternOut]
    stickies: list[StickyOut]
    tutor_sees: str  # the exact profile slice injected into the tutor prompt from here


class ProfileEdit(BaseModel):
    markdown: str


class ProfileEditOut(BaseModel):
    understood: str
    ops: list[str]
    markdown: str


class InsightOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    status: str
    node_id: int | None
    scope: str
    session_id: int | None
    pattern_id: int | None
    evidence: list[EpisodeOut]
    created_at: datetime


class InsightAction(BaseModel):
    action: Literal["confirm", "reject", "dismiss"]
    note: str = ""


# ---------- helpers ----------

def _node(db: Session, node_id: int, kind: str | None = None) -> Node:
    node = db.get(Node, node_id)
    if node is None or (kind and node.kind != kind):
        raise HTTPException(404, f"{kind or 'node'} not found")
    return node


def _node_out(n: Node) -> NodeOut:
    return NodeOut(id=n.id, parent_id=n.parent_id, kind=n.kind, title=n.title, status=n.status, created_at=n.created_at)


def _episode_out(e: Episode) -> EpisodeOut:
    return EpisodeOut(
        id=e.id, session_id=e.session_id, concept=e.concept, concept_type=e.concept_type, outcome=e.outcome,
        message_ids=e.message_ids or [], click_message_id=e.click_message_id, winning_message_id=e.winning_message_id,
        path_summary=e.path_summary, why_it_clicked=e.why_it_clicked, prompting_moves=e.prompting_moves or [],
    )


def _pattern_out(p: Pattern) -> PatternOut:
    return PatternOut(
        id=p.id, claim=p.claim, strategy=p.strategy, concept_type=p.concept_type, confidence=round(p.confidence, 3),
        evidence_count=p.evidence_count, user_status=p.user_status, user_note=p.user_note, source=p.source,
    )


# ---------- tree ----------

@app.get("/api/tree", response_model=list[NodeOut])
def get_tree(db: Session = Depends(get_db)):
    return [_node_out(n) for n in db.scalars(select(Node).order_by(Node.kind, Node.title))]


@app.post("/api/nodes", response_model=NodeOut)
def create_node(body: NodeCreate, db: Session = Depends(get_db)):
    if body.parent_id is not None:
        _node(db, body.parent_id, "folder")
    node = Node(parent_id=body.parent_id, kind=body.kind, title=body.title.strip() or "Untitled")
    db.add(node)
    db.commit()
    return _node_out(node)


@app.patch("/api/nodes/{node_id}", response_model=NodeOut)
def update_node(node_id: int, body: NodeUpdate, db: Session = Depends(get_db)):
    node = _node(db, node_id)
    if body.title is not None:
        node.title = body.title.strip() or node.title
    if body.move:
        if body.parent_id is not None:
            parent = _node(db, body.parent_id, "folder")
            cur: Node | None = parent
            while cur is not None:  # refuse to move a folder inside itself
                if cur.id == node.id:
                    raise HTTPException(400, "Cannot move a folder into itself")
                cur = db.get(Node, cur.parent_id) if cur.parent_id else None
        node.parent_id = body.parent_id
    db.commit()
    return _node_out(node)


@app.delete("/api/nodes/{node_id}")
def delete_node(node_id: int, db: Session = Depends(get_db)):
    db.delete(_node(db, node_id))
    db.commit()
    return {"ok": True}


# ---------- sessions ----------

@app.get("/api/sessions/{session_id}", response_model=SessionOut)
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = _node(db, session_id, "session")
    msgs = db.scalars(select(Message).where(Message.session_id == s.id).order_by(Message.id))
    anns = db.scalars(select(TurnAnnotation).where(TurnAnnotation.session_id == s.id))
    eps = db.scalars(select(Episode).where(Episode.session_id == s.id).order_by(Episode.id))
    pending = db.scalar(
        select(func.count(Job.id)).where(Job.session_id == s.id, Job.status.in_(["queued", "running"]))
    )
    failed = db.scalars(select(Job.error).where(Job.session_id == s.id, Job.status == "failed").order_by(Job.id.desc()).limit(3))
    return SessionOut(
        node=_node_out(s),
        path=path_title(db, s),
        summary=s.summary,
        messages=[MessageOut(id=m.id, role=m.role, content=m.content, created_at=m.created_at) for m in msgs],
        annotations=[
            AnnotationOut(
                message_id=a.message_id, concept=a.concept, concept_type=a.concept_type, strategies=a.strategies or [],
                ordering=a.ordering, verdict=a.verdict, understanding=a.understanding, confidence=a.confidence,
                referenced_part=a.referenced_part, reasoning=a.reasoning, evaluator=a.evaluator,
                level_probs=a.level_probs, signals=a.signals,
            )
            for a in anns
        ],
        episodes=[_episode_out(e) for e in eps],
        pending_jobs=pending or 0,
        failed_jobs=[f for f in failed if f],
    )


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/api/sessions/{session_id}/messages")
def send_message(session_id: int, body: SendMessage, db: Session = Depends(get_db)):
    s = _node(db, session_id, "session")
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "Empty message")

    last = db.scalars(select(Message).where(Message.session_id == s.id).order_by(Message.id.desc()).limit(1)).first()
    user_msg = Message(session_id=s.id, role="user", content=text)
    db.add(user_msg)
    if s.status == "reviewed":
        s.status = "active"  # continuing after a wrap-up; the next wrap-up re-reviews the whole session
    db.commit()
    if last is not None and last.role == "assistant":
        # The learner's reply is the evidence for how the previous tutor turn landed.
        enqueue(db, "evaluate_turn", {"assistant_id": last.id, "next_id": user_msg.id}, s.id)

    system, messages = build_tutor_request(db, s)
    user_msg_id = user_msg.id

    def stream() -> Iterator[str]:
        yield _sse({"type": "user_message", "id": user_msg_id})
        parts: list[str] = []
        try:
            for chunk in get_llm().stream_tutor(system, messages):
                parts.append(chunk)
                yield _sse({"type": "delta", "text": chunk})
        except (LLMError, anthropic.AnthropicError) as e:
            log.warning("tutor stream failed: %s", e)
            # Drop the unanswered user message so history stays user/assistant alternating.
            with SessionLocal() as wdb:
                m = wdb.get(Message, user_msg_id)
                if m is not None:
                    wdb.delete(m)
                wdb.commit()
            yield _sse({"type": "error", "message": _friendly_error(e)})
            return
        with SessionLocal() as wdb:
            reply = Message(session_id=session_id, role="assistant", content="".join(parts))
            wdb.add(reply)
            wdb.commit()
            enqueue(wdb, "tag_turn", {"message_id": reply.id}, session_id)
            yield _sse({"type": "done", "id": reply.id})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _friendly_error(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "Anthropic API key missing or invalid. Set ANTHROPIC_API_KEY in backend/.env (or ENKI_FAKE_LLM=1 to run offline)."
    if isinstance(e, anthropic.RateLimitError):
        return "Rate limited by the API — try again in a moment."
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach the Anthropic API."
    return str(e)


@app.post("/api/sessions/{session_id}/wrap-up")
def wrap_up(session_id: int, db: Session = Depends(get_db)):
    s = _node(db, session_id, "session")
    if not db.scalar(select(func.count(Message.id)).where(Message.session_id == s.id)):
        raise HTTPException(400, "Nothing to review yet")
    s.status = "reviewing"
    db.commit()
    enqueue(db, "review_session", {"session_id": s.id}, s.id)
    return {"ok": True}


# ---------- profile ----------

def _scope_node(db: Session, node_id: int) -> Node | None:
    """node_id 0 means the global scope."""
    return None if node_id == 0 else _node(db, node_id, "folder")


@app.get("/api/profile/{node_id}", response_model=ProfileOut)
def get_profile(node_id: int, db: Session = Depends(get_db)):
    node = _scope_node(db, node_id)
    q = select(Pattern).where(Pattern.status == "active")
    q = q.where(Pattern.scope_node_id.is_(None) if node is None else Pattern.scope_node_id == node.id)
    pats = sorted(db.scalars(q), key=lambda p: p.confidence, reverse=True)
    return ProfileOut(
        node_id=node.id if node else None,
        title=path_title(db, node) if node else "Global",
        summary=node.summary if node else "",
        markdown=render_profile_md(db, node),
        patterns=[_pattern_out(p) for p in pats],
        stickies=[
            StickyOut(id=s.id, session_id=s.session_id, concept=s.concept, excerpt=s.excerpt, why=s.why)
            for s in stickies_under(db, node)
        ],
        tutor_sees=profile_slice(db, node) if node else "",
    )


@app.put("/api/profile/{node_id}", response_model=ProfileEditOut)
def edit_profile(node_id: int, body: ProfileEdit, db: Session = Depends(get_db)):
    node = _scope_node(db, node_id)
    try:
        return ProfileEditOut(**apply_profile_edit(db, node, body.markdown))
    except (LLMError, anthropic.AnthropicError) as e:
        raise HTTPException(502, _friendly_error(e))


# ---------- insights ----------

@app.get("/api/insights", response_model=list[InsightOut])
def list_insights(status: str | None = "new", db: Session = Depends(get_db)):
    q = select(Insight).order_by(Insight.created_at.desc()).limit(100)
    if status:
        q = q.where(Insight.status == status)
    out = []
    for i in db.scalars(q):
        scope = path_title(db, db.get(Node, i.node_id)) if i.node_id else "Global"
        evidence: list[Episode] = []
        if i.pattern_id:
            evidence = list(
                db.scalars(
                    select(Episode)
                    .join(PatternEvidence, PatternEvidence.episode_id == Episode.id)
                    .where(PatternEvidence.pattern_id == i.pattern_id)
                    .order_by(Episode.created_at.desc())
                )
            )
        elif i.session_id:
            evidence = list(db.scalars(select(Episode).where(Episode.session_id == i.session_id)))
        out.append(
            InsightOut(
                id=i.id, kind=i.kind, title=i.title, body=i.body, status=i.status, node_id=i.node_id, scope=scope,
                session_id=i.session_id, pattern_id=i.pattern_id, evidence=[_episode_out(e) for e in evidence],
                created_at=i.created_at,
            )
        )
    return out


@app.post("/api/insights/{insight_id}/feedback")
def post_insight_feedback(insight_id: int, body: InsightAction, db: Session = Depends(get_db)):
    insight = db.get(Insight, insight_id)
    if insight is None:
        raise HTTPException(404, "insight not found")
    insight_feedback(db, insight, body.action, body.note)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "fake_llm": settings.fake_llm,
        "llm": type(get_llm()).__name__,
        "evaluator": type(get_evaluator()).__name__,
    }
