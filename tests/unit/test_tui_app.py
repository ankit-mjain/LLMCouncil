"""TUI app and orchestrator event-emission tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, CouncilConfig, SeatConfig, TriggersConfig, VotingConfig
from llmcouncil.council.orchestrator import set_event_bus
from llmcouncil.tui.app import CouncilTUI
from llmcouncil.tui.events import CouncilEvent
from llmcouncil.tui.pubsub import EventBus


def _cfg() -> AppConfig:
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
        triggers=TriggersConfig(explicit=["/Council"], auto_escalate=False),
    )


def _mock_resp(text: str) -> MagicMock:
    m = MagicMock()
    m.choices = [MagicMock()]
    m.choices[0].message.content = text
    m.usage = MagicMock()
    m.usage.prompt_tokens = 10
    m.usage.completion_tokens = 20
    return m


PROPOSE_TEXT = "Draft answer.\nCONFIDENCE: 0.85\nRATIONALE: Clear."
CRITIQUE_TEXT = "Looks fine."
VOTE_JSON = '{"choice": "draft_0", "confidence": 0.85, "rationale": "Best", "concerns": []}'


# ---------------------------------------------------------------------------
# CouncilTUI instantiation (no Textual terminal required)
# ---------------------------------------------------------------------------

def test_council_tui_has_event_bus() -> None:
    tui = CouncilTUI(_cfg())
    assert isinstance(tui._bus, EventBus)


def test_council_tui_stores_config() -> None:
    cfg = _cfg()
    tui = CouncilTUI(cfg)
    assert tui.cfg is cfg


def test_council_tui_initial_cost_zero() -> None:
    tui = CouncilTUI(_cfg())
    assert tui._total_cost == 0.0


# ---------------------------------------------------------------------------
# Orchestrator event emission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orchestrator_emits_round_change_and_transcript() -> None:
    bus = EventBus()
    set_event_bus(bus)

    try:
        with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
             patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
            mock_llm.side_effect = [
                _mock_resp(PROPOSE_TEXT),
                _mock_resp(CRITIQUE_TEXT),
                _mock_resp(VOTE_JSON),
                _mock_resp(VOTE_JSON),
                _mock_resp(VOTE_JSON),
            ]
            from llmcouncil.council.orchestrator import run_council
            await run_council("What is 1+1?", _cfg())
    finally:
        set_event_bus(None)

    events = bus.drain()
    kinds = [e.kind for e in events]
    assert "round_change" in kinds
    assert "transcript_entry" in kinds
    assert "verdict" in kinds


@pytest.mark.asyncio
async def test_orchestrator_emits_verdict_event() -> None:
    bus = EventBus()
    set_event_bus(bus)

    try:
        with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
             patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.0):
            mock_llm.side_effect = [
                _mock_resp(PROPOSE_TEXT),
                _mock_resp(CRITIQUE_TEXT),
                _mock_resp(VOTE_JSON),
                _mock_resp(VOTE_JSON),
                _mock_resp(VOTE_JSON),
            ]
            from llmcouncil.council.orchestrator import run_council
            await run_council("Simple question", _cfg())
    finally:
        set_event_bus(None)

    verdicts = [e for e in bus.drain() if e.kind == "verdict"]
    assert len(verdicts) == 1
    assert "text" in verdicts[0].payload
    assert verdicts[0].payload["text"]


@pytest.mark.asyncio
async def test_orchestrator_no_events_without_bus() -> None:
    set_event_bus(None)

    bus = EventBus()
    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.0):
        mock_llm.side_effect = [
            _mock_resp(PROPOSE_TEXT),
            _mock_resp(CRITIQUE_TEXT),
            _mock_resp(VOTE_JSON),
            _mock_resp(VOTE_JSON),
            _mock_resp(VOTE_JSON),
        ]
        from llmcouncil.council.orchestrator import run_council
        await run_council("Question", _cfg())

    # bus was never registered, so it should be empty
    assert bus.size == 0
