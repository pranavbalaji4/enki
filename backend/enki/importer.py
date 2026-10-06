"""Read a claude.ai data export (Settings -> Privacy -> Export data) into chats and messages.

The export is a ZIP holding `conversations.json`: a list of conversations, each with `chat_messages`. Fields have
shifted over time, so parsing is lenient: text comes from `content` blocks when present, else `text`; when messages
carry `parent_message_uuid` (edits and retries create branches) only the branch that ends at the latest message is kept.
"""

import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import Message, Node
from .pipeline import undo_review


class ExportError(ValueError):
    pass


@dataclass
class ParsedMessage:
    uuid: str
    role: str  # user | assistant
    text: str
    created_at: datetime | None


@dataclass
class ParsedChat:
    uuid: str
    title: str
    created_at: datetime | None
    updated_at: str
    messages: list[ParsedMessage] = field(default_factory=list)


@dataclass
class ImportResult:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    empty: int = 0


def _time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _message_text(m: dict) -> str:
    parts: list[str] = []
    blocks = m.get("content")
    if isinstance(blocks, list) and blocks:
        for b in blocks:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text" and b.get("text"):
                parts.append(b["text"])
            elif kind == "tool_use":
                parts.append(f"[used tool: {b.get('name', 'tool')}]")
            # thinking, tool_result and other block types carry no signal about the learner
    elif isinstance(m.get("text"), str):
        parts.append(m["text"])
    for key in ("attachments", "files"):
        for a in m.get(key) or []:
            if isinstance(a, dict) and a.get("file_name"):
                parts.append(f"[{'attachment' if key == 'attachments' else 'file'}: {a['file_name']}]")
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _main_branch(raw: list[dict]) -> list[dict]:
    """Messages on the path from the root to the most recent message, oldest first."""
    if not raw or not all(isinstance(m, dict) and "parent_message_uuid" in m for m in raw):
        return raw
    by_id = {m.get("uuid"): m for m in raw}
    latest = max(raw, key=lambda m: m.get("created_at") or "")
    path, cur, seen = [], latest, set()
    while cur is not None and cur.get("uuid") not in seen:
        seen.add(cur.get("uuid"))
        path.append(cur)
        cur = by_id.get(cur.get("parent_message_uuid"))
    return list(reversed(path))


def parse_conversations(data: list) -> list[ParsedChat]:
    if not isinstance(data, list):
        raise ExportError("conversations.json should contain a list of conversations")
    chats = []
    for c in data:
        if not isinstance(c, dict) or not c.get("uuid"):
            continue
        msgs = []
        for m in _main_branch([m for m in c.get("chat_messages") or [] if isinstance(m, dict)]):
            role = {"human": "user", "user": "user", "assistant": "assistant"}.get(m.get("sender"))
            text = _message_text(m)
            if role and text:
                msgs.append(ParsedMessage(str(m.get("uuid") or ""), role, text, _time(m.get("created_at"))))
        chats.append(
            ParsedChat(
                uuid=str(c["uuid"]),
                title=(c.get("name") or "").strip() or "Untitled chat",
                created_at=_time(c.get("created_at")),
                updated_at=str(c.get("updated_at") or ""),
                messages=msgs,
            )
        )
    return chats


def read_export(blob: bytes) -> list[ParsedChat]:
    """Accept the export ZIP, or a bare conversations.json."""
    if blob[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                names = [n for n in z.namelist() if n.rsplit("/", 1)[-1] == "conversations.json"]
                if not names:
                    raise ExportError("No conversations.json in this ZIP. Is it the claude.ai data export?")
                raw = z.read(names[0])
        except zipfile.BadZipFile as e:
            raise ExportError(f"Couldn't open the ZIP: {e}") from e
    else:
        raw = blob
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ExportError(f"conversations.json isn't valid JSON: {e}") from e
    return parse_conversations(data)


def _signature(chat: ParsedChat) -> str:
    """Changes when the conversation gained or lost messages, even if updated_at is missing."""
    return f"{chat.updated_at}|{len(chat.messages)}"[:40]


def store_chats(db: Session, chats: list[ParsedChat]) -> ImportResult:
    """Upsert chats by their claude.ai uuid. A changed chat is re-imported and goes back to pending analysis;
    its old review evidence is taken back out of the pattern statistics first."""
    result = ImportResult()
    existing = {n.external_id: n for n in db.scalars(select(Node).where(Node.source == "claude_ai"))}
    for chat in chats:
        if not any(m.role == "user" for m in chat.messages):
            result.empty += 1
            continue
        sig = _signature(chat)
        node = existing.get(chat.uuid)
        if node is not None and node.source_updated_at == sig:
            result.unchanged += 1
            continue
        if node is None:
            node = Node(kind="session", source="claude_ai", external_id=chat.uuid)
            db.add(node)
            result.new += 1
        else:
            undo_review(db, node.id)
            db.execute(delete(Message).where(Message.session_id == node.id))
            node.summary = ""
            result.updated += 1
        node.title = chat.title[:200]
        node.started_at = chat.created_at
        node.source_updated_at = sig
        node.status = "pending"
        db.flush()
        for m in chat.messages:
            db.add(
                Message(
                    session_id=node.id,
                    role=m.role,
                    content=m.text,
                    created_at=m.created_at or chat.created_at or datetime.now(timezone.utc),
                    external_id=m.uuid or None,
                )
            )
    db.commit()
    return result
