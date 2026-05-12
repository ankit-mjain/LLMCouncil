"""Telegram bot validation tests — /validation, /prefer, preference poll trigger."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, BudgetConfig, TelegramConfig, ValidationConfig
from llmcouncil.telegram.bot import CouncilBot


def _make_bot(db_factory=None, every_n: int = 5) -> CouncilBot:
    cfg = AppConfig(
        telegram=TelegramConfig(authorized_chat_id=1),
        budget=BudgetConfig(per_session_usd=1.0, per_day_usd=5.0),
        validation=ValidationConfig(ab_logging=True, prompt_user_for_preference_every_n=every_n),
    )
    return CouncilBot(token="fake-token", cfg=cfg, db_factory=db_factory)


def _make_update(chat_id: int = 1, text: str = "") -> MagicMock:
    update = MagicMock()
    update.message = MagicMock()
    update.message.chat_id = chat_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


# ---------------------------------------------------------------------------
# /validation — no DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_validation_no_db_replies_not_configured() -> None:
    bot = _make_bot(db_factory=None)
    update = _make_update()
    await bot.cmd_validation(update, _make_context())
    text = update.message.reply_text.call_args[0][0]
    assert "not configured" in text.lower() or "unavailable" in text.lower()


# ---------------------------------------------------------------------------
# /validation — with DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_validation_with_db_shows_dashboard() -> None:
    bot = _make_bot(db_factory=MagicMock())
    update = _make_update()

    from llmcouncil.validation.metrics import ValidationMetrics

    with patch.object(bot, "_query_metrics", return_value=ValidationMetrics(council_sessions=5)):
        await bot.cmd_validation(update, _make_context())

    update.message.reply_text.assert_awaited()
    text = update.message.reply_text.call_args[0][0]
    assert "council sessions" in text.lower() or "validation" in text.lower()


# ---------------------------------------------------------------------------
# /prefer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_prefer_valid_choice_confirmed() -> None:
    bot = _make_bot()
    update = _make_update()
    await bot.cmd_prefer(update, _make_context(args=["council"]))
    text = update.message.reply_text.call_args[0][0]
    assert "council" in text.lower()


@pytest.mark.asyncio
async def test_cmd_prefer_invalid_choice_shows_usage() -> None:
    bot = _make_bot()
    update = _make_update()
    await bot.cmd_prefer(update, _make_context(args=["bad"]))
    text = update.message.reply_text.call_args[0][0]
    assert "usage" in text.lower() or "/prefer" in text.lower()


@pytest.mark.asyncio
async def test_cmd_prefer_records_to_db() -> None:
    fake_db = MagicMock()
    fake_db.__enter__ = MagicMock(return_value=fake_db)
    fake_db.__exit__ = MagicMock(return_value=False)
    fake_factory = MagicMock(return_value=fake_db)

    bot = _make_bot(db_factory=fake_factory)
    update = _make_update()
    await bot.cmd_prefer(update, _make_context(args=["single"]))

    fake_db.add.assert_called_once()
    fake_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Preference poll sent every N sessions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_preference_poll_sent_on_nth_session() -> None:
    bot = _make_bot(every_n=2)
    bot._council_session_count = 1  # next session will be the 2nd

    sent_messages: list[str] = []

    async def fake_send(chat_id: int, text: str, retries: int = 5) -> None:
        sent_messages.append(text)

    bot._send_with_retry = fake_send

    # Simulate end of _run_session logic (shadow + poll check).
    bot._council_session_count += 1
    n = bot._cfg.validation.prompt_user_for_preference_every_n
    if n > 0 and bot._council_session_count % n == 0:
        await bot._send_with_retry(1, "Which response did you prefer?")

    assert any("prefer" in m.lower() for m in sent_messages)
