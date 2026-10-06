"""Read-side views of the analyzed data, shared by the API and the Ask chat's tools. Plain dicts in, plain dicts out."""

from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .context import _rank, ancestors, descendants, path_title, stickies_under
from .models import Episode, Message, Node, Pattern, ProfileSnapshot, StickyExplanation, TurnAnnotation
from .taxonomy import NO_SIGNAL

LEVEL_NAMES = ["not_understood", "iffy", "understood"]


def level_of(a: TurnAnnotation) -> int | None:
    """Most likely understanding level of a judged reply: 0 not understood, 1 iffy, 2 understood."""
    if not a.verdict or a.verdict == NO_SIGNAL:
        return None
    if a.level_probs and len(a.level_probs) == 3:
        return max(range(3), key=lambda i: a.level_probs[i])
    u = a.understanding if a.understanding is not None else 0.5
    return 2 if u >= 0.7 else 1 if u >= 0.45 else 0


def empty_mix() -> dict[str, int]:
    return {name: 0 for name in LEVEL_NAMES}


def _judged(db: Session, session_ids: list[int] | None = None) -> list[TurnAnnotation]:
    q = select(TurnAnnotation).where(TurnAnnotation.verdict.is_not(None), TurnAnnotation.verdict != NO_SIGNAL)
    if session_ids is not None:
        q = q.where(TurnAnnotation.session_id.in_(session_ids))
    return list(db.scalars(q))


def understanding_mix(db: Session, session_ids: list[int] | None = None) -> dict[str, int]:
    mix = empty_mix()
    for a in _judged(db, session_ids):
        level = level_of(a)
        if level is not None:
            mix[LEVEL_NAMES[level]] += 1
    return mix


def pattern_dict(db: Session, p: Pattern) -> dict:
    scope = path_title(db, db.get(Node, p.scope_node_id)) if p.scope_node_id else "Global"
    topics: list[str] = []
    if p.derived_from:
        for pid in p.derived_from:
            src = db.get(Pattern, pid)
            if src is not None and src.scope_node_id:
                topics.append(path_title(db, db.get(Node, src.scope_node_id)))
    return {
        "id": p.id,
        "claim": p.claim,
        "strategy": p.strategy,
        "concept_type": p.concept_type,
        "confidence": round(p.confidence, 3),
        "evidence_count": p.evidence_count,
        "user_status": p.user_status,
        "user_note": p.user_note,
        "source": p.source,
        "scope_id": p.scope_node_id,
        "scope": scope,
        "topics": topics,
    }


def sticky_dict(db: Session, s: StickyExplanation) -> dict:
    chat = db.get(Node, s.session_id)
    return {
        "id": s.id,
        "session_id": s.session_id,
        "chat_title": chat.title if chat else "",
        "concept": s.concept,
        "excerpt": s.excerpt,
        "why": s.why,
    }


def topic_tree(db: Session) -> list[dict]:
    """Every topic folder with chat counts and understanding, rolled up from its chats (and sub-topics)."""
    folders = list(db.scalars(select(Node).where(Node.kind == "folder")))
    chats = list(db.scalars(select(Node).where(Node.kind == "session", Node.is_learning.is_(True))))
    by_id = {f.id: f for f in folders}
    per_chat: dict[int, list[TurnAnnotation]] = defaultdict(list)
    for a in _judged(db, [c.id for c in chats]):
        per_chat[a.session_id].append(a)

    stats: dict[int, dict] = {f.id: {"chats": 0, "analyzed": 0, "u_sum": 0.0, "mix": empty_mix()} for f in folders}
    for c in chats:
        cur = by_id.get(c.parent_id) if c.parent_id else None
        while cur is not None:
            st = stats[cur.id]
            st["chats"] += 1
            st["analyzed"] += c.status == "analyzed"
            for a in per_chat[c.id]:
                st["u_sum"] += a.understanding or 0.0
                level = level_of(a)
                if level is not None:
                    st["mix"][LEVEL_NAMES[level]] += 1
            cur = by_id.get(cur.parent_id) if cur.parent_id else None

    snap = latest_snapshot(db)
    lines = (snap.topic_lines or {}) if snap else {}
    out = []
    for f in sorted(folders, key=lambda f: f.title.lower()):
        st = stats[f.id]
        judged = sum(st["mix"].values())
        out.append(
            {
                "id": f.id,
                "parent_id": f.parent_id,
                "title": f.title,
                "path": path_title(db, f),
                "chat_count": st["chats"],
                "analyzed_count": st["analyzed"],
                "judged_turns": judged,
                "avg_understanding": round(st["u_sum"] / judged, 3) if judged else None,
                "mix": st["mix"],
                "line": lines.get(str(f.id), ""),
            }
        )
    return out


