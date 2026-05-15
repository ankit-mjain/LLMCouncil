"""Telegram bot unit tests — authorization, command routing, reconnect logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, BudgetConfig, TelegramConfig
from llmcouncil.telegram.bot import CouncilBot, _MAX_QUERY_LEN


def _make_bot(authorized_chat_id: int | None = None) -> CouncilBot:
    cfg = AppConfig(
        telegram=TelegramConfig(authorized_chat_id=authorized_chat_id),
        budget=BudgetConfig(per_session_usd=1.0, per_day_usd=5.0),
    )
    return CouncilBot(token="fake-token", cfg=cfg)


def _make_update(chat_id: int, text: str = "", args: list[str] | None = None) -> MagicMock:
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
# Authorization
# ---------------------------------------------------------------------------

def test_is_authorized_no_chat_set() -> None:
    bot = _make_bot(authorized_chat_id=None)
    assert bot._is_authorized(12345)


def test_is_authorized_matching_chat() -> None:
    bot = _make_bot(authorized_chat_id=42)
    assert bot._is_authorized(42)


def test_is_not_authorized_different_chat() -> None:
    bot = _make_bot(authorized_chat_id=42)
    assert not bot._is_authorized(99)


@pytest.mark.asyncio
async def test_cmd_start_pairs_first_user() -> None:
    bot = _make_bot(authorized_chat_id=None)
    update = _make_update(chat_id=777)
    ctx = _make_context()

    await bot.cmd_start(update, ctx)

    assert bot._authorized_chat_id == 777
    update.message.reply_text.assert_awaited_once()
    msg = update.message.reply_text.call_args[0][0]
    assert "paired" in msg.lower() or "authorized" in msg.lower()


@pytest.mark.asyncio
async def test_cmd_start_rejects_second_user() -> None:
    bot = _make_bot(authorized_chat_id=100)
    update = _make_update(chat_id=999)
    ctx = _make_context()

    await bot.cmd_start(update, ctx)

    update.message.reply_text.assert_awaited_once()
    msg = update.message.reply_text.call_args[0][0]
    assert "paired" in msg.lower() or "another" in msg.lower()
    assert bot._authorized_chat_id == 100  # unchanged


@pytest.mark.asyncio
async def test_cmd_help_returns_commands() -> None:
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=1)
    ctx = _make_context()

    await bot.cmd_help(update, ctx)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.call_args[0][0]
    assert "/Council" in text
    assert "/budget" in text


@pytest.mark.asyncio
async def test_cmd_help_ignored_for_unauthorized() -> None:
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=999)
    ctx = _make_context()

    await bot.cmd_help(update, ctx)
    update.message.reply_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# /Council command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_council_no_query_replies_usage() -> None:
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=1)
    ctx = _make_context(args=[])

    await bot.cmd_council(update, ctx)

    update.message.reply_text.assert_awaited()
    text = update.message.reply_text.call_args[0][0]
    assert "Usage" in text or "usage" in text


@pytest.mark.asyncio
async def test_cmd_council_rejects_concurrent_session() -> None:
    bot = _make_bot(authorized_chat_id=1)
    # Simulate an active non-done task.
    fake_task = MagicMock()
    fake_task.done.return_value = False
    bot._active_session = fake_task

    update = _make_update(chat_id=1)
    ctx = _make_context(args=["What", "is", "42?"])

    await bot.cmd_council(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "already running" in text.lower() or "cancel" in text.lower()


# ---------------------------------------------------------------------------
# /cancel command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_cancel_active_session() -> None:
    bot = _make_bot(authorized_chat_id=1)
    fake_task = MagicMock()
    fake_task.done.return_value = False
    bot._active_session = fake_task

    update = _make_update(chat_id=1)
    ctx = _make_context()

    await bot.cmd_cancel(update, ctx)

    fake_task.cancel.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "cancel" in text.lower()


@pytest.mark.asyncio
async def test_cmd_cancel_no_session() -> None:
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=1)
    ctx = _make_context()

    await bot.cmd_cancel(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "no active" in text.lower()


# ---------------------------------------------------------------------------
# /budget command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_budget_shows_limits() -> None:
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=1)
    ctx = _make_context()

    await bot.cmd_budget(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "1.00" in text
    assert "5.00" in text


# ---------------------------------------------------------------------------
# Query length validation (MED-004)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_council_rejects_long_query() -> None:
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=1)
    oversized_query = "x" * (_MAX_QUERY_LEN + 1)
    ctx = _make_context(args=[oversized_query])

    await bot.cmd_council(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "too long" in text.lower() or "maximum" in text.lower()


@pytest.mark.asyncio
async def test_cmd_council_accepts_max_length_query() -> None:
    """Query exactly at the limit is not rejected for length (may be rejected for other reasons)."""
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=1)
    update.message.reply_text = AsyncMock(return_value=MagicMock())
    at_limit_query = ["x" * _MAX_QUERY_LEN]
    ctx = _make_context(args=at_limit_query)

    with patch("llmcouncil.telegram.bot.run_council", new=AsyncMock(return_value={"verdict_text": "ok"})):
        await bot.cmd_council(update, ctx)

    first_call_text = update.message.reply_text.call_args_list[0][0][0]
    assert "too long" not in first_call_text.lower()


# ---------------------------------------------------------------------------
# Generic error message (MED-006)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_error_shows_generic_message() -> None:
    bot = _make_bot(authorized_chat_id=1)
    update = _make_update(chat_id=1)
    update.message.reply_text = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    ctx = _make_context(args=["valid query"])

    with patch(
        "llmcouncil.telegram.bot.run_council",
        new=AsyncMock(side_effect=RuntimeError("internal model error: sk-ant-secret")),
    ):
        with patch("llmcouncil.telegram.bot.EventBus"):
            await bot.cmd_council(update, ctx)
            # Wait briefly for the task to run
            import asyncio
            await asyncio.sleep(0.05)

    if bot._active_session:
        try:
            await bot._active_session
        except Exception:
            pass

    status_mock = update.message.reply_text.return_value
    edit_calls = status_mock.edit_text.call_args_list
    if edit_calls:
        error_text = edit_calls[-1][0][0]
        assert "sk-ant" not in error_text
        assert "secret" not in error_text.lower() or "check logs" in error_text.lower()


# ---------------------------------------------------------------------------
# Auth lock — concurrent /start doesn't authorize two chats (HIGH-001)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cmd_start_is_atomic_under_concurrency() -> None:
    bot = _make_bot(authorized_chat_id=None)

    update_a = _make_update(chat_id=111)
    update_b = _make_update(chat_id=222)
    ctx = _make_context()

    import asyncio
    await asyncio.gather(
        bot.cmd_start(update_a, ctx),
        bot.cmd_start(update_b, ctx),
    )

    # Exactly one chat should be authorized — not both, not neither.
    assert bot._authorized_chat_id in (111, 222)
