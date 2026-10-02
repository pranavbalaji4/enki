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

    tutor_model: str = "claude-sonnet-5-5"   # streams replies to the learner
    fast_model: str = "claude-haiku-4-5"     # per-turn strategy tagging + understanding evaluation
    deep_model: str = "claude-opus-5-5"      # session review, profile-edit interpretation

    # Who judges "did that explanation land?" from the learner's next message.
    # auto = Jev when TYPESAFE_API_KEY is set (falling back to Claude if a Jev call fails), else Claude.
    evaluator: Literal["auto", "jev", "claude"] = "auto"
    jev_model: str = "jev-latest"

    cors_origins: list[str] = ["http://localhost:3000"]

    # A pattern needs this many episodes of evidence before it becomes an insight card.
    insight_min_evidence: int = 3
    insight_min_confidence: float = 0.65
    # Max patterns / sticky explanations injected into the tutor prompt.
    profile_top_k: int = 8
    sticky_top_k: int = 5


settings = Settings()
