"""Pydantic v2 config schema — mirrors the locked TOML structure from SPECS.md §8."""

from __future__ import annotations

import tomllib
import tomli_w
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class VaultConfig(BaseModel):
    backend: Literal["age", "keyring"] = "age"
    identity_file: Path = Path("~/.llmcouncil/age.key")


class CostProfileConfig(BaseModel):
    preset: Literal["free", "cheap", "balanced", "premium", "custom"] = "cheap"


class SeatConfig(BaseModel):
    seat_id: int
    role: Literal["proposer", "critic", "devils_advocate", "judge"]
    provider: str
    model: str


class CouncilConfig(BaseModel):
    size: Annotated[int, Field(ge=2)] = 3
    rotation: bool = False
    protocol: Literal["fixed", "freeform"] = "fixed"
    max_rounds: Annotated[int, Field(ge=1, le=6)] = 3
    include_minority: bool = True
    expose_transcript: bool = False
    min_distinct_providers: Annotated[int, Field(ge=1)] = 2
    devils_advocate_enabled: bool = False
    seats: list[SeatConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_seats(self) -> "CouncilConfig":
        if not self.seats:
            return self
        roles = [s.role for s in self.seats]
        if roles.count("proposer") != 1:
            raise ValueError("Council must have exactly one proposer.")
        if roles.count("judge") != 1:
            raise ValueError("Council must have exactly one judge.")
        if roles.count("critic") < 1:
            raise ValueError("Council must have at least one critic.")
        providers = {s.provider for s in self.seats}
        if len(providers) < self.min_distinct_providers:
            raise ValueError(
                f"Council requires at least {self.min_distinct_providers} distinct providers "
                f"(got {len(providers)}). Set min_distinct_providers=1 to allow single-provider "
                "mode (degraded — votes become correlated)."
            )
        return self


class VotingConfig(BaseModel):
    mechanism: Literal["simple_majority", "supermajority", "ranked_choice", "weighted", "judge_decides"] = "simple_majority"
    tie_break: Literal["user", "judge", "re_deliberate"] = "user"


class MemoryConfig(BaseModel):
    enabled: bool = True
    retention_policy: Literal["summarize_after_30d", "keep_forever", "delete_after_30d"] = "summarize_after_30d"
    max_summary_tokens: int = 2000


class DefaultLLMConfig(BaseModel):
    provider: str = ""
    model: str = ""
    fallback_chain: list[dict[str, str]] = Field(default_factory=list)


class BudgetConfig(BaseModel):
    per_session_usd: float = 0.50
    per_query_tokens: int = 60_000
    per_day_usd: float = 5.00
    soft_latency_s: int = 30
    hard_latency_s: int = 90


class TelegramConfig(BaseModel):
    authorized_chat_id: int | None = None
    message_format: Literal["plain", "markdown", "rich"] = "plain"


class WebSearchConfig(BaseModel):
    provider: Literal["tavily", "serper", "duckduckgo"] = "tavily"
    enabled: bool = True
    max_calls_per_session: int = 5


class StreamingConfig(BaseModel):
    target: Literal["off", "tui", "telegram", "both"] = "off"


class TriggersConfig(BaseModel):
    explicit: list[str] = Field(default_factory=lambda: ["/Council"])
    auto_escalate: bool = True
    escalation_confidence_threshold: float = 0.6


class ValidationConfig(BaseModel):
    ab_logging: bool = True
    prompt_user_for_preference_every_n: int = 5


# ---------------------------------------------------------------------------
# Root config
# ---------------------------------------------------------------------------

class AppConfig(BaseModel):
    config_dir: Path = Path("~/.llmcouncil")
    db_path: Path = Path("~/.llmcouncil/data.sqlite")
    logs_dir: Path = Path("~/.llmcouncil/logs")

    vault: VaultConfig = Field(default_factory=VaultConfig)
    cost_profile: CostProfileConfig = Field(default_factory=CostProfileConfig)
    # registered_providers: provider_name -> list of model names the user registered
    registered_providers: dict[str, list[str]] = Field(default_factory=dict)
    default_llm: DefaultLLMConfig = Field(default_factory=DefaultLLMConfig)
    council: CouncilConfig = Field(default_factory=CouncilConfig)
    voting: VotingConfig = Field(default_factory=VotingConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    triggers: TriggersConfig = Field(default_factory=TriggersConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)

    @field_validator("config_dir", "db_path", "logs_dir", mode="before")
    @classmethod
    def expand_path(cls, v: object) -> Path:
        return Path(str(v)).expanduser()


# ---------------------------------------------------------------------------
# TOML I/O
# ---------------------------------------------------------------------------

def _strip_none(obj: object) -> object:
    """Recursively remove None values — TOML has no null type."""
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj]
    return obj


def load_config(path: Path) -> AppConfig:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return AppConfig.model_validate(data)


def save_config(cfg: AppConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _strip_none(cfg.model_dump(mode="json"))
    with path.open("wb") as f:
        tomli_w.dump(data, f)  # type: ignore[arg-type]
