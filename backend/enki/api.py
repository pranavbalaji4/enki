import json
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import analysis  # noqa: F401  (registers the run_analysis job handler)
from . import ask, views
from .config import settings
from .context import ancestors, path_title, render_profile_md, stickies_under
from .db import SessionLocal, get_db, init_db
from .evaluators import get_evaluator
from .feedback import apply_profile_edit, insight_feedback
from .importer import ExportError, read_export, store_chats
from .jobs import Worker
from .llm import LLMError, get_llm
from .models import AnalysisRun, AskMessage, Episode, Insight, Message, Node, Pattern, PatternEvidence, TurnAnnotation

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
    is_learning: bool | None
    created_at: datetime


class NodeUpdate(BaseModel):
    title: str | None = None
    parent_id: int | None = None
    move: bool = False  # parent_id=None is meaningful (move to root), so moving is explicit


class Mix(BaseModel):
    understood: int
    iffy: int
    not_understood: int


class Estimate(BaseModel):
    chats: int
    turns: int
    usd: float
    breakdown: dict[str, float]


class ImportOut(BaseModel):
    new: int
    updated: int
    unchanged: int
    empty: int
    pending_chats: int
    estimate: Estimate


class StartAnalysis(BaseModel):
    limit: int | None = None  # analyze only the N most recent pending chats


class RunOut(BaseModel):
    id: int
    status: str
    stage: str
    stage_done: int
    stage_total: int
    chats: int
    counts: dict[str, int]
    errors: list[str]
    error: str | None
    created_at: datetime
    updated_at: datetime


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
    scope_id: int | None
    scope: str
    topics: list[str]  # for cross-topic patterns: the topics it was seen in


class StickyOut(BaseModel):
    id: int
    session_id: int
    chat_title: str
    concept: str
    excerpt: str
    why: str


class TopicOut(BaseModel):
    id: int
    parent_id: int | None
    title: str
    path: str
    chat_count: int
    analyzed_count: int
    judged_turns: int
    avg_understanding: float | None
    mix: Mix
    line: str  # the global profile's one-liner for this topic


class SnapshotOut(BaseModel):
    headline: str
    summary_md: str
    created_at: datetime


class Stats(BaseModel):
    chats: int
    learning_chats: int
    analyzed_chats: int
    pending_chats: int
    topics: int


class OverviewOut(BaseModel):
    snapshot: SnapshotOut | None
    stats: Stats
    mix: Mix
    topics: list[TopicOut]
    global_patterns: list[PatternOut]
    top_patterns: list[PatternOut]
    stickies: list[StickyOut]


class ChatSummaryOut(BaseModel):
    id: int
    title: str
    started_at: datetime
    status: str
    is_learning: bool | None
    judged_turns: int
    avg_understanding: float | None
    mix: Mix


class Crumb(BaseModel):
    id: int
    title: str


class TopicDetailOut(BaseModel):
    topic: TopicOut
    summary: str
    breadcrumbs: list[Crumb]
    children: list[TopicOut]
    patterns: list[PatternOut]
    stickies: list[StickyOut]
    chats: list[ChatSummaryOut]


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
    verdict: str | None  # no_signal: the chat ended on this reply
    understanding: float | None
    confidence: float | None
    referenced_part: str | None
    reasoning: str | None
    evaluator: str | None  # jev | claude | fake
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


class ChatOut(BaseModel):
    chat: ChatSummaryOut
    breadcrumbs: list[Crumb]
    topic_label: str | None
    summary: str
    claude_url: str | None
    messages: list[MessageOut]
    annotations: list[AnnotationOut]
    episodes: list[EpisodeOut]


class ChatUpdate(BaseModel):
    is_learning: bool


class ProfileOut(BaseModel):
    node_id: int | None
    title: str
    summary: str
    markdown: str
    patterns: list[PatternOut]
    stickies: list[StickyOut]


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


class AskIn(BaseModel):
    content: str


class AskMessageOut(BaseModel):
    id: int
    role: str
    content: str
    tools_used: list[str]
    created_at: datetime


# ---------- helpers ----------

def _node(db: Session, node_id: int, kind: str | None = None) -> Node:
    node = db.get(Node, node_id)
    if node is None or (kind and node.kind != kind):
        raise HTTPException(404, f"{'chat' if kind == 'session' else kind or 'node'} not found")
    return node


