"""Extended config schema tests for fields added in M2."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from llmcouncil.config import (
    AppConfig,
    BudgetConfig,
    CouncilConfig,
    CostProfileConfig,
    MemoryConfig,
    SeatConfig,
    TriggersConfig,
    ValidationConfig,
    WebSearchConfig,
    load_config,
    save_config,
)


def _cheap_seats() -> list[SeatConfig]:
    return [
        SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
        SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
        SeatConfig(seat_id=3, role="judge", provider="google", model="gemini-2.5-flash"),
    ]


def test_full_config_round_trip(tmp_path: Path) -> None:
    cfg = AppConfig(
        config_dir=tmp_path,
        db_path=tmp_path / "data.sqlite",
        logs_dir=tmp_path / "logs",
        cost_profile=CostProfileConfig(preset="cheap"),
        registered_providers={
            "anthropic": ["claude-haiku-4-5"],
            "moonshot": ["kimi-k2"],
            "google": ["gemini-2.5-flash"],
        },
        council=CouncilConfig(seats=_cheap_seats()),
        validation=ValidationConfig(ab_logging=True, prompt_user_for_preference_every_n=5),
    )
    config_file = tmp_path / "config.toml"
    save_config(cfg, config_file)
    loaded = load_config(config_file)

    assert loaded.cost_profile.preset == "cheap"
    assert "anthropic" in loaded.registered_providers
    assert loaded.registered_providers["anthropic"] == ["claude-haiku-4-5"]
    assert len(loaded.council.seats) == 3
    assert loaded.validation.ab_logging is True


def test_budget_defaults() -> None:
    b = BudgetConfig()
    assert b.per_session_usd == 0.50
    assert b.per_day_usd == 5.00
    assert b.soft_latency_s == 30
    assert b.hard_latency_s == 90


def test_triggers_defaults() -> None:
    t = TriggersConfig()
    assert "/Council" in t.explicit
    assert t.auto_escalate is True
    assert 0.0 <= t.escalation_confidence_threshold <= 1.0


def test_memory_config() -> None:
    m = MemoryConfig(retention_policy="keep_forever")
    assert m.retention_policy == "keep_forever"
    with pytest.raises(ValidationError):
        MemoryConfig(retention_policy="invalid_policy")  # type: ignore[arg-type]


def test_web_search_config() -> None:
    w = WebSearchConfig(provider="serper", max_calls_per_session=3)
    assert w.max_calls_per_session == 3


def test_cost_profile_config() -> None:
    for preset in ["free", "cheap", "balanced", "premium", "custom"]:
        c = CostProfileConfig(preset=preset)
        assert c.preset == preset
    with pytest.raises(ValidationError):
        CostProfileConfig(preset="unknown")  # type: ignore[arg-type]


def test_expose_transcript_field() -> None:
    seats = _cheap_seats()
    cfg = CouncilConfig(seats=seats, expose_transcript=True)
    assert cfg.expose_transcript is True


def test_registered_providers_roundtrip(tmp_path: Path) -> None:
    cfg = AppConfig(
        config_dir=tmp_path,
        registered_providers={"anthropic": ["claude-haiku-4-5", "claude-sonnet-4-6"]},
    )
    f = tmp_path / "config.toml"
    save_config(cfg, f)
    loaded = load_config(f)
    assert loaded.registered_providers["anthropic"] == ["claude-haiku-4-5", "claude-sonnet-4-6"]
