"""Tests for shadow A/B runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, ValidationConfig
from llmcouncil.validation.shadow import run_shadow


def _mock_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.tokens_in = 10
    resp.tokens_out = 20
    resp.usd = 0.001
    return resp


@pytest.mark.asyncio
async def test_shadow_disabled_returns_empty() -> None:
    cfg = AppConfig(validation=ValidationConfig(ab_logging=False))
    result = await run_shadow("What is X?", cfg)
    assert result == ""


@pytest.mark.asyncio
async def test_shadow_returns_llm_text() -> None:
    cfg = AppConfig(validation=ValidationConfig(ab_logging=True))
    with patch("llmcouncil.validation.shadow.call_seat", new=AsyncMock(return_value=_mock_response("shadow answer"))):
        result = await run_shadow("What is X?", cfg)
    assert result == "shadow answer"


@pytest.mark.asyncio
async def test_shadow_call_failure_returns_empty() -> None:
    cfg = AppConfig(validation=ValidationConfig(ab_logging=True))
    with patch("llmcouncil.validation.shadow.call_seat", side_effect=RuntimeError("API down")):
        result = await run_shadow("What is X?", cfg)
    assert result == ""


@pytest.mark.asyncio
async def test_shadow_persists_to_db_when_factory_provided() -> None:
    cfg = AppConfig(validation=ValidationConfig(ab_logging=True))

    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)
    fake_factory = MagicMock(return_value=fake_db)

    with patch("llmcouncil.validation.shadow.call_seat", new=AsyncMock(return_value=_mock_response("ok"))):
        await run_shadow("query", cfg, db_factory=fake_factory)

    fake_db.add.assert_called_once()
    fake_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_shadow_skips_db_when_factory_is_none() -> None:
    cfg = AppConfig(validation=ValidationConfig(ab_logging=True))
    with patch("llmcouncil.validation.shadow.call_seat", new=AsyncMock(return_value=_mock_response("ok"))):
        result = await run_shadow("query", cfg, db_factory=None)
    assert result == "ok"
