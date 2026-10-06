"""Tree walking and the markdown profile view."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Node, Pattern, StickyExplanation


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


def _rank(p: Pattern) -> float:
    boost = 0.3 if p.user_status in ("confirmed", "edited") or p.source == "user" else 0.0
    return p.confidence + boost + min(p.evidence_count, 10) * 0.01


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
        lines.append("_No patterns yet. Import and analyze more chats in this topic and Enki will start learning how you learn here._")
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