def latest_snapshot(db: Session) -> ProfileSnapshot | None:
    return db.scalars(select(ProfileSnapshot).order_by(ProfileSnapshot.id.desc()).limit(1)).first()


def overview(db: Session) -> dict:
    snap = latest_snapshot(db)
    sessions = select(func.count(Node.id)).where(Node.kind == "session")
    global_pats = sorted(
        db.scalars(select(Pattern).where(Pattern.scope_node_id.is_(None), Pattern.status == "active")), key=_rank, reverse=True
    )
    topic_pats = sorted(
        db.scalars(select(Pattern).where(Pattern.scope_node_id.is_not(None), Pattern.status == "active")),
        key=_rank,
        reverse=True,
    )[:8]
    return {
        "snapshot": (
            {"headline": snap.headline, "summary_md": snap.summary_md, "created_at": snap.created_at} if snap else None
        ),
        "stats": {
            "chats": db.scalar(sessions) or 0,
            "learning_chats": db.scalar(sessions.where(Node.is_learning.is_(True))) or 0,
            "analyzed_chats": db.scalar(sessions.where(Node.status == "analyzed")) or 0,
            "pending_chats": db.scalar(sessions.where(Node.status.in_(["pending", "failed"]), Node.is_learning.is_not(False))) or 0,
            "topics": db.scalar(select(func.count(Node.id)).where(Node.kind == "folder", Node.parent_id.is_not(None))) or 0,
        },
        "mix": understanding_mix(db),
        "topics": topic_tree(db),
        "global_patterns": [pattern_dict(db, p) for p in global_pats],
        "top_patterns": [pattern_dict(db, p) for p in topic_pats],
        "stickies": [sticky_dict(db, s) for s in stickies_under(db, None, limit=6)],
    }


def chat_summary(db: Session, c: Node, anns: list[TurnAnnotation] | None = None) -> dict:
    anns = anns if anns is not None else _judged(db, [c.id])
    mix = empty_mix()
    for a in anns:
        level = level_of(a)
        if level is not None:
            mix[LEVEL_NAMES[level]] += 1
    judged = sum(mix.values())
    return {
        "id": c.id,
        "title": c.title,
        "started_at": c.started_at or c.created_at,
        "status": c.status,
        "is_learning": c.is_learning,
        "judged_turns": judged,
        "avg_understanding": round(sum(a.understanding or 0 for a in anns) / judged, 3) if judged else None,
        "mix": mix,
    }


