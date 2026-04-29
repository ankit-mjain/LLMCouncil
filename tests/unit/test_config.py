"""Config schema round-trip tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from llmcouncil.config import AppConfig, CouncilConfig, SeatConfig, load_config, save_config


def test_default_config_is_valid() -> None:
    cfg = AppConfig()
    assert cfg.council.size == 3
    assert cfg.voting.mechanism == "simple_majority"
    assert cfg.vault.backend == "age"


def test_toml_round_trip(tmp_path: Path) -> None:
    cfg = AppConfig()
    config_file = tmp_path / "config.toml"
    save_config(cfg, config_file)
    loaded = load_config(config_file)
    assert loaded.council.size == cfg.council.size
    assert loaded.vault.backend == cfg.vault.backend
    assert loaded.voting.mechanism == cfg.voting.mechanism
    assert loaded.memory.retention_policy == cfg.memory.retention_policy


def test_council_with_valid_seats() -> None:
    seats = [
        SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
        SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
        SeatConfig(seat_id=3, role="judge", provider="google", model="gemini-2.5-flash"),
    ]
    cfg = CouncilConfig(seats=seats)
    assert len(cfg.seats) == 3


def test_council_rejects_missing_proposer() -> None:
    seats = [
        SeatConfig(seat_id=1, role="critic", provider="anthropic", model="claude-haiku-4-5"),
        SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
        SeatConfig(seat_id=3, role="judge", provider="google", model="gemini-2.5-flash"),
    ]
    with pytest.raises(ValidationError, match="proposer"):
        CouncilConfig(seats=seats)


def test_council_rejects_single_provider() -> None:
    seats = [
        SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
        SeatConfig(seat_id=2, role="critic", provider="anthropic", model="claude-sonnet-4-6"),
        SeatConfig(seat_id=3, role="judge", provider="anthropic", model="claude-opus-4-7"),
    ]
    with pytest.raises(ValidationError, match="distinct providers"):
        CouncilConfig(seats=seats, min_distinct_providers=2)


def test_council_allows_single_provider_when_min_is_1() -> None:
    seats = [
        SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
        SeatConfig(seat_id=2, role="critic", provider="anthropic", model="claude-sonnet-4-6"),
        SeatConfig(seat_id=3, role="judge", provider="anthropic", model="claude-opus-4-7"),
    ]
    cfg = CouncilConfig(seats=seats, min_distinct_providers=1)
    assert len(cfg.seats) == 3


def test_max_rounds_bounds() -> None:
    with pytest.raises(ValidationError):
        CouncilConfig(max_rounds=7)
    with pytest.raises(ValidationError):
        CouncilConfig(max_rounds=0)
