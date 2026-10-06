"""Shared vocabularies. Kept small on purpose: transfer quality depends on these being coarse enough to recur."""

from typing import Literal

Strategy = Literal[
    "analogy",
    "concrete_example",
    "worked_example",
    "visual_diagram",
    "formal_definition",
    "code",
    "socratic_question",
    "first_principles",
    "contrast_counterexample",
    "story",
    "step_by_step",
    "summary_recap",
]

ConceptType = Literal[
    "procedural",       # how to do X
    "structural",       # what X is / how it is organized
    "causal",           # why X happens
    "formal_proof",     # proofs, derivations, formal reasoning
    "factual",          # facts, names, definitions to remember
    "spatial_visual",   # geometry, layouts, things best seen
]

Ordering = Literal["example_first", "definition_first", "question_first", "single_mode"]

Abstraction = Literal["concrete", "mixed", "abstract"]

Verdict = Literal[
    "applies_correctly",   # uses the idea correctly on something new
    "builds_on",           # asks a follow-up that presupposes understanding
    "paraphrase_correct",  # restates it correctly in own words
    "narrowing",           # "ok, but why X?" — partial understanding, targeted gap
    "ambiguous_ack",       # "ok" / "thanks" — can't tell
    "topic_shift",         # moves on without signal
    "re_ask",              # asks the same thing again
    "confusion",           # explicit confusion
    "misconception",       # restates it wrongly
]

VERDICT_DESCRIPTIONS: dict[str, str] = {
    "applies_correctly": "Uses the idea correctly on a new case or example.",
    "builds_on": "Asks a follow-up that only makes sense if they understood the explanation.",
    "paraphrase_correct": "Restates the idea correctly in their own words.",
    "narrowing": "Shows partial understanding and asks about one specific remaining gap.",
    "ambiguous_ack": "Only acknowledges ('ok', 'thanks', 'cool') with no evidence either way.",
    "topic_shift": "Moves to an unrelated topic without signalling understanding or confusion.",
    "re_ask": "Asks essentially the same question again.",
    "confusion": "Says or clearly shows they are lost.",
    "misconception": "Restates the idea incorrectly.",
}

# Stored (never produced by a judge) for a reply nothing followed: the chat ended, so there is no evidence either way.
NO_SIGNAL = "no_signal"

# The three-level understanding scale Jev scores on, lowest first.
LEVELS = ["not_understood", "iffy", "understood"]
LEVEL_DESCRIPTIONS = [
    "Not understood: the learner is confused, asks the same thing again, or restates the idea incorrectly.",
    "Iffy: partial or unclear — a follow-up about one specific gap, a bare acknowledgement like 'ok' or 'thanks', "
    "or moving on without showing whether they understood.",
    "Understood: the learner applies the idea correctly, restates it correctly in their own words, "
    "or asks a follow-up that only makes sense if they understood.",
]

# Prior understanding score per verdict; the evaluator's own score is blended with this.
VERDICT_SCORE: dict[str, float] = {
    "applies_correctly": 0.95,
    "builds_on": 0.8,
    "paraphrase_correct": 0.85,
    "narrowing": 0.55,
    "ambiguous_ack": 0.5,
    "topic_shift": 0.5,
    "re_ask": 0.2,
    "confusion": 0.1,
    "misconception": 0.1,
}
