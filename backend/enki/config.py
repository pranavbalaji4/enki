from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ENKI_", extra="ignore")

    # Read without the ENKI_ prefix so a normal ANTHROPIC_API_KEY in .env works.
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    typesafe_api_key: str | None = Field(default=None, validation_alias="TYPESAFE_API_KEY")

    database_url: str = "sqlite:///./enki.db"
    # Deterministic offline stand-in for every model call (dev without a key, tests).
    fake_llm: bool = False

    ask_model: str = "claude-sonnet-5-5"     # the "ask about how I learn" chat (streamed, tool use)
    fast_model: str = "claude-haiku-4-5"     # chat classification + per-turn tagging/understanding
    deep_model: str = "claude-opus-5-5"      # topic tree, chat review, global profile, profile-edit interpretation

    # Who judges "did that explanation land?" from the learner's next message.
    # auto = Jev when TYPESAFE_API_KEY is set (falling back to Claude if a Jev call fails), else Claude.
    evaluator: Literal["auto", "jev", "claude"] = "auto"
    jev_model: str = "jev-latest"

    cors_origins: list[str] = ["http://localhost:3000"]

    # A pattern needs this many episodes of evidence before it becomes an insight card.
    insight_min_evidence: int = 3
    insight_min_confidence: float = 0.65
    # Model calls in flight at once while analyzing an import (fast model / deep model).
    analysis_concurrency: int = 4
    review_concurrency: int = 2
    max_upload_mb: int = 500

    # $ per million tokens (input, output), for the pre-analysis cost estimate only.
    prices: dict[str, tuple[float, float]] = {
        "claude-haiku-4-5": (1.0, 5.0),
        "claude-sonnet-5-5": (2.0, 10.0),
        "claude-opus-5-5": (4.0, 20.0),
    }


settings = Settings()
