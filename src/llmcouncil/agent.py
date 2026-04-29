"""Agent bootstrap — wires Telegram adapter + optional TUI event bus.

M0 stub: starts successfully, logs config summary. Full impl in M1.
"""

from __future__ import annotations

import structlog

from llmcouncil.config import AppConfig

log = structlog.get_logger(__name__)


async def start_agent(cfg: AppConfig) -> None:
    log.info(
        "agent_starting",
        default_model=cfg.default_llm.model,
        council_size=cfg.council.size,
        streaming=cfg.streaming.target,
    )
    raise NotImplementedError("Agent bootstrap not yet implemented (M1).")
