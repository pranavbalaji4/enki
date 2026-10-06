"""The analysis run: imported chats -> learning profile.

Stages, each resumable (a restart re-queues the job, and every stage skips work that is already done):
  classify  fast model, per chat      is this a learning chat? which domain / topic?
  topics    deep model, once          merge the labels into the Domain -> Topic tree, place the chats
  turns     fast model, per reply     how it explained + did it land (judged from the next user message)
  review    deep model, per chat      episodes, explanations that clicked, pattern evidence
  profile   deep model, once          topic summaries, cross-topic patterns, the written global profile

Model calls run on a thread pool and never touch the database; results are written on the job's own thread."""

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

import anthropic
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .context import _rank, path_title
from .feedback import CONFIRM_WEIGHT
from .jobs import enqueue, handler
from .llm import LLMError, get_llm
from .models import AnalysisRun, Insight, Message, Node, Pattern, ProfileSnapshot, StickyExplanation
from .pipeline import (
    MAX_TRANSCRIPT_MSG_CHARS,
    MAX_TURN_CHARS,
    analyze_turn_call,
    apply_review,
    apply_turn,
    review_call,
    review_input,
    turn_inputs,
)
from .views import understanding_mix

log = logging.getLogger("enki.analysis")

I = TypeVar("I")
R = TypeVar("R")

# Errors that will fail every remaining call too: stop the run instead of recording hundreds of failures.
FATAL = (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)
MAX_RECORDED_ERRORS = 10
STAGES = ["classify", "topics", "turns", "review", "profile"]


# ---------- choosing and pricing the work ----------

def pending_chat_ids(db: Session, limit: int | None = None) -> list[int]:
    """Chats waiting for analysis, most recent first. Chats marked as not-learning are left out."""
    q = (
        select(Node.id)
        .where(Node.kind == "session", Node.status.in_(["pending", "failed"]), Node.is_learning.is_not(False))
        .order_by(func.coalesce(Node.started_at, Node.created_at).desc())
    )
    if limit:
        q = q.limit(limit)
    return list(db.scalars(q))


def _usd(model: str, tokens_in: float, tokens_out: float) -> float:
    p_in, p_out = settings.prices.get(model, (0.0, 0.0))
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


def estimate(db: Session, chat_ids: list[int]) -> dict:
    """Rough upper bound (~4 characters per token; assumes every unclassified chat turns out to be a learning chat)."""
    cost = defaultdict(float)
    turns = 0
    fast, deep = settings.fast_model, settings.deep_model
    for node in db.scalars(select(Node).where(Node.id.in_(chat_ids))):
        msgs = list(db.scalars(select(Message).where(Message.session_id == node.id).order_by(Message.id)))
        if node.is_learning is None:
            opening = sum(min(len(m.content), 600) for m in msgs if m.role == "user")
            cost["classify"] += _usd(fast, 400 + (len(node.title) + opening) / 4, 80)
        transcript = 0
        for i, m in enumerate(msgs):
            transcript += min(len(m.content), MAX_TRANSCRIPT_MSG_CHARS)
            if m.role != "assistant":
                continue
            turns += 1
            around = sum(min(len(x.content), MAX_TURN_CHARS) for x in msgs[max(0, i - 1): i + 2])
            cost["turns"] += _usd(fast, 1100 + around / 4, 300)
        cost["review"] += _usd(deep, 2500 + transcript / 4, 3500)
    if chat_ids:
        cost["topics_and_profile"] += _usd(deep, 8000, 6000)
    return {
        "chats": len(chat_ids),
        "turns": turns,
        "usd": round(sum(cost.values()), 2),
        "breakdown": {k: round(v, 2) for k, v in cost.items()},
    }


def start_run(db: Session, limit: int | None = None) -> AnalysisRun:
    active = db.scalars(select(AnalysisRun).where(AnalysisRun.status.in_(["queued", "running"]))).first()
    if active is not None:
        return active
    run = AnalysisRun(chat_ids=pending_chat_ids(db, limit), counts={}, errors=[])
    db.add(run)
    db.commit()
    enqueue(db, "run_analysis", {"run_id": run.id})
    return run


# ---------- running ----------

