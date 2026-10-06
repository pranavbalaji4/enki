"""Per-chat analysis: tag each Claude reply and judge whether it landed, then review whole chats into episodes,
explanations that clicked, and pattern evidence.

Each step is split into a pure model call (`*_call`, safe to run on a worker thread, touches no database) and a
write (`apply_*`, run on the thread that owns the session), so a run can keep several model calls in flight."""

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .context import patterns_for_prompt
from .evaluators import ClaudeEvaluator, Judgement, get_evaluator, judgement_from_eval
from .llm import get_llm
from .llm_schemas import SessionReview, TagResult
from .models import Episode, Insight, Message, Node, Pattern, PatternEvidence, StickyExplanation, TurnAnnotation
from .taxonomy import NO_SIGNAL

# Long replies are cut to head + tail before analysis; what a reply opens and closes with is what the learner reacts to.
MAX_TURN_CHARS = 12000
MAX_TRANSCRIPT_MSG_CHARS = 6000


def trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n[…]\n" + text[-half:]


# ---------- turns ----------

@dataclass
class TurnInput:
    message_id: int
    session_id: int
    question: str
    reply: str
    next_id: int | None
    next_msg: str | None


def turn_inputs(db: Session, session_ids: list[int]) -> list[TurnInput]:
    """Every Claude reply in these chats that hasn't been analyzed yet, with the user turns around it."""
    done = set(
        db.scalars(
            select(TurnAnnotation.message_id).where(
                TurnAnnotation.session_id.in_(session_ids), TurnAnnotation.verdict.is_not(None)
            )
        )
    )
    out = []
    for sid in session_ids:
        msgs = list(db.scalars(select(Message).where(Message.session_id == sid).order_by(Message.id)))
        for i, m in enumerate(msgs):
            if m.role != "assistant" or m.id in done:
                continue
            prev = next((p for p in reversed(msgs[:i]) if p.role == "user"), None)
            nxt = next((n for n in msgs[i + 1:] if n.role == "user"), None)
            out.append(
                TurnInput(m.id, sid, prev.content if prev else "", m.content, nxt.id if nxt else None, nxt.content if nxt else None)
            )
    return out


def analyze_turn_call(t: TurnInput) -> tuple[TagResult, Judgement | None]:
    """With the Claude evaluator, tagging and judging share one call; Jev judges separately."""
    question, reply = trim(t.question, MAX_TURN_CHARS), trim(t.reply, MAX_TURN_CHARS)
    llm = get_llm()
    if t.next_msg is None:
        return llm.tag_turn(question, reply), None
    next_msg = trim(t.next_msg, MAX_TURN_CHARS)
    evaluator = get_evaluator()
    if isinstance(evaluator, ClaudeEvaluator):
        r = llm.analyze_turn(question, reply, next_msg)
        return r.tag, judgement_from_eval(r.evaluation)
    return llm.tag_turn(question, reply), evaluator.judge(question, reply, next_msg)


def apply_turn(db: Session, t: TurnInput, tag: TagResult, j: Judgement | None) -> None:
    ann = db.scalars(select(TurnAnnotation).where(TurnAnnotation.message_id == t.message_id)).first()
    if ann is None:
        ann = TurnAnnotation(message_id=t.message_id, session_id=t.session_id, strategies=[])
        db.add(ann)
    ann.concept = tag.concept
    ann.concept_type = tag.concept_type
    ann.strategies = list(tag.strategies)
    ann.ordering = tag.ordering
    ann.abstraction = tag.abstraction
    if j is None:
        # The chat ended on this reply: nothing to judge it by.
        ann.verdict = NO_SIGNAL
        return
    ann.next_message_id = t.next_id
    ann.verdict = j.verdict
    ann.understanding = j.understanding
    ann.confidence = j.confidence
    ann.referenced_part = j.referenced_part
    ann.reasoning = j.reasoning
    ann.evaluator = j.evaluator
    ann.level_probs = j.level_probs
    ann.signals = j.signals or None


