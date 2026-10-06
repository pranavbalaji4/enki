"""The "ask about how I learn" chat: Claude with read-only tools over the analyzed data, streamed as events.

Events: {"type": "tool", "name", "label"} when a lookup starts, {"type": "delta", "text"} for answer text."""

import json
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from . import prompts
from .config import settings
from .db import SessionLocal
from .llm import FALLBACK_BETA, LLMError, get_llm
from .models import Node
from . import views

MAX_STEPS = 8  # model calls per answer


class _NoArgs(BaseModel):
    pass


class _TopicArgs(BaseModel):
    topic_id: int


class _ChatArgs(BaseModel):
    chat_id: int


class _SearchArgs(BaseModel):
    query: str | None = Field(default=None, description="Words to look for in the question, the reply, the concept or the chat title")
    level: Literal["understood", "iffy", "not_understood"] | None = None
    topic_id: int | None = None
    limit: int = Field(default=10, ge=1, le=25)


def _profile(db, _: _NoArgs) -> dict:
    o = views.overview(db)
    return {k: o[k] for k in ("snapshot", "stats", "mix", "global_patterns", "top_patterns", "stickies")}


def _topics(db, _: _NoArgs) -> list[dict]:
    return [{k: t[k] for k in ("id", "parent_id", "path", "chat_count", "judged_turns", "avg_understanding", "mix", "line")} for t in views.topic_tree(db)]


def _topic(db, a: _TopicArgs) -> dict:
    node = db.get(Node, a.topic_id)
    if node is None or node.kind != "folder":
        raise LookupError(f"No topic with id {a.topic_id}. Call list_topics for valid ids.")
    d = views.topic_detail(db, node)
    d["chats"] = d["chats"][:40]
    return d


def _chat(db, a: _ChatArgs) -> dict:
    node = db.get(Node, a.chat_id)
    if node is None or node.kind != "session":
        raise LookupError(f"No chat with id {a.chat_id}.")
    return views.chat_for_ask(db, node)


def _search(db, a: _SearchArgs) -> list[dict]:
    return views.search_turns(db, a.query, a.level, a.topic_id, a.limit)


# name -> (description, argument model, implementation, label shown while it runs)
TOOLS = {
    "get_learning_profile": (
        "The written global profile, overall stats, how often replies landed, cross-topic and strongest patterns, and recent explanations that clicked. Start here.",
        _NoArgs, _profile, "Reading your learning profile",
    ),
    "list_topics": (
        "Every topic (Domain -> Topic) with chat counts, judged replies, average understanding and the understood/iffy/not-understood mix.",
        _NoArgs, _topics, "Looking through your topics",
    ),
    "get_topic": (
        "One topic in depth: its summary, patterns, explanations that clicked, sub-topics, and its chats with per-chat understanding.",
        _TopicArgs, _topic, "Opening a topic",
    ),
    "search_turns": (
        "Find individual Claude replies with their judgement (level, probabilities, verdict), the question before and the learner's next message. Filter by text, level and topic.",
        _SearchArgs, _search, "Searching your conversations",
    ),
    "get_chat": (
        "One conversation: summary, episodes (what clicked and why), and every turn with its strategies and judgement. Long messages are shortened.",
        _ChatArgs, _chat, "Reading a conversation",
    ),
}


def tool_definitions() -> list[dict]:
    return [
        {
            "name": name,
            "description": desc,
            "input_schema": args.model_json_schema(),
            "eager_input_streaming": True,
        }
        for name, (desc, args, _, _) in TOOLS.items()
    ]


def run_tool(name: str, raw_input) -> tuple[str, bool]:
    """Returns (JSON result, is_error). Inputs are validated here: streamed tool input is not validated by the API."""
    if name not in TOOLS:
        return f"Unknown tool {name}", True
    _, args_model, impl, _ = TOOLS[name]
    try:
        args = args_model.model_validate(raw_input or {})
    except ValidationError as e:
        return f"Invalid input: {e}", True
    with SessionLocal() as db:
        try:
            return json.dumps(impl(db, args), default=str)[:60000], False
        except LookupError as e:
            return str(e), True


def answer(history: list[dict]) -> Iterator[dict]:
    """`history` is the conversation so far as plain {role, content} text messages, ending with the user's question."""
    if settings.fake_llm:
        yield from _fake_answer(history)
        return
    client = get_llm().client
    messages: list = list(history)
    wrote_text = False
    for _ in range(MAX_STEPS):
        started = False
        with client.beta.messages.stream(
            model=settings.ask_model,
            max_tokens=16000,
            system=[{"type": "text", "text": prompts.ASK_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            tools=tool_definitions(),
            messages=messages,
            output_config={"effort": "medium"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            for text in stream.text_stream:
                if not started and wrote_text:
                    yield {"type": "delta", "text": "\n\n"}
                started = True
                yield {"type": "delta", "text": text}
            final = stream.get_final_message()
        wrote_text = wrote_text or started
        if final.stop_reason == "refusal":
            raise LLMError("Claude declined to answer this question.")
        if final.stop_reason == "max_tokens":
            yield {"type": "delta", "text": "\n\n_(answer cut off)_"}
            return
        if final.stop_reason != "tool_use":
            return
        messages.append({"role": "assistant", "content": final.content})
        results = []
        for block in final.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool", "name": block.name, "label": TOOLS.get(block.name, ("", None, None, block.name))[3]}
            content, is_error = run_tool(block.name, block.input)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    yield {"type": "delta", "text": "\n\n_(stopped after too many lookups — try a narrower question)_"}


def _fake_answer(history: list[dict]) -> Iterator[dict]:
    yield {"type": "tool", "name": "get_learning_profile", "label": TOOLS["get_learning_profile"][3]}
    data = json.loads(run_tool("get_learning_profile", {})[0])
    mix = data["mix"]
    with SessionLocal() as db:
        first = db.scalars(select(Node).where(Node.kind == "session", Node.status == "analyzed").limit(1)).first()
    cite = f" For example, see [{first.title}](/chats/{first.id})." if first else ""
    text = (
        f"(Offline answer.) Across your analyzed chats, {mix['understood']} replies landed, {mix['iffy']} were iffy and "
        f"{mix['not_understood']} didn't land.{cite}"
    )
    for word in text.split(" "):
        yield {"type": "delta", "text": word + " "}
