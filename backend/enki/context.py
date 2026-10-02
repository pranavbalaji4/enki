"""Tree walking, the scoped profile slice, and the markdown profile view."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import prompts
from .config import settings
from .models import Message, Node, Pattern, StickyExplanation


def ancestors(db: Session, node: Node) -> list[Node]:
    """Folders above `node`, nearest first (not including `node`)."""
    out, cur = [], node
    while cur.parent_id is not None:
        cur = db.get(Node, cur.parent_id)
        out.append(cur)
    return out


def path_title(db: Session, node: Node) -> str:
    return " / ".join([n.title for n in reversed(ancestors(db, node))] + [node.title])


def descendants(db: Session, node_id: int) -> list[int]:
    ids, frontier = [node_id], [node_id]
    while frontier:
        frontier = list(db.scalars(select(Node.id).where(Node.parent_id.in_(frontier))))
        ids += frontier
    return ids


def scope_for_session(session: Node) -> int | None:
    """MVP: patterns are learned at the session's parent folder (the "topic"); a root-level chat learns globally."""
    return session.parent_id


def patterns_in_scope_chain(db: Session, node: Node) -> list[tuple[Pattern, str]]:
    """Active patterns visible from `node`: its own scope, then each ancestor, then global. Lower scopes win
    when two patterns share a strategy + concept type."""
    chain: list[tuple[int | None, str]] = []
    if node.kind == "folder":
        chain.append((node.id, node.title))
    chain += [(a.id, a.title) for a in ancestors(db, node)]
    chain.append((None, "Global"))

    seen: set[tuple[str, str | None]] = set()
    out: list[tuple[Pattern, str]] = []
    for scope_id, scope_title in chain:
        q = select(Pattern).where(Pattern.status == "active")
        q = q.where(Pattern.scope_node_id.is_(None) if scope_id is None else Pattern.scope_node_id == scope_id)
        for p in db.scalars(q):
            key = (p.strategy, p.concept_type)
            if key in seen:
                continue
            seen.add(key)
            out.append((p, scope_title))
    return out


def _rank(p: Pattern) -> float:
    boost = 0.3 if p.user_status in ("confirmed", "edited") or p.source == "user" else 0.0
    return p.confidence + boost + min(p.evidence_count, 10) * 0.01


def profile_slice(db: Session, node: Node) -> str:
    items = sorted(patterns_in_scope_chain(db, node), key=lambda t: _rank(t[0]), reverse=True)[: settings.profile_top_k]
    lines = []
    for p, scope in items:
        if p.source == "user" or p.user_status in ("confirmed", "edited"):
            basis = "stated/confirmed by the learner"
        else:
            basis = f"observed, confidence {p.confidence:.2f} over {p.evidence_count} episode(s)"
            if p.evidence_count < 2:
                basis += " — tentative, keep testing it"
        applies = f" (for {p.concept_type.replace('_', ' ')} concepts)" if p.concept_type else ""
        note = f" Learner's note: {p.user_note}" if p.user_note else ""
        lines.append(f"- [{scope}] {p.claim}{applies} — {basis}.{note}")
    return "\n".join(lines)


def folder_context(db: Session, session: Node) -> str:
    return "\n".join(f"{a.title}: {a.summary}" for a in reversed(ancestors(db, session)) if a.summary)


def sticky_context(db: Session, session: Node) -> str:
    """Explanations that clicked in this session's topic subtree (siblings included — same concept family)."""
    scope = session.parent_id
    session_ids = descendants(db, scope) if scope is not None else [session.id]
    rows = db.scalars(
        select(StickyExplanation)
        .where(StickyExplanation.session_id.in_(session_ids))
        .order_by(StickyExplanation.created_at.desc())
        .limit(settings.sticky_top_k)
    )
    return "\n\n".join(f"[{s.concept}] {s.excerpt}" for s in rows)


def build_tutor_request(db: Session, session: Node) -> tuple[str, list[dict]]:
    system = prompts.tutor_system(
        workspace_path=path_title(db, session),
        profile=profile_slice(db, session),
        folder_context=folder_context(db, session),
        sticky=sticky_context(db, session),
        session_summary=session.summary,
    )
    history = db.scalars(select(Message).where(Message.session_id == session.id).order_by(Message.id))
    messages = [{"role": m.role, "content": m.content} for m in history]
    return system, messages


def patterns_for_prompt(patterns: list[Pattern]) -> str:
    return "\n".join(
        f"- [id={p.id}] strategy={p.strategy} concept_type={p.concept_type or 'any'} "
        f"confidence={p.confidence:.2f} n={p.evidence_count} status={p.user_status}: {p.claim}"
        for p in patterns
    )


def render_profile_md(db: Session, node: Node | None) -> str:
    """Readable, editable view of the patterns scoped exactly at `node` (None = global)."""
    title = "Global" if node is None else node.title
    q = select(Pattern).where(Pattern.status == "active")
    q = q.where(Pattern.scope_node_id.is_(None) if node is None else Pattern.scope_node_id == node.id)
    pats = sorted(db.scalars(q), key=_rank, reverse=True)

    lines = [f"# How I learn — {title}", ""]
    if not pats:
        lines.append("_No patterns yet. Finish a session with “Wrap up” and Enki will start learning how you learn here._")
    for p in pats:
        tag = "✓" if p.user_status in ("confirmed", "edited") or p.source == "user" else f"{p.confidence:.0%}"
        applies = f" _(for {p.concept_type.replace('_', ' ')} concepts)_" if p.concept_type else ""
        lines.append(f"- {p.claim}{applies} — {tag}, {p.evidence_count} episode(s)")
        if p.user_note:
            lines.append(f"  - Note: {p.user_note}")
    return "\n".join(lines).rstrip() + "\n"


def stickies_under(db: Session, node: Node | None, limit: int = 20) -> list[StickyExplanation]:
    q = select(StickyExplanation).order_by(StickyExplanation.created_at.desc()).limit(limit)
    if node is not None:
        q = q.where(StickyExplanation.session_id.in_(descendants(db, node.id)))
    return list(db.scalars(q))
