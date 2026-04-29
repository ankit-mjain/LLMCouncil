"""LiteLLM seat caller — wraps acompletion with latency and cost tracking."""

from __future__ import annotations

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


async def call_seat(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    timeout_s: int = 30,
    max_tokens: int | None = None,
) -> LLMResponse:
    # LiteLLM accepts "provider/model" or just "model" depending on the provider.
    model_str = model if "/" in model else f"{provider}/{model}"

    kwargs: dict[str, object] = {
        "model": model_str,
        "messages": messages,
        "timeout": timeout_s,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    start = time.monotonic()
    response = await litellm.acompletion(**kwargs)  # type: ignore[arg-type]
    latency_ms = int((time.monotonic() - start) * 1000)

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
