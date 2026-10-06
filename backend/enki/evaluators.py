"""Per-turn understanding judges: "did that tutor reply land?", read from the learner's next message.

Jev (TypeSafe's classifier) is the primary judge: one request asks every question about the same state in parallel
and returns calibrated probabilities, which is what the pattern statistics need. Claude (fast model) is the
fallback and the default when no TYPESAFE_API_KEY is set."""

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from .config import settings
from .llm import get_llm
from .llm_schemas import EvalResult
from .taxonomy import LEVEL_DESCRIPTIONS, LEVELS, VERDICT_DESCRIPTIONS, VERDICT_SCORE

log = logging.getLogger("enki.evaluators")

# Jev's context limit isn't documented yet; keep the (long) tutor reply to its head and tail.
MAX_REPLY_CHARS = 8000


@dataclass
class Judgement:
    verdict: str
    understanding: float  # 0-1 expected understanding
    confidence: float  # 0-1
    evaluator: str  # jev | claude | fake
    level_probs: list[float] | None = None  # [not_understood, iffy, understood]; Jev's are calibrated, Claude's are estimates
    signals: dict[str, float] = field(default_factory=dict)
    referenced_part: str | None = None
    reasoning: str = ""


class Evaluator(Protocol):
    def judge(self, question: str, reply: str, next_msg: str) -> Judgement: ...


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _normalize(probs: list[float]) -> list[float] | None:
    """The model's [not understood, iffy, understood]; None if it didn't return three usable numbers."""
    if len(probs) != len(LEVELS):
        return None
    clean = [max(0.0, float(p)) for p in probs]
    total = sum(clean)
    return [round(p / total, 4) for p in clean] if total > 0 else None


def judgement_from_eval(r: EvalResult) -> Judgement:
    """Map a Claude (or FakeLLM) structured evaluation onto the shared Judgement."""
    return Judgement(
        verdict=r.verdict,
        # An LLM's self-reported number isn't calibrated; blend it with the verdict prior.
        understanding=round(0.5 * _clamp(r.understanding) + 0.5 * VERDICT_SCORE[r.verdict], 3),
        confidence=_clamp(r.confidence),
        evaluator="fake" if settings.fake_llm else "claude",
        level_probs=_normalize(r.level_probs),
        referenced_part=r.referenced_part or None,
        reasoning=r.reasoning,
    )


class ClaudeEvaluator:
    """Structured-output judgement from the fast model (or the offline FakeLLM)."""

    def judge(self, question: str, reply: str, next_msg: str) -> Judgement:
        return judgement_from_eval(get_llm().evaluate_turn(question, reply, next_msg))


class JevEvaluator:
    def __init__(self, classifier: Any | None = None) -> None:
        if classifier is None:
            from langchain_typesafe import TypeSafeClassifier

            classifier = TypeSafeClassifier(model=settings.jev_model, api_key=settings.typesafe_api_key)
        self.classifier = classifier

    @staticmethod
    def request(question: str, reply: str, next_msg: str) -> dict:
        from langchain_typesafe import Choice, Noul, Score

        if len(reply) > MAX_REPLY_CHARS:
            half = MAX_REPLY_CHARS // 2
            reply = reply[:half] + "\n[…]\n" + reply[-half:]
        return {
            # The tutor's output and the learner's next prompt are the evidence; the original question is context.
            "state": {
                "learner_question": question,
                "tutor_explanation": reply,
                "learner_next_message": next_msg,
            },
            "questions": {
                "understanding": Score(
                    instructions=(
                        "Judging only from learner_next_message, how well did the learner understand "
                        "tutor_explanation?"
                    ),
                    criteria=list(LEVEL_DESCRIPTIONS),
                ),
                "verdict": Choice(
                    instructions="Which best describes what learner_next_message shows about tutor_explanation?",
                    criteria=dict(VERDICT_DESCRIPTIONS),
                ),
                "reused_explanation": Noul(
                    instructions=(
                        "Does learner_next_message reuse a specific analogy, example, or wording "
                        "from tutor_explanation?"
                    )
                ),
                "frustrated": Noul(instructions="Does learner_next_message show frustration or discouragement?"),
            },
        }

    def judge(self, question: str, reply: str, next_msg: str) -> Judgement:
        resp = self.classifier.invoke(self.request(question, reply, next_msg))
        score = resp.scores["understanding"]
        verdict = resp.choices["verdict"]
        nouls = resp.nouls

        n_levels = len(LEVELS)
        probs = [float(score.probabilities.get(i, 0.0)) for i in range(n_levels)]
        understanding = _clamp(score.score / (n_levels - 1))
        pct = " · ".join(f"{LEVELS[i].replace('_', ' ')} {p:.0%}" for i, p in reversed(list(enumerate(probs))))
        return Judgement(
            verdict=verdict.choice if verdict.choice in VERDICT_SCORE else "ambiguous_ack",
            understanding=round(understanding, 3),
            confidence=_clamp(score.confidence),
            evaluator="jev",
            level_probs=[round(p, 4) for p in probs],
            signals={k: round(v.noul, 4) for k, v in nouls.items()},
            reasoning=f"Jev: {pct}",
        )


class FallbackEvaluator:
    """Try Jev; if the call fails, judge with Claude so the turn still gets evidence."""

    def __init__(self, primary: Evaluator, fallback: Evaluator) -> None:
        self.primary, self.fallback = primary, fallback

    def judge(self, question: str, reply: str, next_msg: str) -> Judgement:
        from langchain_typesafe.client import TypeSafeError

        try:
            return self.primary.judge(question, reply, next_msg)
        except TypeSafeError as e:
            log.warning("Jev evaluation failed, falling back to Claude: %s", e)
            return self.fallback.judge(question, reply, next_msg)


@lru_cache
def get_evaluator() -> Evaluator:
    mode = settings.evaluator
    if settings.fake_llm or mode == "claude" or (mode == "auto" and not settings.typesafe_api_key):
        return ClaudeEvaluator()
    if mode == "jev":
        return JevEvaluator()
    return FallbackEvaluator(JevEvaluator(), ClaudeEvaluator())
