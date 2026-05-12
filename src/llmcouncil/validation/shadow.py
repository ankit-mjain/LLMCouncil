"""Shadow A/B runner — single-LLM call alongside each council session (§26)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

import structlog

from llmcouncil.config import AppConfig
from llmcouncil.council.llm_adapter import call_seat

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

log = structlog.get_logger(__name__)


async def run_shadow(
    query: str,
    cfg: AppConfig,
    session_id: str = "",
    db_factory: "sessionmaker | None" = None,
) -> str:
    """Run a single-LLM shadow call and record to DB if db_factory is provided.

    Returns the shadow response text, or "" if disabled or errored.
    """
    if not cfg.validation.ab_logging:
        return ""

    provider = cfg.default_llm.provider
    model = cfg.default_llm.model
    t0 = time.monotonic()

    try:
        resp = await call_seat(
            provider,
            model,
            [{"role": "user", "content": query}],
            timeout_s=cfg.budget.hard_latency_s,
        )
    except Exception as exc:
        log.warning("shadow_run_failed", error=str(exc))
        return ""

    latency_ms = int((time.monotonic() - t0) * 1000)
    log.info("shadow_run_complete", latency_ms=latency_ms, usd=resp.usd)

    if db_factory is not None:
        _persist_shadow(db_factory, session_id, provider, model, resp, latency_ms)

    return resp.text


def _persist_shadow(
    db_factory: "sessionmaker",
    session_id: str,
    provider: str,
    model: str,
    resp: object,
    latency_ms: int,
) -> None:
    from llmcouncil.persistence.models import ShadowRun

    try:
        with db_factory() as db:
            run = ShadowRun(
                session_id=session_id or None,
                single_llm_provider=provider,
                single_llm_model=model,
                verdict_text=resp.text,  # type: ignore[attr-defined]
                tokens_in=resp.tokens_in,  # type: ignore[attr-defined]
                tokens_out=resp.tokens_out,  # type: ignore[attr-defined]
                usd=resp.usd,  # type: ignore[attr-defined]
                latency_ms=latency_ms,
                created_at=datetime.now(timezone.utc),
            )
            db.add(run)
            db.commit()
    except Exception as exc:
        log.warning("shadow_persist_failed", error=str(exc))