def _node_out(n: Node) -> NodeOut:
    return NodeOut(
        id=n.id, parent_id=n.parent_id, kind=n.kind, title=n.title, status=n.status, is_learning=n.is_learning,
        created_at=n.created_at,
    )


def _episode_out(e: Episode) -> EpisodeOut:
    return EpisodeOut(
        id=e.id, session_id=e.session_id, concept=e.concept, concept_type=e.concept_type, outcome=e.outcome,
        message_ids=e.message_ids or [], click_message_id=e.click_message_id, winning_message_id=e.winning_message_id,
        path_summary=e.path_summary, why_it_clicked=e.why_it_clicked, prompting_moves=e.prompting_moves or [],
    )


def _run_out(r: AnalysisRun) -> RunOut:
    return RunOut(
        id=r.id, status=r.status, stage=r.stage, stage_done=r.stage_done, stage_total=r.stage_total,
        chats=len(r.chat_ids or []), counts=r.counts or {}, errors=r.errors or [], error=r.error,
        created_at=r.created_at, updated_at=r.updated_at,
    )


def _friendly_error(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "Anthropic API key missing or invalid. Set ANTHROPIC_API_KEY in backend/.env (or ENKI_FAKE_LLM=1 to run offline)."
    if isinstance(e, anthropic.RateLimitError):
        return "Rate limited by the API — try again in a moment."
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach the Anthropic API."
    return str(e)


# ---------- tree ----------

@app.get("/api/tree", response_model=list[NodeOut])
def get_tree(db: Session = Depends(get_db)):
    return [_node_out(n) for n in db.scalars(select(Node).order_by(Node.kind, Node.title))]


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


# ---------- import + analysis ----------

@app.post("/api/imports", response_model=ImportOut)
async def import_export(request: Request, db: Session = Depends(get_db)):
    """Body: the claude.ai export ZIP (or conversations.json) as raw bytes."""
    blob = await request.body()
    if not blob:
        raise HTTPException(400, "Empty upload")
    if len(blob) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Export is larger than {settings.max_upload_mb} MB")
    try:
        chats = read_export(blob)
    except ExportError as e:
        raise HTTPException(400, str(e))
    r = store_chats(db, chats)
    pending = analysis.pending_chat_ids(db)
    return ImportOut(
        new=r.new, updated=r.updated, unchanged=r.unchanged, empty=r.empty, pending_chats=len(pending),
        estimate=Estimate(**analysis.estimate(db, pending)),
    )


@app.get("/api/analysis/estimate", response_model=Estimate)
def get_estimate(limit: int | None = None, db: Session = Depends(get_db)):
    return Estimate(**analysis.estimate(db, analysis.pending_chat_ids(db, limit)))


@app.post("/api/analysis", response_model=RunOut)
def start_analysis(body: StartAnalysis, db: Session = Depends(get_db)):
    if not analysis.pending_chat_ids(db, body.limit):
        raise HTTPException(400, "Nothing to analyze — import your claude.ai export first.")
    return _run_out(analysis.start_run(db, body.limit))


@app.get("/api/analysis/latest", response_model=RunOut | None)
def latest_run(db: Session = Depends(get_db)):
    r = db.scalars(select(AnalysisRun).order_by(AnalysisRun.id.desc()).limit(1)).first()
    return _run_out(r) if r else None


# ---------- insights pages ----------

@app.get("/api/overview", response_model=OverviewOut)
def get_overview(db: Session = Depends(get_db)):
    return views.overview(db)


@app.get("/api/topics/{topic_id}", response_model=TopicDetailOut)
def get_topic(topic_id: int, db: Session = Depends(get_db)):
    return views.topic_detail(db, _node(db, topic_id, "folder"))


@app.get("/api/chats/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: int, db: Session = Depends(get_db)):
    c = _node(db, chat_id, "session")
    msgs = db.scalars(select(Message).where(Message.session_id == c.id).order_by(Message.id))
    anns = list(db.scalars(select(TurnAnnotation).where(TurnAnnotation.session_id == c.id)))
    eps = db.scalars(select(Episode).where(Episode.session_id == c.id).order_by(Episode.id))
    return ChatOut(
        chat=views.chat_summary(db, c, [a for a in anns if views.level_of(a) is not None]),
        breadcrumbs=[Crumb(id=a.id, title=a.title) for a in reversed(ancestors(db, c))],
        topic_label=c.topic_label,
        summary=c.summary,
        claude_url=f"https://claude.ai/chat/{c.external_id}" if c.source == "claude_ai" and c.external_id else None,
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
    )


@app.patch("/api/chats/{chat_id}", response_model=ChatSummaryOut)
def update_chat(chat_id: int, body: ChatUpdate, db: Session = Depends(get_db)):
    """Override the classifier: include a chat it skipped (it's analyzed on the next run), or leave one out."""
    c = _node(db, chat_id, "session")
    c.is_learning = body.is_learning
    if body.is_learning and c.status == "skipped":
        c.status = "pending"
    elif not body.is_learning and c.status in ("pending", "failed"):
        c.status = "skipped"
    db.commit()
    return views.chat_summary(db, c)


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
        patterns=[views.pattern_dict(db, p) for p in pats],
        stickies=[views.sticky_dict(db, s) for s in stickies_under(db, node)],
    )


@app.put("/api/profile/{node_id}", response_model=ProfileEditOut)
def edit_profile(node_id: int, body: ProfileEdit, db: Session = Depends(get_db)):
    node = _scope_node(db, node_id)
    try:
        return ProfileEditOut(**apply_profile_edit(db, node, body.markdown))
    except (LLMError, anthropic.AnthropicError) as e:
        raise HTTPException(502, _friendly_error(e))


# ---------- insight cards ----------

@app.get("/api/insights", response_model=list[InsightOut])
def list_insights(status: str | None = "new", kind: str | None = None, db: Session = Depends(get_db)):
    q = select(Insight).order_by(Insight.created_at.desc()).limit(100)
    if status:
        q = q.where(Insight.status == status)
    if kind:
        q = q.where(Insight.kind == kind)
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


# ---------- ask ----------

ASK_HISTORY = 20  # earlier messages sent back to the model with each question


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


@app.get("/api/ask", response_model=list[AskMessageOut])
def ask_history(db: Session = Depends(get_db)):
    return [
        AskMessageOut(id=m.id, role=m.role, content=m.content, tools_used=m.tools_used or [], created_at=m.created_at)
        for m in db.scalars(select(AskMessage).order_by(AskMessage.id))
    ]


@app.delete("/api/ask")
def clear_ask(db: Session = Depends(get_db)):
    db.execute(delete(AskMessage))
    db.commit()
    return {"ok": True}


@app.post("/api/ask")
def ask_question(body: AskIn, db: Session = Depends(get_db)):
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "Empty question")
    earlier = list(db.scalars(select(AskMessage).order_by(AskMessage.id.desc()).limit(ASK_HISTORY)))[::-1]
    history = [{"role": m.role, "content": m.content} for m in earlier]
    while history and history[0]["role"] != "user":
        history.pop(0)
    history.append({"role": "user", "content": text})
    question = AskMessage(role="user", content=text, tools_used=[])
    db.add(question)
    db.commit()
    question_id = question.id

    def stream() -> Iterator[str]:
        yield _sse({"type": "user_message", "id": question_id})
        parts: list[str] = []
        tools: list[str] = []
        try:
            for ev in ask.answer(history):
                if ev["type"] == "delta":
                    parts.append(ev["text"])
                elif ev["type"] == "tool":
                    tools.append(ev["label"])
                yield _sse(ev)
        except (LLMError, anthropic.AnthropicError) as e:
            log.warning("ask failed: %s", e)
            with SessionLocal() as wdb:  # keep history alternating: drop the unanswered question
                q = wdb.get(AskMessage, question_id)
                if q is not None:
                    wdb.delete(q)
                wdb.commit()
            yield _sse({"type": "error", "message": _friendly_error(e)})
            return
        with SessionLocal() as wdb:
            reply = AskMessage(role="assistant", content="".join(parts).strip(), tools_used=tools)
            wdb.add(reply)
            wdb.commit()
            yield _sse({"type": "done", "id": reply.id})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "fake_llm": settings.fake_llm,
        "llm": type(get_llm()).__name__,
        "evaluator": type(get_evaluator()).__name__,
    }
