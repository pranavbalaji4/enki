"""All model calls go through here. `get_llm()` returns the real client or a deterministic fake (ENKI_FAKE_LLM=1)."""

import re
from functools import lru_cache
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from . import prompts
from .config import settings
from .llm_schemas import (
    ChatClassification,
    EvalResult,
    FolderSummary,
    GlobalProfile,
    PatternObservation,
    ProfileEditResult,
    ReviewEpisode,
    SessionReview,
    TagResult,
    TopicDomain,
    TopicLeaf,
    TopicTree,
    TurnAnalysis,
)
from .taxonomy import VERDICT_SCORE

# Server-side refusal fallback: Anthropic re-runs a declined request on its recommended model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    def tag_turn(self, user_msg: str, reply: str) -> TagResult: ...
    def evaluate_turn(self, user_msg: str, reply: str, next_msg: str) -> EvalResult: ...
    def analyze_turn(self, user_msg: str, reply: str, next_msg: str) -> TurnAnalysis: ...
    def classify_chat(self, title: str, opening: str) -> ChatClassification: ...
    def build_topic_tree(self, existing: str, labels: list[str]) -> TopicTree: ...
    def write_global_profile(self, evidence: str, topic_ids: list[int]) -> GlobalProfile: ...
    def review_session(self, transcript: str, patterns: str, message_ids: list[int]) -> SessionReview: ...
    def update_folder_summary(self, folder: str, old: str, session_summary: str) -> FolderSummary: ...
    def interpret_profile_edit(self, old_md: str, new_md: str, patterns: str) -> ProfileEditResult: ...


