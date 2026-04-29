"""Agent bootstrap — single-LLM responder and council dispatcher with auto-escalation."""

from __future__ import annotations

import re

import structlog

from llmcouncil.config import AppConfig
from llmcouncil.council.llm_adapter import call_seat
from llmcouncil.council.orchestrator import run_council

log = structlog.get_logger(__name__)

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
        return f"{notice}\n\n{state['verdict_text']}"

    return clean_text


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