# ---------- chat review ----------

def build_transcript(messages: list[Message], anns: dict[int, TurnAnnotation], max_chars: int | None = None) -> str:
    out = []
    for m in messages:
        content = trim(m.content, max_chars) if max_chars else m.content
        if m.role == "user":
            out.append(f"[#{m.id} learner]\n{content}\n")
            continue
        a = anns.get(m.id)
        meta = ""
        if a:
            meta = f" | concept={a.concept} | strategies={','.join(a.strategies or [])} | ordering={a.ordering}"
            if a.verdict and a.verdict != NO_SIGNAL:
                meta += f" | verdict={a.verdict} u={a.understanding:.2f} conf={a.confidence:.2f}"
            if a.level_probs:
                meta += " | p(not,iffy,understood)=" + ",".join(f"{p:.2f}" for p in a.level_probs)
            for name, p in (a.signals or {}).items():
                meta += f" | p({name})={p:.2f}"
        out.append(f"[#{m.id} tutor{meta}]\n{content}\n")
    return "\n".join(out)


def undo_review(db: Session, session_id: int) -> None:
    """Re-reviewing a chat replaces its episodes; take their evidence back out of the pattern stats first."""
    old_eps = list(db.scalars(select(Episode.id).where(Episode.session_id == session_id)))
    if old_eps:
        for ev in db.scalars(select(PatternEvidence).where(PatternEvidence.episode_id.in_(old_eps))):
            p = db.get(Pattern, ev.pattern_id)
            if ev.supports:
                p.alpha = max(1.0, p.alpha - 1)
            else:
                p.beta = max(1.0, p.beta - 1)
        db.execute(delete(PatternEvidence).where(PatternEvidence.episode_id.in_(old_eps)))
        db.execute(delete(StickyExplanation).where(StickyExplanation.episode_id.in_(old_eps)))
        db.execute(delete(Episode).where(Episode.id.in_(old_eps)))
    db.execute(delete(Insight).where(Insight.session_id == session_id, Insight.kind == "recap"))


def scope_patterns(db: Session, scope_id: int | None) -> list[Pattern]:
    q = select(Pattern).where(Pattern.scope_node_id.is_(None) if scope_id is None else Pattern.scope_node_id == scope_id)
    return list(db.scalars(q))


@dataclass
class ReviewInput:
    session_id: int
    scope_id: int | None
    transcript: str
    patterns: str
    message_ids: list[int]


def review_input(db: Session, session: Node) -> ReviewInput | None:
    messages = list(db.scalars(select(Message).where(Message.session_id == session.id).order_by(Message.id)))
    if not messages:
        return None
    anns = {a.message_id: a for a in db.scalars(select(TurnAnnotation).where(TurnAnnotation.session_id == session.id))}
    scope_id = session.parent_id  # patterns are learned at the chat's topic
    return ReviewInput(
        session_id=session.id,
        scope_id=scope_id,
        transcript=build_transcript(messages, anns, MAX_TRANSCRIPT_MSG_CHARS),
        patterns=patterns_for_prompt([p for p in scope_patterns(db, scope_id) if p.status == "active"]),
        message_ids=[m.id for m in messages],
    )


def review_call(inp: ReviewInput) -> SessionReview:
    return get_llm().review_session(inp.transcript, inp.patterns, inp.message_ids)


