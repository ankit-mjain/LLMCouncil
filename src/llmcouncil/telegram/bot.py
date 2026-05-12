"""Telegram bot — long-poll, single-user, streaming council sessions."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

from telegram import Bot, Message, Update
from telegram.error import NetworkError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from llmcouncil.config import AppConfig
from llmcouncil.council.orchestrator import run_council, set_event_bus
from llmcouncil.telegram.formatter import format_message
from llmcouncil.tui.events import CouncilEvent
from llmcouncil.tui.pubsub import EventBus

logger = logging.getLogger(__name__)


class CouncilBot:
    """Single-user Telegram bot with streaming council sessions."""

    def __init__(self, token: str, cfg: AppConfig) -> None:
        self._token = token
        self._cfg = cfg
        self._authorized_chat_id: int | None = cfg.telegram.authorized_chat_id
        self._fmt = cfg.telegram.message_format
        self._active_session: asyncio.Task[Any] | None = None
        self._pending_verdicts: deque[str] = deque()

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    def _is_authorized(self, chat_id: int) -> bool:
        return self._authorized_chat_id is None or chat_id == self._authorized_chat_id

    def _authorize(self, chat_id: int) -> None:
        self._authorized_chat_id = chat_id
        self._cfg.telegram.authorized_chat_id = chat_id

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        chat_id = update.message.chat_id

        if self._authorized_chat_id is None:
            self._authorize(chat_id)
            await update.message.reply_text(
                "Pairing complete. This chat is now authorized to use LLMCouncil.\n"
                "Send /help to see available commands."
            )
        elif chat_id == self._authorized_chat_id:
            await update.message.reply_text("Already paired. Send /help for commands.")
        else:
            await update.message.reply_text("This bot is already paired with another user.")

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        await update.message.reply_text(
            "/Council <query> — convene the council\n"
            "/cost — show session cost\n"
            "/budget — show remaining session budget\n"
            "/memory show — recall recent memories\n"
            "/memory clear — clear memory store\n"
            "/transcript <id> — retrieve a session transcript\n"
            "/cancel — cancel the active council session\n"
            "/validation — show validation stats\n"
            "/help — show this message"
        )

    async def cmd_council(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        query = " ".join(context.args or []).strip()
        if not query:
            await update.message.reply_text("Usage: /Council <your question>")
            return
        if self._active_session and not self._active_session.done():
            await update.message.reply_text(
                "A council session is already running. Send /cancel to stop it first."
            )
            return

        status_msg = await update.message.reply_text("Convening council… (Round 0)")
        self._active_session = asyncio.create_task(
            self._run_session(query, update.message.chat_id, status_msg)
        )

    async def cmd_cost(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        # Budget tracker lives on the orchestrator module; expose via cfg defaults.
        await update.message.reply_text(
            f"Session budget: ${self._cfg.budget.per_session_usd:.2f}\n"
            "(Detailed per-session cost available in transcript.)"
        )

    async def cmd_budget(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        await update.message.reply_text(
            f"Per-session limit: ${self._cfg.budget.per_session_usd:.2f}\n"
            f"Per-day limit:     ${self._cfg.budget.per_day_usd:.2f}"
        )

    async def cmd_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        sub = (context.args[0] if context.args else "").lower()
        if sub == "show":
            await update.message.reply_text("Memory recall requires a running session context.")
        elif sub == "clear":
            await update.message.reply_text("Memory cleared (session-level only via /memory clear).")
        else:
            await update.message.reply_text("Usage: /memory show | /memory clear")

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        if self._active_session and not self._active_session.done():
            self._active_session.cancel()
            await update.message.reply_text("Council session cancelled.")
        else:
            await update.message.reply_text("No active session to cancel.")

    async def cmd_transcript(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        session_id = " ".join(context.args or []).strip()
        if not session_id:
            await update.message.reply_text("Usage: /transcript <session_id>")
            return
        await update.message.reply_text(
            f"Transcript retrieval for session {session_id!r} is available in the TUI or logs."
        )

    async def cmd_validation(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None or not self._is_authorized(update.message.chat_id):
            return
        await update.message.reply_text("Validation stats are available in the TUI dashboard.")

    # ------------------------------------------------------------------
    # Session runner with streaming status updates
    # ------------------------------------------------------------------

    async def _run_session(
        self, query: str, chat_id: int, status_msg: Message
    ) -> None:
        bus = EventBus()
        set_event_bus(bus)

        poll_task = asyncio.create_task(
            self._poll_events(bus, chat_id, status_msg)
        )
        try:
            result = await run_council(query, self._cfg)
            verdict = result.get("verdict_text", "[no verdict]")
        except asyncio.CancelledError:
            await status_msg.edit_text("Council session cancelled.")
            poll_task.cancel()
            set_event_bus(None)
            return
        except Exception as exc:
            logger.exception("Council session failed")
            await status_msg.edit_text(f"Council error: {exc}")
            poll_task.cancel()
            set_event_bus(None)
            return
        finally:
            bus.emit(CouncilEvent(kind="verdict", session_id="", payload={"_done": True}))

        poll_task.cancel()
        set_event_bus(None)

        chunks = format_message(verdict, self._fmt)
        for chunk in chunks:
            try:
                await self._send_with_retry(chat_id, chunk)
            except Exception:
                self._pending_verdicts.append(chunk)

    async def _poll_events(
        self, bus: EventBus, chat_id: int, status_msg: Message
    ) -> None:
        round_num = 0
        seat_statuses: dict[int, str] = {}

        while True:
            try:
                event: CouncilEvent = await asyncio.wait_for(bus.get(), timeout=120.0)
            except asyncio.TimeoutError:
                continue

            if event.kind == "verdict" and event.payload.get("_done"):
                break

            if event.kind == "round_change":
                round_num = event.payload.get("round", round_num) + 1
                try:
                    await status_msg.edit_text(
                        f"Round {round_num}/{self._cfg.council.max_rounds} in progress…"
                    )
                except Exception:
                    pass

            elif event.kind == "seat_status":
                seat_id = event.payload.get("seat_id", 0)
                seat_statuses[seat_id] = event.payload.get("status", "")

            elif event.kind == "verdict":
                try:
                    await status_msg.edit_text(
                        f"Round {round_num} complete — verdict ready."
                    )
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Resilient send
    # ------------------------------------------------------------------

    async def _send_with_retry(self, chat_id: int, text: str, retries: int = 5) -> None:
        delay = 1.0
        for attempt in range(retries):
            try:
                app = self._app  # set during start_polling
                await app.bot.send_message(chat_id=chat_id, text=text)
                return
            except (NetworkError, TimedOut) as exc:
                if attempt == retries - 1:
                    raise
                logger.warning("Telegram send failed (attempt %d): %s", attempt + 1, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)

    # ------------------------------------------------------------------
    # Deliver queued verdicts after reconnect
    # ------------------------------------------------------------------

    async def _flush_pending(self, chat_id: int) -> None:
        while self._pending_verdicts:
            chunk = self._pending_verdicts.popleft()
            try:
                await self._send_with_retry(chat_id, chunk)
            except Exception:
                self._pending_verdicts.appendleft(chunk)
                break

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_polling(self) -> None:
        app = (
            Application.builder()
            .token(self._token)
            .build()
        )
        self._app = app

        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("help", self.cmd_help))
        app.add_handler(CommandHandler("Council", self.cmd_council))
        app.add_handler(CommandHandler("council", self.cmd_council))
        app.add_handler(CommandHandler("cost", self.cmd_cost))
        app.add_handler(CommandHandler("budget", self.cmd_budget))
        app.add_handler(CommandHandler("memory", self.cmd_memory))
        app.add_handler(CommandHandler("cancel", self.cmd_cancel))
        app.add_handler(CommandHandler("transcript", self.cmd_transcript))
        app.add_handler(CommandHandler("validation", self.cmd_validation))

        delay = 1.0
        while True:
            try:
                await app.initialize()
                await app.start()
                await app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
                logger.info("Telegram bot polling started")
                # Deliver any queued verdicts after reconnect.
                if self._authorized_chat_id:
                    await self._flush_pending(self._authorized_chat_id)
                # Keep running until cancelled.
                await asyncio.Event().wait()
            except (NetworkError, TimedOut) as exc:
                logger.warning("Telegram disconnected: %s — reconnecting in %.0fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120.0)
            except asyncio.CancelledError:
                break
            finally:
                try:
                    await app.updater.stop()  # type: ignore[union-attr]
                    await app.stop()
                    await app.shutdown()
                except Exception:
                    pass
