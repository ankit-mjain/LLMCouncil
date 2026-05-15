"""Structured logging — structlog with API key / token redaction and file output."""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import structlog

# Matches common secret token formats that must never appear in logs.
_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9\-_]{20,}"         # OpenAI / LiteLLM style
    r"|ant-[A-Za-z0-9\-_]{20,}"        # Anthropic style
    r"|bot\d+:[A-Za-z0-9\-_]{30,}"    # Telegram bot token
    r"|tvly-[A-Za-z0-9\-_]{20,}"      # Tavily
    r")"
)


def _redact_secrets(
    _logger: object, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: replace known secret patterns with [REDACTED]."""
    for key, value in list(event_dict.items()):
        if isinstance(value, str) and _SECRET_RE.search(value):
            event_dict[key] = _SECRET_RE.sub("[REDACTED]", value)
    return event_dict


def init_logging(logs_dir: Path, level: str = "INFO") -> None:
    """Configure structlog for JSON-lines output to logs_dir/llmcouncil.jsonl (mode 0640)."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "llmcouncil.jsonl"

    log_handle = open(log_file, "a", encoding="utf-8")  # noqa: SIM115 — open for process lifetime

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_secrets,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=log_handle),
    )

    try:
        os.chmod(log_file, 0o640)
    except OSError as e:
        print(
            f"WARNING: Failed to set log file permissions on {log_file}: {e}",
            file=sys.stderr,
        )
