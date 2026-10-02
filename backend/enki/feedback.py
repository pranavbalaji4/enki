"""Learner feedback: markdown profile edits and insight-card responses. The strongest signals in the system."""

from sqlalchemy.orm import Session

from .context import patterns_for_prompt, render_profile_md
from .llm import get_llm
from .llm_schemas import ProfileEditOp
from .models import Insight, Node, Pattern
from .pipeline import scope_patterns

CONFIRM_WEIGHT = 2.0  # a confirmation counts as two supporting episodes


def apply_profile_edit(db: Session, node: Node | None, new_md: str) -> dict:
    scope_id = node.id if node else None
    old_md = render_profile_md(db, node)
    if new_md.strip() == old_md.strip():
        return {"understood": "No changes.", "ops": [], "markdown": old_md}
    patterns = [p for p in scope_patterns(db, scope_id) if p.status == "active"]
    result = get_llm().interpret_profile_edit(old_md, new_md, patterns_for_prompt(patterns))

    by_id = {p.id: p for p in patterns}
    applied = []
    for op in result.ops:
        desc = _apply_op(db, op, by_id, scope_id, node)
        if desc:
            applied.append(desc)
    db.commit()
    return {"understood": result.understood, "ops": applied, "markdown": render_profile_md(db, node)}


def _apply_op(db: Session, op: ProfileEditOp, by_id: dict[int, Pattern], scope_id: int | None, node: Node | None) -> str | None:
    p = by_id.get(op.pattern_id) if op.pattern_id is not None else None
    if op.op == "add":
        db.add(
            Pattern(
                scope_node_id=scope_id,
                claim=op.claim,
                strategy=op.strategy or "user_stated",
                concept_type=op.concept_type,
                source="user",
                user_status="confirmed",
                alpha=1 + CONFIRM_WEIGHT,
                surfaced=True,
            )
        )
        return f"Added: {op.claim}"
    if op.op == "note" and p is None:
        if node is not None and op.note:
            node.summary = (node.summary + f"\nLearner note: {op.note}").strip()
            return f"Noted for this folder: {op.note}"
        return None
    if p is None:
        return None
    if op.op == "confirm":
        p.user_status = "confirmed"
        p.alpha += CONFIRM_WEIGHT
        return f"Confirmed: {p.claim}"
    if op.op == "reject":
        p.status = "rejected"
        p.user_status = "rejected"
        return f"Removed: {p.claim}"
    if op.op == "update_claim" and op.claim:
        before = p.claim
        p.claim = op.claim
        p.user_status = "edited"
        return f"Reworded: “{before}” → “{op.claim}”"
    if op.op == "note" and op.note:
        p.user_note = (p.user_note + " " + op.note).strip()
        return f"Note on “{p.claim}”: {op.note}"
    return None


def insight_feedback(db: Session, insight: Insight, action: str, note: str = "") -> None:
    insight.user_note = note
    p = db.get(Pattern, insight.pattern_id) if insight.pattern_id else None
    if action == "confirm":
        insight.status = "confirmed"
        if p:
            p.user_status = "confirmed"
            p.alpha += CONFIRM_WEIGHT
    elif action == "reject":
        insight.status = "rejected"
        if p:
            p.user_status = "rejected"
            p.status = "rejected"
    else:
        insight.status = "dismissed"
    if p and note:
        p.user_note = (p.user_note + " " + note).strip()
    db.commit()