def topic_detail(db: Session, topic: Node) -> dict:
    ids = descendants(db, topic.id)
    chats = list(
        db.scalars(
            select(Node)
            .where(Node.id.in_(ids), Node.kind == "session")
            .order_by(func.coalesce(Node.started_at, Node.created_at).desc())
        )
    )
    judged_by_chat: dict[int, list[TurnAnnotation]] = defaultdict(list)
    for a in _judged(db, [c.id for c in chats]):
        judged_by_chat[a.session_id].append(a)
    folder_ids = [i for i in ids if (n := db.get(Node, i)) is not None and n.kind == "folder"]
    pats = sorted(
        db.scalars(select(Pattern).where(Pattern.scope_node_id.in_(folder_ids), Pattern.status == "active")),
        key=_rank,
        reverse=True,
    )
    tree = {t["id"]: t for t in topic_tree(db)}
    return {
        "topic": tree[topic.id],
        "summary": topic.summary,
        "breadcrumbs": [{"id": a.id, "title": a.title} for a in reversed(ancestors(db, topic))],
        "children": [t for t in tree.values() if t["parent_id"] == topic.id],
        "patterns": [pattern_dict(db, p) for p in pats],
        "stickies": [sticky_dict(db, s) for s in stickies_under(db, topic, limit=12)],
        "chats": [chat_summary(db, c, judged_by_chat[c.id]) for c in chats],
    }


def search_turns(
    db: Session, query: str | None = None, level: str | None = None, topic_id: int | None = None, limit: int = 10
) -> list[dict]:
    """Judged Claude replies, newest first, filtered by text (in the reply or the question), level and topic."""
    q = (
        select(TurnAnnotation, Message, Node)
        .join(Message, Message.id == TurnAnnotation.message_id)
        .join(Node, Node.id == TurnAnnotation.session_id)
        .where(TurnAnnotation.verdict.is_not(None), TurnAnnotation.verdict != NO_SIGNAL)
        .order_by(Message.id.desc())
    )
    if topic_id is not None:
        q = q.where(TurnAnnotation.session_id.in_(descendants(db, topic_id)))
    if query:
        like = f"%{query}%"
        q = q.where(or_(Message.content.ilike(like), TurnAnnotation.concept.ilike(like), Node.title.ilike(like)))
    out = []
    for a, m, chat in db.execute(q):
        lv = level_of(a)
        if level and (lv is None or LEVEL_NAMES[lv] != level):
            continue
        question = db.scalars(
            select(Message.content)
            .where(Message.session_id == m.session_id, Message.role == "user", Message.id < m.id)
            .order_by(Message.id.desc())
            .limit(1)
        ).first()
        nxt = db.get(Message, a.next_message_id) if a.next_message_id else None
        out.append(
            {
                "chat_id": chat.id,
                "chat_title": chat.title,
                "message_id": m.id,
                "concept": a.concept,
                "strategies": a.strategies or [],
                "level": LEVEL_NAMES[lv] if lv is not None else None,
                "level_probs": a.level_probs,
                "verdict": a.verdict,
                "question": (question or "")[:300],
                "reply_start": m.content[:400],
                "next_message": nxt.content[:300] if nxt else "",
            }
        )
        if len(out) >= limit:
            break
    return out


def chat_for_ask(db: Session, chat: Node, max_chars: int = 1200) -> dict:
    msgs = list(db.scalars(select(Message).where(Message.session_id == chat.id).order_by(Message.id)))
    anns = {a.message_id: a for a in db.scalars(select(TurnAnnotation).where(TurnAnnotation.session_id == chat.id))}
    turns = []
    for m in msgs:
        t = {"id": m.id, "role": m.role, "text": m.content[:max_chars] + ("…" if len(m.content) > max_chars else "")}
        a = anns.get(m.id)
        if a is not None:
            lv = level_of(a)
            t.update(
                strategies=a.strategies or [],
                verdict=a.verdict,
                level=LEVEL_NAMES[lv] if lv is not None else None,
                level_probs=a.level_probs,
            )
        turns.append(t)
    eps = db.scalars(select(Episode).where(Episode.session_id == chat.id))
    return {
        "id": chat.id,
        "title": chat.title,
        "path": path_title(db, chat),
        "summary": chat.summary,
        "episodes": [
            {"concept": e.concept, "outcome": e.outcome, "path": e.path_summary, "why": e.why_it_clicked} for e in eps
        ],
        "turns": turns,
    }
