"""Agent bootstrap — single-LLM responder (M1) and council dispatcher (M3)."""

from __future__ import annotations

import structlog

from llmcouncil.config import AppConfig
from llmcouncil.council.llm_adapter import call_seat
from llmcouncil.council.orchestrator import run_council

log = structlog.get_logger(__name__)


async def single_shot(query: str, cfg: AppConfig) -> str:
    """Call the configured default LLM and return the response text."""
    resp = await call_seat(
        provider=cfg.default_llm.provider,
        model=cfg.default_llm.model,
        messages=[{"role": "user", "content": query}],
        timeout_s=cfg.budget.hard_latency_s,
    )
    log.info("single_shot_done", tokens_in=resp.tokens_in, tokens_out=resp.tokens_out, usd=resp.usd)
    return resp.text


async def dispatch(query: str, cfg: AppConfig) -> str:
    """Route a query: explicit /Council prefix → council; otherwise single-shot."""
    for trigger in cfg.triggers.explicit:
        if query.startswith(trigger):
            actual_query = query[len(trigger):].strip()
            log.info("council_triggered", trigger=trigger)
            state = await run_council(actual_query, cfg)
            return str(state["verdict_text"])

    return await single_shot(query, cfg)


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