class ClaudeLLM:
    def __init__(self) -> None:
        # With no explicit key the SDK resolves ANTHROPIC_API_KEY / auth token / `ant auth login` profile.
        key = settings.anthropic_api_key
        self.client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

    def _fast(self, system: str, user: str, schema: type[T]) -> T:
        resp = self.client.messages.parse(
            model=settings.fast_model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
        return self._parsed(resp, schema)

    def _deep(self, system: str, user: str, schema: type[T]) -> T:
        resp = self.client.beta.messages.parse(
            model=settings.deep_model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": "high"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        return self._parsed(resp, schema)

    @staticmethod
    def _parsed(resp, schema: type[T]) -> T:
        if resp.stop_reason == "refusal":
            raise LLMError(f"{schema.__name__}: model declined")
        if resp.stop_reason == "max_tokens" or resp.parsed_output is None:
            raise LLMError(f"{schema.__name__}: no parsed output (stop_reason={resp.stop_reason})")
        return resp.parsed_output

    def tag_turn(self, user_msg: str, reply: str) -> TagResult:
        return self._fast(prompts.TAGGER_SYSTEM, prompts.tagger_user(user_msg, reply), TagResult)

    def evaluate_turn(self, user_msg: str, reply: str, next_msg: str) -> EvalResult:
        return self._fast(prompts.EVALUATOR_SYSTEM, prompts.evaluator_user(user_msg, reply, next_msg), EvalResult)

    def analyze_turn(self, user_msg: str, reply: str, next_msg: str) -> TurnAnalysis:
        return self._fast(prompts.ANALYZE_SYSTEM, prompts.evaluator_user(user_msg, reply, next_msg), TurnAnalysis)

    def classify_chat(self, title: str, opening: str) -> ChatClassification:
        return self._fast(prompts.CLASSIFY_SYSTEM, prompts.classify_user(title, opening), ChatClassification)

    def build_topic_tree(self, existing: str, labels: list[str]) -> TopicTree:
        numbered = "\n".join(f"[{i}] {label}" for i, label in enumerate(labels))
        return self._deep(prompts.TOPIC_TREE_SYSTEM, prompts.topic_tree_user(existing, numbered), TopicTree)

    def write_global_profile(self, evidence: str, topic_ids: list[int]) -> GlobalProfile:
        return self._deep(prompts.GLOBAL_PROFILE_SYSTEM, prompts.global_profile_user(evidence), GlobalProfile)

    def review_session(self, transcript: str, patterns: str, message_ids: list[int]) -> SessionReview:
        return self._deep(prompts.REVIEW_SYSTEM, prompts.review_user(transcript, patterns), SessionReview)

    def update_folder_summary(self, folder: str, old: str, session_summary: str) -> FolderSummary:
        return self._fast(prompts.FOLDER_SUMMARY_SYSTEM, prompts.folder_summary_user(folder, old, session_summary), FolderSummary)

    def interpret_profile_edit(self, old_md: str, new_md: str, patterns: str) -> ProfileEditResult:
        return self._deep(prompts.PROFILE_EDIT_SYSTEM, prompts.profile_edit_user(old_md, new_md, patterns), ProfileEditResult)


class FakeLLM:
    """Keyword heuristics standing in for the models so the whole loop runs offline."""

    def tag_turn(self, user_msg: str, reply: str) -> TagResult:
        low = reply.lower()
        strategies = []
        rules = [
            ("analogy", ("like a", "think of it", "imagine")),
            ("concrete_example", ("for example", "e.g.", "for instance")),
            ("code", ("```",)),
            ("formal_definition", ("formally", "is defined", "definition")),
            ("step_by_step", ("step by step", "first,", "step 1")),
            ("visual_diagram", ("diagram", "->", "┌")),
        ]
        for name, keys in rules:
            if any(k in low for k in keys):
                strategies.append(name)
        if reply.rstrip().endswith("?"):
            strategies.append("socratic_question")
        ex, df = low.find("for example"), low.find("formally")
        ordering = "example_first" if 0 <= ex < df or (ex >= 0 > df) else "definition_first" if df >= 0 else "single_mode"
        concept = " ".join(re.findall(r"[a-z]+", user_msg.lower())[-3:]) or "general"
        return TagResult(
            concept=concept,
            concept_type="structural",
            strategies=strategies or ["first_principles"],
            ordering=ordering,
            abstraction="mixed",
        )

    def evaluate_turn(self, user_msg: str, reply: str, next_msg: str) -> EvalResult:
        low = next_msg.lower().strip()
        if any(k in low for k in ("don't get", "dont get", "confused", "huh", "lost", "makes no sense")):
            verdict = "confusion"
        elif any(k in low for k in ("again", "what do you mean", "explain that")):
            verdict = "re_ask"
        elif low.startswith(("so ", "oh", "i see", "got it, so")):
            verdict = "paraphrase_correct"
        elif len(low) < 15 and any(k in low for k in ("ok", "thanks", "cool")):
            verdict = "ambiguous_ack"
        else:
            verdict = "builds_on"
        u = VERDICT_SCORE[verdict]
        level = 2 if u >= 0.75 else 1 if u >= 0.45 else 0
        probs = [0.15, 0.15, 0.15]
        probs[level] = 0.7
        return EvalResult(
            verdict=verdict,
            level_probs=probs,
            understanding=u,
            confidence=0.6,
            referenced_part="",
            reasoning=f"offline heuristic: {verdict}",
        )

    def analyze_turn(self, user_msg: str, reply: str, next_msg: str) -> TurnAnalysis:
        return TurnAnalysis(tag=self.tag_turn(user_msg, reply), evaluation=self.evaluate_turn(user_msg, reply, next_msg))

    # Keyword -> (domain, topic). Anything else is a task, not learning.
    _TOPICS = [
        (("queue", "stack", "heap", "tree", "linked list", "hash"), ("Computer Science", "Data Structures")),
        (("recursion", "big o", "algorithm", "sort"), ("Computer Science", "Algorithms")),
        (("bond", "stock", "interest", "inflation", "option"), ("Finance", "Markets")),
        (("kant", "ethics", "free will", "plato", "philosoph"), ("Philosophy", "Ethics")),
    ]

    def classify_chat(self, title: str, opening: str) -> ChatClassification:
        low = f"{title}\n{opening}".lower()
        for keys, (domain, topic) in self._TOPICS:
            if any(k in low for k in keys):
                return ChatClassification(is_learning=True, domain=domain, topic=topic)
        return ChatClassification(is_learning=False, domain="Other", topic="Tasks")

    def build_topic_tree(self, existing: str, labels: list[str]) -> TopicTree:
        domains: dict[str, dict[str, list[int]]] = {}
        for i, label in enumerate(labels):
            domain, _, topic = label.partition(" / ")
            domains.setdefault(domain, {}).setdefault(topic.split(" (")[0], []).append(i)
        return TopicTree(
            domains=[
                TopicDomain(name=d, topics=[TopicLeaf(name=t, label_ids=ids) for t, ids in topics.items()])
                for d, topics in domains.items()
            ]
        )

    def write_global_profile(self, evidence: str, topic_ids: list[int]) -> GlobalProfile:
        from .llm_schemas import CrossTopicLine

        return GlobalProfile(
            headline="Offline profile: everyday analogies tend to land for you.",
            summary_md=(
                "**Offline mode.** This summary is a placeholder written without a model. With an API key, this is "
                "where Claude describes how you learn across your topics, and how strong the evidence is."
            ),
            topic_lines=[CrossTopicLine(topic_id=t, line="Analogies helped here.") for t in topic_ids],
        )

    def review_session(self, transcript: str, patterns: str, message_ids: list[int]) -> SessionReview:
        # One episode covering the whole session; the first tutor turn followed by understanding "wins".
        turns = []
        for line in transcript.splitlines():
            m = re.match(r"\[#(\d+) (learner|tutor)", line)
            if m:
                v = re.search(r"verdict=(\w+)", line.split("]")[0])
                turns.append((int(m.group(1)), m.group(2), v.group(1) if v else None))
        winning, click, failed_turns = None, None, 0
        for i, (mid, role, verdict) in enumerate(turns):
            if role != "tutor":
                continue
            nxt = next((t for t in turns[i + 1:] if t[1] == "learner"), None)
            if verdict in ("builds_on", "paraphrase_correct", "applies_correctly") and winning is None:
                winning, click = mid, nxt[0] if nxt else None
            elif verdict in ("confusion", "re_ask", "misconception"):
                failed_turns += 1
        clicked = winning is not None
        obs = [
            PatternObservation(
                existing_pattern_id=_find_pattern_id(patterns, "analogy"),
                claim="Everyday analogies help you understand new structures",
                strategy="analogy",
                concept_type="structural",
                episode_index=0,
                supports=clicked,
                note="offline heuristic",
            )
        ]
        return SessionReview(
            episodes=[
                ReviewEpisode(
                    concept="session topic",
                    concept_type="structural",
                    outcome="clicked" if clicked else "not_yet",
                    message_ids=message_ids,
                    click_message_id=click,
                    winning_message_id=winning,
                    path_summary=f"{failed_turns} attempt(s) missed -> analogy -> {'understood' if clicked else 'still open'}",
                    why_it_clicked="The coffee-shop analogy gave a concrete picture before the formal term.",
                    sticky_excerpt="Think of it like a line at a coffee shop: the first person in is the first served." if clicked else "",
                    prompting_moves=["asked a direct follow-up"],
                )
            ],
            observations=obs,
            session_summary="Offline review: one concept discussed.",
            recap_title="Session recap",
            recap_body="You worked through one idea. **Tip:** asking for an example early got you there faster.",
        )

    def update_folder_summary(self, folder: str, old: str, session_summary: str) -> FolderSummary:
        return FolderSummary(summary=(old + "\n" + session_summary).strip()[-1500:])

    def interpret_profile_edit(self, old_md: str, new_md: str, patterns: str) -> ProfileEditResult:
        return ProfileEditResult(ops=[], understood="Offline mode: edit saved as a note only.")


def _find_pattern_id(patterns: str, strategy: str) -> int | None:
    m = re.search(rf"^- \[id=(\d+)\] strategy={strategy}\b", patterns, re.M)
    return int(m.group(1)) if m else None


@lru_cache
def get_llm() -> LLM:
    return FakeLLM() if settings.fake_llm else ClaudeLLM()
