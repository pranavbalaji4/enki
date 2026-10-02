"""Structured-output schemas for every non-chat model call."""

from typing import Literal

from pydantic import BaseModel, Field

from .taxonomy import Abstraction, ConceptType, Ordering, Strategy, Verdict


class TagResult(BaseModel):
    concept: str = Field(description="The single concept the reply explains, 1-5 words, lowercase")
    concept_type: ConceptType
    strategies: list[Strategy] = Field(description="Every explanation strategy the reply uses, most prominent first")
    ordering: Ordering
    abstraction: Abstraction


class EvalResult(BaseModel):
    verdict: Verdict
    understanding: float = Field(description="0.0 = not understood at all, 1.0 = clearly understood")
    confidence: float = Field(description="0.0-1.0: how sure you are, given only the learner's next message")
    referenced_part: str = Field(description="Short quote of the part of the tutor reply the learner picked up on, or empty")
    reasoning: str = Field(description="One sentence")


class ReviewEpisode(BaseModel):
    concept: str
    concept_type: ConceptType
    outcome: Literal["clicked", "partial", "not_yet"]
    message_ids: list[int] = Field(description="Ids of every message (both roles) in this episode, in order")
    click_message_id: int | None = Field(description="Id of the learner message where understanding first shows, if any")
    winning_message_id: int | None = Field(description="Id of the tutor message that did the most to produce understanding")
    path_summary: str = Field(description="The trajectory in one line, e.g. 'formal def -> confused -> analogy -> applies it'")
    why_it_clicked: str = Field(description="Why the winning explanation worked for this learner (or why nothing did)")
    sticky_excerpt: str = Field(description="Verbatim excerpt (<= 1200 chars) of the winning tutor message that carried the insight; empty if none")
    prompting_moves: list[str] = Field(description="The learner's own prompt moves that helped, e.g. 'asked for an example'")


class PatternObservation(BaseModel):
    existing_pattern_id: int | None = Field(description="Id of an existing pattern this is evidence for/against, else null")
    claim: str = Field(description="Second-person claim, e.g. 'A concrete example before the formal definition helps you'")
    strategy: str = Field(description="Strategy or ordering key from the taxonomy, e.g. 'analogy' or 'example_first'")
    concept_type: ConceptType | None
    episode_index: int = Field(description="0-based index into the episodes list")
    supports: bool = Field(description="True if this episode is evidence FOR the claim, False if AGAINST")
    note: str


class SessionReview(BaseModel):
    episodes: list[ReviewEpisode]
    observations: list[PatternObservation]
    session_summary: str = Field(description="3-6 sentences: what was covered, where it clicked, what is still shaky")
    recap_title: str
    recap_body: str = Field(description="Markdown, second person, <= 150 words, ends with one prompting tip grounded in this session")


class FolderSummary(BaseModel):
    summary: str


class ProfileEditOp(BaseModel):
    op: Literal["confirm", "reject", "update_claim", "add", "note"]
    pattern_id: int | None
    claim: str
    strategy: str
    concept_type: ConceptType | None
    note: str


class ProfileEditResult(BaseModel):
    ops: list[ProfileEditOp]
    understood: str = Field(description="One or two sentences telling the learner how their edit was interpreted")
