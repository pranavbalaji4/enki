from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Node(Base):
    """Topic tree. `folder` nodes are topics (Domain -> Topic); `session` nodes are imported chats and always leaves.
    The implicit global root is parent_id = NULL (patterns with scope_node_id = NULL are global)."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # folder | session
    title: Mapped[str] = mapped_column(String(200))
    # Session: summary of the chat. Folder: roll-up of what was covered and what clicked.
    summary: Mapped[str] = mapped_column(Text, default="")
    # Session: pending (imported, not analyzed yet) | analyzed | skipped (not a learning chat) | failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Imported chats
    source: Mapped[str | None] = mapped_column(String(16))  # claude_ai
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    source_updated_at: Mapped[str | None] = mapped_column(String(40))  # change detection on re-import
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Classifier output; is_learning=None means not classified yet. The user can flip is_learning.
    is_learning: Mapped[bool | None] = mapped_column(Boolean)
    topic_label: Mapped[str | None] = mapped_column(String(200))


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    external_id: Mapped[str | None] = mapped_column(String(64))


class TurnAnnotation(Base):
    """How an assistant turn explained (tagger) and how well it landed, judged from the next user turn (evaluator)."""

    __tablename__ = "turn_annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), unique=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    # Tagger
    concept: Mapped[str | None] = mapped_column(String(200))
    concept_type: Mapped[str | None] = mapped_column(String(32))
    strategies: Mapped[list] = mapped_column(JSON, default=list)
    ordering: Mapped[str | None] = mapped_column(String(32))
    abstraction: Mapped[str | None] = mapped_column(String(16))
    # Evaluator (filled once the next user message exists)
    next_message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    verdict: Mapped[str | None] = mapped_column(String(32))
    understanding: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    referenced_part: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    evaluator: Mapped[str | None] = mapped_column(String(16))  # jev | claude | fake
    # P(not understood), P(iffy), P(understood); only Jev returns a real distribution.
    level_probs: Mapped[list | None] = mapped_column(JSON)
    # Extra yes/no probabilities Jev answers in the same call, e.g. {"reused_explanation": 0.8, "frustrated": 0.1}.
    signals: Mapped[dict | None] = mapped_column(JSON)


class Episode(Base):
    """The run of turns about one concept until it clicked (or didn't)."""

    __tablename__ = "episodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    concept: Mapped[str] = mapped_column(String(200))
    concept_type: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16))  # clicked | partial | not_yet
    message_ids: Mapped[list] = mapped_column(JSON, default=list)
    click_message_id: Mapped[int | None] = mapped_column(Integer)
    winning_message_id: Mapped[int | None] = mapped_column(Integer)
    path_summary: Mapped[str] = mapped_column(Text, default="")
    why_it_clicked: Mapped[str] = mapped_column(Text, default="")
    prompting_moves: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class StickyExplanation(Base):
    """An explanation that clicked, saved verbatim as part of the learner's personal canon."""

    __tablename__ = "sticky_explanations"

    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    concept: Mapped[str] = mapped_column(String(200))
    excerpt: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Pattern(Base):
    """A claim about how this learner learns, scoped to a node, backed by episodes. Beta(alpha, beta) tracks support."""

    __tablename__ = "patterns"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope_node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(64))
    concept_type: Mapped[str | None] = mapped_column(String(32))
    alpha: Mapped[float] = mapped_column(Float, default=1.0)
    beta: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | rejected
    user_status: Mapped[str] = mapped_column(String(16), default="unreviewed")  # unreviewed | confirmed | rejected | edited
    user_note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="observed")  # observed | user | rollup
    # Global roll-ups: the topic-level patterns this one was built from.
    derived_from: Mapped[list | None] = mapped_column(JSON)
    surfaced: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    @property
    def confidence(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def evidence_count(self) -> int:
        return round(self.alpha + self.beta - 2)


class PatternEvidence(Base):
    __tablename__ = "pattern_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    pattern_id: Mapped[int] = mapped_column(ForeignKey("patterns.id", ondelete="CASCADE"), index=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), index=True)
    supports: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str] = mapped_column(Text, default="")


class Insight(Base):
    """A card pushed to the learner: a session recap or a pattern worth confirming."""

    __tablename__ = "insights"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    pattern_id: Mapped[int | None] = mapped_column(ForeignKey("patterns.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # recap | pattern
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | confirmed | rejected | dismissed
    user_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Job(Base):
    """Persistent background job queue (stand-in for ARQ/Redis in the MVP)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AnalysisRun(Base):
    """One pass of the analysis pipeline over the pending imported chats."""

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    # classify | topics | turns | review | profile | done
    stage: Mapped[str] = mapped_column(String(16), default="classify")
    stage_done: Mapped[int] = mapped_column(Integer, default=0)
    stage_total: Mapped[int] = mapped_column(Integer, default=0)
    chat_ids: Mapped[list] = mapped_column(JSON, default=list)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)  # learning / skipped / turns / reviewed / failed
    errors: Mapped[list] = mapped_column(JSON, default=list)  # first few per-item failures
    error: Mapped[str | None] = mapped_column(Text)  # what stopped the whole run
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class ProfileSnapshot(Base):
    """The written global profile, regenerated at the end of each analysis run."""

    __tablename__ = "profile_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    headline: Mapped[str] = mapped_column(Text)
    summary_md: Mapped[str] = mapped_column(Text)
    topic_lines: Mapped[dict] = mapped_column(JSON, default=dict)  # str(topic node id) -> one line
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AskMessage(Base):
    """History of the "ask about how I learn" chat."""

    __tablename__ = "ask_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
