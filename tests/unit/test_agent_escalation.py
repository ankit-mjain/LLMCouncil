"""Agent dispatch and auto-escalation unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.agent import _parse_confidence, _strip_confidence_footer, dispatch
from llmcouncil.config import AppConfig, CouncilConfig, SeatConfig, TriggersConfig, VotingConfig


def _mock_response(text: str) -> MagicMock:
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = text
    m.usage = MagicMock()
    m.usage.prompt_tokens = 10
    m.usage.completion_tokens = 20
    return m


def _council_cfg(auto_escalate: bool = True) -> AppConfig:
    return AppConfig(
        council=CouncilConfig(
            seats=[
                SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
                SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
                SeatConfig(seat_id=3, role="judge", provider="google", model="gemini/gemini-2.5-flash"),
            ],
            max_rounds=1,
            min_distinct_providers=3,
        ),
        voting=VotingConfig(mechanism="simple_majority"),
        triggers=TriggersConfig(
            explicit=["/Council"],
            auto_escalate=auto_escalate,
            escalation_confidence_threshold=0.6,
        ),
    )


PROPOSE_TEXT = "The answer.\nCONFIDENCE: 0.85\nRATIONALE: Clear."
CRITIQUE_TEXT = "Looks good."
VOTE_JSON = '{"choice": "draft_0", "confidence": 0.85, "rationale": "Best", "concerns": []}'


# ---------------------------------------------------------------------------
# _parse_confidence
# ---------------------------------------------------------------------------

def test_parse_confidence_found() -> None:
    assert abs(_parse_confidence("Some answer.\nCONFIDENCE: 0.42") - 0.42) < 1e-9


def test_parse_confidence_missing_defaults_to_one() -> None:
    assert _parse_confidence("No confidence line here.") == 1.0


def test_parse_confidence_clamped_high() -> None:
    assert _parse_confidence("CONFIDENCE: 1.5") == 1.0


def test_parse_confidence_case_insensitive() -> None:
    assert abs(_parse_confidence("confidence: 0.75") - 0.75) < 1e-9


# ---------------------------------------------------------------------------
# _strip_confidence_footer
# ---------------------------------------------------------------------------

def test_strip_confidence_footer_removes_line() -> None:
    text = "The answer is 42.\nCONFIDENCE: 0.85"
    clean = _strip_confidence_footer(text)
    assert "CONFIDENCE" not in clean
    assert "The answer is 42." in clean


def test_strip_confidence_footer_no_footer_unchanged() -> None:
    text = "The answer is 42."
    assert "42" in _strip_confidence_footer(text)


# ---------------------------------------------------------------------------
# dispatch — high confidence, no escalation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_high_confidence_no_escalation() -> None:
    cfg = _council_cfg()
    single_shot_text = "The answer is 42.\nCONFIDENCE: 0.90"

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.return_value = _mock_response(single_shot_text)
        result = await dispatch("What is 6 * 7?", cfg)

    assert "42" in result
    assert "Auto-escalating" not in result
    assert mock_llm.call_count == 1


# ---------------------------------------------------------------------------
# dispatch — low confidence → auto-escalation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_low_confidence_escalates() -> None:
    cfg = _council_cfg()
    single_shot_text = "I'm uncertain.\nCONFIDENCE: 0.30"

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = [
            _mock_response(single_shot_text),   # single-shot call
            _mock_response(PROPOSE_TEXT),        # council: propose
            _mock_response(CRITIQUE_TEXT),       # council: critique
            _mock_response(VOTE_JSON),           # council: vote proposer
            _mock_response(VOTE_JSON),           # council: vote critic
            _mock_response(VOTE_JSON),           # council: vote judge
        ]
        result = await dispatch("Hard question?", cfg)

    assert "Auto-escalating" in result
    assert "0.30" in result
    assert "[Verdict]" in result
    assert mock_llm.call_count == 6


# ---------------------------------------------------------------------------
# dispatch — auto_escalate disabled
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_auto_escalate_disabled_stays_single_shot() -> None:
    cfg = _council_cfg(auto_escalate=False)
    low_conf_text = "I'm not sure.\nCONFIDENCE: 0.10"

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.return_value = _mock_response(low_conf_text)
        result = await dispatch("Tricky question?", cfg)

    assert "Auto-escalating" not in result
    assert mock_llm.call_count == 1


# ---------------------------------------------------------------------------
# dispatch — explicit /Council prefix bypasses single-shot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_explicit_council_trigger() -> None:
    cfg = _council_cfg()

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = [
            _mock_response(PROPOSE_TEXT),
            _mock_response(CRITIQUE_TEXT),
            _mock_response(VOTE_JSON),
            _mock_response(VOTE_JSON),
            _mock_response(VOTE_JSON),
        ]
        result = await dispatch("/Council What is the meaning of life?", cfg)

    assert "[Verdict]" in result
    # No single-shot preamble — exactly 5 council calls
    assert mock_llm.call_count == 5


# ---------------------------------------------------------------------------
# dispatch — memory context is injected into the request
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_memory_context_injected() -> None:
    cfg = _council_cfg(auto_escalate=False)
    response_text = "Answered with context.\nCONFIDENCE: 0.90"
    captured: list[dict] = []

    async def _capture(**kwargs):  # type: ignore[no-untyped-def]
        captured.extend(kwargs.get("messages", []))
        return _mock_response(response_text)

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.0):
        mock_llm.side_effect = _capture
        await dispatch("New question?", cfg, memory_context="Prior: user prefers brevity.")

    assert any("Prior: user prefers brevity." in m.get("content", "") for m in captured)
