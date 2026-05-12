"""LiteLLM seat caller — wraps acompletion with latency, cost tracking, and retry on 429/5xx."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass

import litellm

litellm.suppress_debug_info = True  # type: ignore[attr-defined]


@dataclass
class LLMResponse:
    text: str
    tokens_in: int
    tokens_out: int
    usd: float
    latency_ms: int


class SeatError(Exception):
    """Raised when a seat fails after all retries (errored) or exceeds the hard latency cap (timed_out)."""

    def __init__(self, seat_id: int, reason: str) -> None:
        self.seat_id = seat_id
        self.reason = reason  # "timed_out" | "errored: <msg>"
        super().__init__(f"Seat {seat_id} failed: {reason}")


def _is_retryable(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "ratelimit" in name
        or "serviceunavailable" in name
        or "internalserver" in name
        or "429" in msg
        or any(f" {code}" in msg or msg.startswith(code) for code in ("500", "502", "503", "504"))
    )


async def call_seat(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_s: int = 30,
    max_tokens: int | None = None,
    seat_id: int = 0,
) -> LLMResponse:
    model_str = model if "/" in model else f"{provider}/{model}"

    kwargs: dict[str, object] = {
        "model": model_str,
        "messages": messages,
        "timeout": timeout_s,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    last_exc: Exception = RuntimeError("unknown")
    for attempt in range(2):
        try:
            start = time.monotonic()
            response = await litellm.acompletion(**kwargs)  # type: ignore[arg-type]
            latency_ms = int((time.monotonic() - start) * 1000)
            break
        except Exception as exc:
            last_exc = exc
            if attempt == 0 and _is_retryable(exc):
                await asyncio.sleep(random.uniform(1.0, 3.0))
                continue
            raise SeatError(seat_id, f"errored: {exc}") from exc
    else:
        raise SeatError(seat_id, f"errored after retry: {last_exc}") from last_exc

    text: str = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    tokens_in: int = usage.prompt_tokens if usage else 0
    tokens_out: int = usage.completion_tokens if usage else 0

    try:
        usd: float = litellm.completion_cost(completion_response=response)  # type: ignore[attr-defined]
    except Exception:
        usd = 0.0

    return LLMResponse(
        text=text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        usd=usd,
        latency_ms=latency_ms,
    )