class _Progress:
    def __init__(self, db: Session, run: AnalysisRun) -> None:
        self.db, self.run = db, run

    def stage(self, name: str, total: int) -> None:
        self.run.stage, self.run.stage_done, self.run.stage_total = name, 0, total
        self.db.commit()

    def step(self) -> None:
        self.run.stage_done += 1
        self.db.commit()

    def count(self, key: str, n: int = 1) -> None:
        self.run.counts = {**self.run.counts, key: self.run.counts.get(key, 0) + n}

    def fail(self, what: str, e: Exception) -> None:
        log.warning("analysis: %s failed: %s", what, e)
        self.count("failed")
        if len(self.run.errors) < MAX_RECORDED_ERRORS:
            self.run.errors = [*self.run.errors, f"{what}: {type(e).__name__}: {e}"[:300]]


def _parallel(
    items: Iterable[I],
    call: Callable[[I], R],
    write: Callable[[I, R], None],
    progress: _Progress,
    describe: Callable[[I], str],
    workers: int,
) -> None:
    """Run `call` on a pool and `write` each result here as it completes. A fatal API error stops the stage."""
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(call, item): item for item in items}
        try:
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    write(item, fut.result())
                except FATAL:
                    raise
                except (LLMError, anthropic.AnthropicError, ValueError) as e:
                    progress.db.rollback()
                    progress.fail(describe(item), e)
                progress.step()
        except FATAL:
            for f in futures:
                f.cancel()
            raise


@handler("run_analysis")
def run_analysis(db: Session, payload: dict) -> None:
    run = db.get(AnalysisRun, payload["run_id"])
    if run is None or run.status == "done":
        return
    run.status, run.error = "running", None
    db.commit()
    progress = _Progress(db, run)
    try:
        _classify(db, run.chat_ids, progress)
        _place_in_topics(db, run.chat_ids, progress)
        _analyze_turns(db, run.chat_ids, progress)
        reviewed = _review(db, run.chat_ids, progress)
        _profile(db, reviewed, progress)
        run.stage, run.status = "done", "done"
    except FATAL as e:
        db.rollback()
        run.status, run.error = "failed", _friendly(e)
    except Exception as e:  # keep the run's own status truthful even for bugs
        log.exception("analysis run %s failed", run.id)
        db.rollback()
        run.status, run.error = "failed", f"{type(e).__name__}: {e}"
    db.commit()


