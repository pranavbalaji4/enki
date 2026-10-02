"""Background analysis: tag each tutor turn, evaluate it against the learner's next turn, review whole sessions.

Every handler calls the model BEFORE writing anything, so no database write lock is held during a model call."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .context import patterns_for_prompt, path_title, scope_for_session
from .evaluators import get_evaluator
from .jobs import handler
from .llm import get_llm
from .models import Episode, Insight, Message, Node, Pattern, PatternEvidence, StickyExplanation, TurnAnnotation


def _annotation(db: Session, msg: Message) -> TurnAnnotation:
    ann = db.scalars(select(TurnAnnotation).where(TurnAnnotation.message_id == msg.id)).first()
    if ann is None:
        ann = TurnAnnotation(message_id=msg.id, session_id=msg.session_id, strategies=[])
        db.add(ann)
    return ann


def _previous_user_text(db: Session, msg: Message) -> str:
    prev = db.scalars(
        select(Message)
        .where(Message.session_id == msg.session_id, Message.role == "user", Message.id < msg.id)
        .order_by(Message.id.desc())
        .limit(1)
    ).first()
    return prev.content if prev else ""


@handler("tag_turn")
def tag_turn(db: Session, payload: dict) -> None:
    msg = db.get(Message, payload["message_id"])
    if msg is None:
        return
    result = get_llm().tag_turn(_previous_user_text(db, msg), msg.content)
    ann = _annotation(db, msg)
    ann.concept = result.concept
    ann.concept_type = result.concept_type
    ann.strategies = list(result.strategies)
    ann.ordering = result.ordering
    ann.abstraction = result.abstraction


@handler("evaluate_turn")
def evaluate_turn(db: Session, payload: dict) -> None:
    reply = db.get(Message, payload["assistant_id"])
    nxt = db.get(Message, payload["next_id"])
    if reply is None or nxt is None:
        return
    j = get_evaluator().judge(_previous_user_text(db, reply), reply.content, nxt.content)
    ann = _annotation(db, reply)
    ann.next_message_id = nxt.id
    ann.verdict = j.verdict
    ann.understanding = j.understanding
    ann.confidence = j.confidence
    ann.referenced_part = j.referenced_part
    ann.reasoning = j.reasoning
    ann.evaluator = j.evaluator
    ann.level_probs = j.level_probs
    ann.signals = j.signals or None


def build_transcript(messages: list[Message], anns: dict[int, TurnAnnotation]) -> str:
    out = []
    for m in messages:
        if m.role == "user":
            out.append(f"[#{m.id} learner]\n{m.content}\n")
            continue
        a = anns.get(m.id)
        meta = ""
        if a:
            meta = f" | concept={a.concept} | strategies={','.join(a.strategies or [])} | ordering={a.ordering}"
            if a.verdict:
                meta += f" | verdict={a.verdict} u={a.understanding:.2f} conf={a.confidence:.2f}"
            if a.level_probs:
                meta += " | p(not,iffy,understood)=" + ",".join(f"{p:.2f}" for p in a.level_probs)
            for name, p in (a.signals or {}).items():
                meta += f" | p({name})={p:.2f}"
        out.append(f"[#{m.id} tutor{meta}]\n{m.content}\n")
    return "\n".join(out)


def _undo_previous_review(db: Session, session_id: int) -> None:
    """Re-reviewing a session replaces its episodes; take their evidence back out of the pattern stats first."""
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


@handler("review_session")
def review_session(db: Session, payload: dict) -> None:
    session = db.get(Node, payload["session_id"])
    if session is None:
        return
    messages = list(db.scalars(select(Message).where(Message.session_id == session.id).order_by(Message.id)))
    if not messages:
        session.status = "active"
        return
    anns = {
        a.message_id: a
        for a in db.scalars(select(TurnAnnotation).where(TurnAnnotation.session_id == session.id))
    }
    scope_id = scope_for_session(session)
    existing = scope_patterns(db, scope_id)
    valid_ids = {m.id for m in messages}

    llm = get_llm()
    review = llm.review_session(
        build_transcript(messages, anns),
        patterns_for_prompt([p for p in existing if p.status == "active"]),
        [m.id for m in messages],
    )
    folder = db.get(Node, scope_id) if scope_id is not None else None
    folder_summary = (
        llm.update_folder_summary(path_title(db, folder), folder.summary, review.session_summary).summary
        if folder is not None
        else None
    )

    # ---- write phase ----
    _undo_previous_review(db, session.id)

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
            p = Pattern(scope_node_id=scope_id, claim=o.claim, strategy=o.strategy, concept_type=o.concept_type)
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
    session.status = "reviewed"
    if folder is not None and folder_summary is not None:
        folder.summary = folder_summary

    db.add(
        Insight(
            node_id=scope_id,
            session_id=session.id,
            kind="recap",
            title=review.recap_title,
            body=review.recap_body,
        )
    )
    db.flush()
    for p in touched.values():
        _maybe_surface(db, p)


def _maybe_surface(db: Session, p: Pattern) -> None:
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
