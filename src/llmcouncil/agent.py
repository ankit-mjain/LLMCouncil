"""Agent bootstrap — single-LLM responder and council dispatcher with auto-escalation."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Callable, Awaitable

import structlog

from llmcouncil.config import AppConfig
from llmcouncil.council.llm_adapter import call_seat
from llmcouncil.council.orchestrator import run_council

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

log = structlog.get_logger(__name__)

# Module-level slots set by the CLI/bot at startup.
_db_factory: "sessionmaker | None" = None
_poll_callback: "Callable[[str], Awaitable[None]] | None" = None
_council_session_count: int = 0


def set_validation_db(factory: "sessionmaker | None") -> None:
    global _db_factory
    _db_factory = factory


def set_poll_callback(fn: "Callable[[str], Awaitable[None]] | None") -> None:
    global _poll_callback
    _poll_callback = fn

_CONFIDENCE_RE = re.compile(r"CONFIDENCE:\s*([\d.]+)", re.IGNORECASE)


def _parse_confidence(text: str) -> float:
    """Extract the CONFIDENCE: 0.XX footer; returns 1.0 if absent."""
    m = _CONFIDENCE_RE.search(text)
    if m:
        try:
            return max(0.0, min(1.0, float(m.group(1))))
        except ValueError:
            pass
    return 1.0


def _strip_confidence_footer(text: str) -> str:
    """Remove the CONFIDENCE: line and trailing whitespace from a response."""
    return _CONFIDENCE_RE.sub("", text).rstrip()


async def single_shot(query: str, cfg: AppConfig) -> str:
    """Call the configured default LLM and return the response text (no confidence gate)."""
    resp = await call_seat(
        provider=cfg.default_llm.provider,
        model=cfg.default_llm.model,
        messages=[{"role": "user", "content": query}],
        timeout_s=cfg.budget.hard_latency_s,
    )
    log.info("single_shot_done", tokens_in=resp.tokens_in, tokens_out=resp.tokens_out, usd=resp.usd)
    return resp.text


async def dispatch(query: str, cfg: AppConfig, memory_context: str = "") -> str:
    """Route a query to council (explicit trigger or auto-escalation) or single-shot.

    memory_context: pre-fetched memory summaries to prepend to the query.
    """
    enriched = f"{memory_context}\n\n---\n\n{query}" if memory_context else query

    # Explicit /Council trigger — bypass single-shot entirely.
    for trigger in cfg.triggers.explicit:
        if query.startswith(trigger):
            actual = query[len(trigger):].strip()
            council_query = f"{memory_context}\n\n---\n\n{actual}" if memory_context else actual
            log.info("council_triggered", trigger=trigger)
            state = await run_council(council_query, cfg)
            await _post_council(actual or query, cfg)
            return str(state["verdict_text"])

    # Single-shot with confidence extraction.
    messages = [
        {
            "role": "system",
            "content": (
                "Answer the user's question directly and thoroughly. "
                "End your response with exactly:\n"
                "CONFIDENCE: 0.XX\n"
                "where 0.XX is your confidence in the answer (0.0 = no idea, 1.0 = certain)."
            ),
        },
        {"role": "user", "content": enriched},
    ]
    resp = await call_seat(
        provider=cfg.default_llm.provider,
        model=cfg.default_llm.model,
        messages=messages,
        timeout_s=cfg.budget.hard_latency_s,
    )
    log.info("single_shot_done", tokens_in=resp.tokens_in, tokens_out=resp.tokens_out, usd=resp.usd)

    confidence = _parse_confidence(resp.text)
    clean_text = _strip_confidence_footer(resp.text)

    # Auto-escalation gate.
    if cfg.triggers.auto_escalate and confidence < cfg.triggers.escalation_confidence_threshold:
        log.info(
            "auto_escalating",
            confidence=confidence,
            threshold=cfg.triggers.escalation_confidence_threshold,
        )
        notice = (
            f"[Auto-escalating to council — "
            f"confidence {confidence:.2f} < threshold "
            f"{cfg.triggers.escalation_confidence_threshold:.2f}]"
        )
        state = await run_council(enriched, cfg)
        await _post_council(query, cfg)
        return f"{notice}\n\n{state['verdict_text']}"

    return clean_text


async def _post_council(query: str, cfg: AppConfig) -> None:
    """Fire shadow run and optionally send preference poll after a council session."""
    global _council_session_count
    _council_session_count += 1

    from llmcouncil.validation.shadow import run_shadow

    asyncio.create_task(run_shadow(query, cfg, db_factory=_db_factory))

    n = cfg.validation.prompt_user_for_preference_every_n
    if _poll_callback and n > 0 and _council_session_count % n == 0:
        msg = (
            "Which response did you prefer?\n"
            "Reply: /prefer council | /prefer single | /prefer tie | /prefer skip"
        )
        asyncio.create_task(_poll_callback(msg))


async def start_agent(cfg: AppConfig) -> None:
    """Entry point for `llmcouncil run`. Telegram wiring lives in M7."""
    log.info(
        "agent_starting",
        default_model=cfg.default_llm.model,
        council_size=cfg.council.size,
        streaming=cfg.streaming.target,
    )
    raise NotImplementedError(
        "Full Telegram agent bootstrap is scheduled for M7. "
        "Use dispatch() directly for programmatic access."
    )