def _friendly(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "Anthropic API key missing or invalid. Set ANTHROPIC_API_KEY in backend/.env (or ENKI_FAKE_LLM=1 to run offline)."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "This API key isn't allowed to use one of the configured models."
    if isinstance(e, anthropic.NotFoundError):
        return "A configured model wasn't found. Check the model ids in backend/enki/config.py."
    return str(e)


def _chats(db: Session, ids: list[int]) -> list[Node]:
    return list(db.scalars(select(Node).where(Node.id.in_(ids), Node.kind == "session").order_by(Node.id)))


# --- classify ---

def _classify(db: Session, chat_ids: list[int], progress: _Progress) -> None:
    todo = [c for c in _chats(db, chat_ids) if c.is_learning is None]
    progress.stage("classify", len(todo))
    inputs = []
    for c in todo:
        users = db.scalars(
            select(Message.content).where(Message.session_id == c.id, Message.role == "user").order_by(Message.id).limit(3)
        )
        inputs.append((c.id, c.title, "\n---\n".join(u[:600] for u in users)))

    def write(item, result) -> None:
        chat = db.get(Node, item[0])
        chat.is_learning = result.is_learning
        chat.topic_label = f"{result.domain.strip()} / {result.topic.strip()}"[:200]
        if not result.is_learning:
            chat.status = "skipped"
        progress.count("learning" if result.is_learning else "skipped")

    _parallel(
        inputs,
        lambda it: get_llm().classify_chat(it[1], it[2]),
        write,
        progress,
        lambda it: f"classifying “{it[1]}”",
        settings.analysis_concurrency,
    )


# --- topic tree ---

def _folder(db: Session, title: str, parent_id: int | None) -> Node:
    title = title.strip()[:200] or "Other"
    q = select(Node).where(Node.kind == "folder", func.lower(Node.title) == title.lower())
    q = q.where(Node.parent_id.is_(None) if parent_id is None else Node.parent_id == parent_id)
    node = db.scalars(q).first()
    if node is None:
        node = Node(kind="folder", title=title, parent_id=parent_id, status="analyzed")
        db.add(node)
        db.flush()
    return node


def existing_tree(db: Session) -> str:
    lines = []
    for d in db.scalars(select(Node).where(Node.kind == "folder", Node.parent_id.is_(None)).order_by(Node.title)):
        topics = db.scalars(select(Node.title).where(Node.kind == "folder", Node.parent_id == d.id).order_by(Node.title))
        lines.append(f"{d.title}: {', '.join(topics)}")
    return "\n".join(lines)


def _place_in_topics(db: Session, chat_ids: list[int], progress: _Progress) -> None:
    unplaced = [c for c in _chats(db, chat_ids) if c.is_learning and c.parent_id is None and c.topic_label]
    progress.stage("topics", 1 if unplaced else 0)
    if not unplaced:
        return
    by_label: dict[str, list[Node]] = defaultdict(list)
    for c in unplaced:
        by_label[c.topic_label].append(c)
    labels = sorted(by_label)
    tree = get_llm().build_topic_tree(existing_tree(db), [f"{label} ({len(by_label[label])} chats)" for label in labels])

    placed: set[int] = set()
    for d in tree.domains:
        domain = _folder(db, d.name, None)
        for t in d.topics:
            topic = _folder(db, t.name, domain.id)
            for i in t.label_ids:
                if 0 <= i < len(labels) and i not in placed:
                    placed.add(i)
                    for c in by_label[labels[i]]:
                        c.parent_id = topic.id
    for i, label in enumerate(labels):  # anything the model left out goes where its own label points
        if i not in placed:
            d_name, _, t_name = label.partition(" / ")
            topic = _folder(db, t_name or "General", _folder(db, d_name, None).id)
            for c in by_label[label]:
                c.parent_id = topic.id
    progress.step()


# --- turns ---

def _learning_ids(db: Session, chat_ids: list[int]) -> list[int]:
    return [c.id for c in _chats(db, chat_ids) if c.is_learning and c.status in ("pending", "failed")]


def _analyze_turns(db: Session, chat_ids: list[int], progress: _Progress) -> None:
    inputs = turn_inputs(db, _learning_ids(db, chat_ids))
    progress.stage("turns", len(inputs))

    def write(t, result) -> None:
        apply_turn(db, t, *result)
        progress.count("turns")

    _parallel(inputs, analyze_turn_call, write, progress, lambda t: f"reply #{t.message_id}", settings.analysis_concurrency)


# --- review ---

def _review(db: Session, chat_ids: list[int], progress: _Progress) -> list[int]:
    inputs = [inp for c in _chats(db, _learning_ids(db, chat_ids)) if (inp := review_input(db, c))]
    progress.stage("review", len(inputs))
    reviewed: list[int] = []

    def write(inp, review) -> None:
        apply_review(db, inp, review)
        reviewed.append(inp.session_id)
        progress.count("reviewed")

    _parallel(inputs, review_call, write, progress, lambda inp: f"reviewing chat {inp.session_id}", settings.review_concurrency)
    failed = set(i.session_id for i in inputs) - set(reviewed)
    for c in _chats(db, list(failed)):
        c.status = "failed"
    db.commit()
    return reviewed


# --- profile ---

def _profile(db: Session, reviewed: list[int], progress: _Progress) -> None:
    topics = {c.parent_id for c in _chats(db, reviewed) if c.parent_id is not None}
    progress.stage("profile", len(topics) + 1)
    llm = get_llm()

    def summarize(topic_id: int):
        topic = db.get(Node, topic_id)
        new = [c.summary for c in _chats(db, reviewed) if c.parent_id == topic_id and c.summary]
        return llm.update_folder_summary(path_title(db, topic), topic.summary, "\n\n".join(new)).summary

    # Topic summaries read from the database, so they run here rather than on the pool.
    for topic_id in sorted(topics):
        try:
            db.get(Node, topic_id).summary = summarize(topic_id)
        except FATAL:
            raise
        except (LLMError, anthropic.AnthropicError) as e:
            progress.fail(f"summarizing topic {topic_id}", e)
        progress.step()

    rollup_global_patterns(db)
    db.flush()
    if db.scalar(select(func.count(Node.id)).where(Node.kind == "session", Node.status == "analyzed")):
        try:
            write_snapshot(db)
        except FATAL:
            raise
        except (LLMError, anthropic.AnthropicError) as e:
            progress.fail("writing the global profile", e)
    progress.step()


def rollup_global_patterns(db: Session) -> list[Pattern]:
    """A pattern seen in two or more topics becomes a global pattern whose evidence is the sum of the topics'."""
    topic_pats = list(
        db.scalars(select(Pattern).where(Pattern.scope_node_id.is_not(None), Pattern.status == "active"))
    )
    groups: dict[tuple[str, str | None], list[Pattern]] = defaultdict(list)
    for p in topic_pats:
        groups[(p.strategy, p.concept_type)].append(p)
    rollups = {
        (g.strategy, g.concept_type): g
        for g in db.scalars(select(Pattern).where(Pattern.scope_node_id.is_(None), Pattern.source == "rollup"))
    }

    out = []
    for key, pats in groups.items():
        g = rollups.get(key)
        qualifies = len({p.scope_node_id for p in pats}) >= 2
        if not qualifies:
            if g is not None and g.user_status == "unreviewed":
                db.delete(g)
            continue
        if g is None:
            g = Pattern(scope_node_id=None, strategy=key[0], concept_type=key[1], source="rollup", claim="")
            db.add(g)
        if g.status == "rejected":
            continue  # the learner rejected it
        g.alpha = 1 + sum(p.alpha - 1 for p in pats) + (CONFIRM_WEIGHT if g.user_status == "confirmed" else 0)
        g.beta = 1 + sum(p.beta - 1 for p in pats)
        g.derived_from = [p.id for p in pats]
        if g.user_status not in ("edited",):
            g.claim = max(pats, key=lambda p: p.evidence_count).claim
        db.flush()
        _surface_rollup(db, g, pats)
        out.append(g)
    return out


def _surface_rollup(db: Session, g: Pattern, pats: list[Pattern]) -> None:
    if g.surfaced or g.user_status != "unreviewed" or g.evidence_count < settings.insight_min_evidence:
        return
    strong_yes = g.confidence >= settings.insight_min_confidence
    if not (strong_yes or g.confidence <= 1 - settings.insight_min_confidence):
        return
    lines = "\n".join(
        f"- **{path_title(db, db.get(Node, p.scope_node_id))}**: {p.confidence:.0%} over {p.evidence_count} episode(s)"
        for p in sorted(pats, key=lambda p: -p.evidence_count)
    )
    title = g.claim if strong_yes else f"This may not work for you: {g.claim[0].lower()}{g.claim[1:]}"
    body = f"This showed up in **{len(pats)} topics**:\n\n{lines}\n\nDoes it match how you learn in general?"
    db.add(Insight(node_id=None, pattern_id=g.id, kind="pattern", title=title, body=body))
    g.surfaced = True


def write_snapshot(db: Session) -> ProfileSnapshot:
    topics = list(db.scalars(select(Node).where(Node.kind == "folder", Node.parent_id.is_not(None))))
    mix = understanding_mix(db)
    analyzed = db.scalar(select(func.count(Node.id)).where(Node.kind == "session", Node.status == "analyzed"))
    lines = [
        f"Analyzed learning chats: {analyzed}",
        f"Judged replies: understood {mix['understood']}, iffy {mix['iffy']}, not understood {mix['not_understood']}",
        "",
        "Cross-topic patterns:",
    ]
    for g in db.scalars(select(Pattern).where(Pattern.scope_node_id.is_(None), Pattern.status == "active")):
        lines.append(f"- {g.claim} — confidence {g.confidence:.2f}, {g.evidence_count} episodes, {g.user_status}")
    lines += ["", "Per topic:"]
    topic_ids = []
    for t in topics:
        pats = sorted(
            db.scalars(select(Pattern).where(Pattern.scope_node_id == t.id, Pattern.status == "active")), key=_rank, reverse=True
        )[:4]
        if not pats and not t.summary:
            continue
        topic_ids.append(t.id)
        lines.append(f"[topic_id={t.id}] {path_title(db, t)}")
        if t.summary:
            lines.append(f"  summary: {t.summary[:500]}")
        for p in pats:
            lines.append(f"  - {p.claim} — confidence {p.confidence:.2f}, {p.evidence_count} episodes, {p.user_status}")
    clicked = db.scalars(select(StickyExplanation.concept).order_by(StickyExplanation.created_at.desc()).limit(8))
    lines += ["", "Recent explanations that clicked: " + ", ".join(clicked)]

    profile = get_llm().write_global_profile("\n".join(lines), topic_ids)
    valid = set(topic_ids)
    snap = ProfileSnapshot(
        headline=profile.headline,
        summary_md=profile.summary_md,
        topic_lines={str(t.topic_id): t.line for t in profile.topic_lines if t.topic_id in valid},
    )
    db.add(snap)
    return snap
