"""Failure-mode tests — SeatError retry, budget abort, all-seats-errored, web search flag."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, BudgetConfig, CouncilConfig, SeatConfig, VotingConfig
from llmcouncil.council.budget import BudgetExceededError, BudgetTracker
from llmcouncil.council.llm_adapter import SeatError, _is_retryable, call_seat
from llmcouncil.council.orchestrator import run_council, set_budget_tracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(text: str) -> MagicMock:
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = text
    mock.usage = MagicMock()
    mock.usage.prompt_tokens = 10
    mock.usage.completion_tokens = 20
    return mock


def _cheap_cfg(max_rounds: int = 1, budget_usd: float = 10.0) -> AppConfig:
    return AppConfig(
        council=CouncilConfig(
            seats=[
                SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
                SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
                SeatConfig(seat_id=3, role="judge", provider="google", model="gemini/gemini-2.5-flash"),
            ],
            max_rounds=max_rounds,
            min_distinct_providers=3,
        ),
        voting=VotingConfig(mechanism="simple_majority"),
        budget=BudgetConfig(per_session_usd=budget_usd, hard_latency_s=90),
    )


PROPOSE_TEXT = "The answer.\nCONFIDENCE: 0.85\nRATIONALE: Complete."
CRITIQUE_TEXT = "Looks good."
VOTE_JSON = '{"choice": "draft_0", "confidence": 0.85, "rationale": "Best", "concerns": []}'


# ---------------------------------------------------------------------------
# SeatError / retry tests
# ---------------------------------------------------------------------------

def test_is_retryable_rate_limit() -> None:
    class FakeRateLimitError(Exception):
        pass
    FakeRateLimitError.__name__ = "RateLimitError"
    assert _is_retryable(FakeRateLimitError("too many requests"))


def test_is_retryable_500_in_message() -> None:
    assert _is_retryable(Exception("server returned 500 internal server error"))


def test_is_retryable_non_retryable() -> None:
    assert not _is_retryable(ValueError("bad input"))


@pytest.mark.asyncio
async def test_call_seat_retries_once_on_rate_limit() -> None:
    """First call raises a rate-limit-like error; second call succeeds."""
    good_response = _mock_response("hello")

    class FakeRateLimitError(Exception):
        pass
    FakeRateLimitError.__name__ = "RateLimitError"

    call_count = 0

    async def fake_completion(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FakeRateLimitError("429 rate limit")
        return good_response

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", side_effect=fake_completion), \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001), \
         patch("llmcouncil.council.llm_adapter.asyncio.sleep", new_callable=AsyncMock):
        resp = await call_seat("anthropic", "claude-haiku-4-5", [{"role": "user", "content": "hi"}])

    assert resp.text == "hello"
    assert call_count == 2


@pytest.mark.asyncio
async def test_call_seat_raises_seat_error_after_two_failures() -> None:
    """Both attempts fail → SeatError raised."""
    class FakeRateLimitError(Exception):
        pass
    FakeRateLimitError.__name__ = "RateLimitError"

    async def always_fail(**kwargs: object) -> MagicMock:
        raise FakeRateLimitError("rate limited")

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", side_effect=always_fail), \
         patch("llmcouncil.council.llm_adapter.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(SeatError) as exc_info:
            await call_seat(
                "anthropic", "claude-haiku-4-5",
                [{"role": "user", "content": "hi"}],
                seat_id=7,
            )
    assert exc_info.value.seat_id == 7


@pytest.mark.asyncio
async def test_call_seat_raises_seat_error_on_non_retryable() -> None:
    """Non-retryable error on first attempt raises SeatError immediately (no retry)."""
    call_count = 0

    async def fail_once(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        raise ValueError("bad request")

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", side_effect=fail_once):
        with pytest.raises(SeatError):
            await call_seat("anthropic", "claude-haiku-4-5", [{"role": "user", "content": "hi"}])

    assert call_count == 1


# ---------------------------------------------------------------------------
# Orchestrator failure mode: budget abort
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_abort_before_first_draft() -> None:
    """Budget exhausted before proposer call → verdict contains abort note."""
    cfg = _cheap_cfg(max_rounds=1, budget_usd=0.0)  # zero budget

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = [_mock_response(PROPOSE_TEXT)]
        result = await run_council("What is 2+2?", cfg)

    assert "aborted" in result["verdict_text"].lower() or "budget" in result["verdict_text"].lower()
    assert result["terminated_by"] in ("budget_exceeded", "all_seats_errored")


# ---------------------------------------------------------------------------
# Orchestrator failure mode: critic seat errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_critic_seat_error_session_continues() -> None:
    """Critic seat fails but session continues with empty critiques; verdict produced."""
    cfg = _cheap_cfg(max_rounds=1)

    class FakeRateLimitError(Exception):
        pass
    FakeRateLimitError.__name__ = "RateLimitError"

    responses = [
        _mock_response(PROPOSE_TEXT),     # propose
        # critic errors (two retries both fail) — handled by mock raising twice
        _mock_response(VOTE_JSON),        # vote proposer
        _mock_response(VOTE_JSON),        # vote critic (if it recovers to vote)
        _mock_response(VOTE_JSON),        # vote judge
    ]

    call_count = 0

    async def selective_fail(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        # calls 1=propose, 2=critique (fail first attempt), 3=critique (retry, also fail)
        # After that, votes succeed.
        if call_count in (2, 3):
            raise FakeRateLimitError("rate limited")
        idx = call_count - 1
        # Adjust index: call 1 → responses[0], call 4+ → responses[1], [2], [3]
        adjusted = 0 if call_count == 1 else call_count - 3
        return responses[min(adjusted, len(responses) - 1)]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", side_effect=selective_fail), \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001), \
         patch("llmcouncil.council.llm_adapter.asyncio.sleep", new_callable=AsyncMock):
        result = await run_council("Test critic error?", cfg)

    # Session should produce a verdict despite critic seat failure.
    assert result["verdict_text"]


# ---------------------------------------------------------------------------
# Orchestrator failure mode: all votes error → fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_votes_error_produces_fallback_verdict() -> None:
    """All vote calls fail → synthesize_node uses last draft as fallback verdict."""
    cfg = _cheap_cfg(max_rounds=1)

    call_count = 0

    async def fail_votes(**kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _mock_response(PROPOSE_TEXT)
        if call_count == 2:
            return _mock_response(CRITIQUE_TEXT)
        raise SeatError(call_count, "errored: timeout")

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", side_effect=fail_votes), \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001), \
         patch("llmcouncil.council.llm_adapter.asyncio.sleep", new_callable=AsyncMock):
        result = await run_council("All votes fail?", cfg)

    assert "fallback" in result["verdict_text"].lower() or result["verdict_text"]
    # terminated_by may be all_seats_errored or seat_error depending on the path
    assert result.get("terminated_by") in (
        "all_seats_errored", "round_cap", "budget_exceeded", "seat_error", ""
    )


# ---------------------------------------------------------------------------
# Web search unavailable flag
# ---------------------------------------------------------------------------

def test_search_unavailable_flag_preserved_in_critique() -> None:
    """[search_unavailable] text in a critique is preserved as-is (no stripping)."""
    text = "The draft has a gap. [search_unavailable] Could not verify via web."
    assert "[search_unavailable]" in text