def apply_review(db: Session, inp: ReviewInput, review: SessionReview) -> None:
    session = db.get(Node, inp.session_id)
    if session is None:
        return
    undo_review(db, session.id)
    valid_ids = set(inp.message_ids)

    episodes: list[Episode] = []
    for e in review.episodes:
        ep = Episode(
            session_id=session.id,
            concept=e.concept[:200],
            concept_type=e.concept_type,
            outcome=e.outcome,
            message_ids=[i for i in e.message_ids if i in valid_ids],
            click_message_id=e.click_message_id if e.click_message_id in valid_ids else None,
            winning_message_id=e.winning_message_id if e.winning_message_id in valid_ids else None,
            path_summary=e.path_summary,
            why_it_clicked=e.why_it_clicked,
            prompting_moves=list(e.prompting_moves),
        )
        db.add(ep)
        episodes.append(ep)
    db.flush()

    for ep, e in zip(episodes, review.episodes):
        if e.outcome != "not_yet" and e.sticky_excerpt.strip():
            db.add(
                StickyExplanation(
                    episode_id=ep.id,
                    session_id=session.id,
                    concept=ep.concept,
                    excerpt=e.sticky_excerpt.strip()[:1500],
                    why=e.why_it_clicked,
                )
            )

    # Read the scope's patterns now, not when the review was requested: another review in the same topic may have
    # created one in between, and two patterns for the same strategy would split the evidence.
    existing = scope_patterns(db, inp.scope_id)
    by_id = {p.id: p for p in existing}
    by_key = {(p.strategy, p.concept_type): p for p in existing}
    touched: dict[int, Pattern] = {}
    recorded: set[tuple[int, int]] = set()
    for o in review.observations:
        if not 0 <= o.episode_index < len(episodes):
            continue
        ep = episodes[o.episode_index]
        p = by_id.get(o.existing_pattern_id) if o.existing_pattern_id is not None else None
        p = p or by_key.get((o.strategy, o.concept_type))
        if p is None:
            p = Pattern(scope_node_id=inp.scope_id, claim=o.claim, strategy=o.strategy, concept_type=o.concept_type)
            db.add(p)
            db.flush()
            by_id[p.id] = p
            by_key[(p.strategy, p.concept_type)] = p
        if p.status != "active" or (p.id, ep.id) in recorded:
            continue  # the learner rejected this pattern; don't keep building it back up
        recorded.add((p.id, ep.id))
        if o.supports:
            p.alpha += 1
        else:
            p.beta += 1
        db.add(PatternEvidence(pattern_id=p.id, episode_id=ep.id, supports=o.supports, note=o.note))
        touched[p.id] = p

    session.summary = review.session_summary
    session.status = "analyzed"
    db.add(Insight(node_id=inp.scope_id, session_id=session.id, kind="recap", title=review.recap_title, body=review.recap_body))
    db.flush()
    for p in touched.values():
        maybe_surface(db, p)


def maybe_surface(db: Session, p: Pattern) -> None:
    """Turn a pattern into an insight card once it has enough evidence, in either direction."""
    if p.surfaced or p.user_status != "unreviewed" or p.evidence_count < settings.insight_min_evidence:
        return
    strong_yes = p.confidence >= settings.insight_min_confidence
    strong_no = p.confidence <= 1 - settings.insight_min_confidence
    if not (strong_yes or strong_no):
        return
    evidence = list(
        db.execute(
            select(Episode, PatternEvidence.supports)
            .join(PatternEvidence, PatternEvidence.episode_id == Episode.id)
            .where(PatternEvidence.pattern_id == p.id)
            .order_by(Episode.created_at.desc())
        )
    )
    n_yes = sum(1 for _, s in evidence if s)
    n = len(evidence)
    title = p.claim if strong_yes else f"This may not work for you: {p.claim[0].lower()}{p.claim[1:]}"
    moments = "\n".join(
        f"- {'✓' if s else '✗'} **{ep.concept}** — {ep.path_summary}" for ep, s in evidence[:3]
    )
    body = f"In **{n_yes} of {n}** episodes the evidence {'supported' if strong_yes else 'went against'} this.\n\n{moments}\n\nDoes this match your experience?"
    db.add(Insight(node_id=p.scope_node_id, pattern_id=p.id, kind="pattern", title=title, body=body))
    p.surfaced = True
