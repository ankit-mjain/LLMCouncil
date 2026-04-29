"""Council orchestrator tests — all LiteLLM calls are mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmcouncil.config import AppConfig, CouncilConfig, SeatConfig, VotingConfig
from llmcouncil.council.orchestrator import build_council_graph, run_council
from llmcouncil.council.synthesizer import render_verdict
from llmcouncil.council.voting import VotePayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(text: str, tokens_in: int = 10, tokens_out: int = 20) -> MagicMock:
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = text
    mock.usage = MagicMock()
    mock.usage.prompt_tokens = tokens_in
    mock.usage.completion_tokens = tokens_out
    return mock


def _cheap_cfg(max_rounds: int = 3) -> AppConfig:
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
    )


def _da_cfg() -> AppConfig:
    return AppConfig(
        council=CouncilConfig(
            seats=[
                SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
                SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
                SeatConfig(seat_id=3, role="devils_advocate", provider="deepseek", model="deepseek-v3"),
                SeatConfig(seat_id=4, role="judge", provider="google", model="gemini/gemini-2.5-flash"),
            ],
            max_rounds=1,
            min_distinct_providers=4,
            devils_advocate_enabled=True,
        ),
        voting=VotingConfig(mechanism="simple_majority"),
    )


def _tie_cfg(tie_break: str) -> AppConfig:
    return AppConfig(
        council=CouncilConfig(
            seats=[
                SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
                SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
                SeatConfig(seat_id=3, role="judge", provider="google", model="gemini/gemini-2.5-flash"),
            ],
            max_rounds=3,
            min_distinct_providers=3,
        ),
        voting=VotingConfig(mechanism="simple_majority", tie_break=tie_break),
    )


PROPOSE_TEXT = "The answer is 42.\nCONFIDENCE: 0.85\nRATIONALE: Clear and complete."
CRITIQUE_TEXT = "The draft is accurate. Well done."
STRAW_DRAFT0 = "draft_0"
VOTE_JSON = '{"choice": "draft_0", "confidence": 0.85, "rationale": "Best", "concerns": []}'

# Three different votes with equal confidence — forces a 3-way tie in simple_majority.
VOTE_DRAFT0_EQ = '{"choice": "draft_0", "confidence": 0.7, "rationale": "Best", "concerns": []}'
VOTE_DRAFT1_EQ = '{"choice": "draft_1", "confidence": 0.7, "rationale": "Best", "concerns": []}'
VOTE_DRAFT2_EQ = '{"choice": "draft_2", "confidence": 0.7, "rationale": "Best", "concerns": []}'


# ---------------------------------------------------------------------------
# M3 tests (fixed protocol)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_council_unanimous_after_revision() -> None:
    """With max_rounds=3, if straw poll is unanimous after revision 1, stop early."""
    cfg = _cheap_cfg(max_rounds=3)

    responses = [
        _mock_response(PROPOSE_TEXT),            # propose draft_0
        _mock_response(CRITIQUE_TEXT),           # critique draft_0
        _mock_response(PROPOSE_TEXT),            # propose draft_1 (revision)
        _mock_response(CRITIQUE_TEXT),           # critique draft_1
        _mock_response(STRAW_DRAFT0),            # straw poll — critic
        _mock_response(STRAW_DRAFT0),            # straw poll — judge
        _mock_response(VOTE_JSON),               # vote — proposer
        _mock_response(VOTE_JSON),               # vote — critic
        _mock_response(VOTE_JSON),               # vote — judge
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("What is the answer to life?", cfg)

    assert "[Verdict]" in result["verdict_text"]
    assert result["terminated_by"] == "unanimous"
    assert len(result["drafts"]) == 2
    assert len(result["transcript"]) == 8


@pytest.mark.asyncio
async def test_council_round_cap() -> None:
    """With max_rounds=1, terminates immediately after first critique (no straw poll)."""
    cfg = _cheap_cfg(max_rounds=1)

    responses = [
        _mock_response(PROPOSE_TEXT),
        _mock_response(CRITIQUE_TEXT),
        _mock_response(VOTE_JSON),
        _mock_response(VOTE_JSON),
        _mock_response(VOTE_JSON),
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("Simple question?", cfg)

    assert "[Verdict]" in result["verdict_text"]
    assert result["terminated_by"] == "round_cap"
    assert len(result["drafts"]) == 1
    assert mock_llm.call_count == 5


@pytest.mark.asyncio
async def test_council_max_rounds_exhausted() -> None:
    """With max_rounds=2, terminates after 2 drafts without straw poll unanimity."""
    cfg = _cheap_cfg(max_rounds=2)

    responses = [
        _mock_response(PROPOSE_TEXT),
        _mock_response(CRITIQUE_TEXT),
        _mock_response(PROPOSE_TEXT),
        _mock_response(CRITIQUE_TEXT),
        _mock_response(VOTE_JSON),
        _mock_response(VOTE_JSON),
        _mock_response(VOTE_JSON),
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("Complex question?", cfg)

    assert result["terminated_by"] == "round_cap"
    assert len(result["drafts"]) == 2
    assert mock_llm.call_count == 7


@pytest.mark.asyncio
async def test_council_vote_parse_fallback() -> None:
    """Malformed vote JSON still produces a valid verdict via the fallback parser."""
    cfg = _cheap_cfg(max_rounds=1)

    responses = [
        _mock_response(PROPOSE_TEXT),
        _mock_response(CRITIQUE_TEXT),
        _mock_response("I choose draft_0 because it is best"),
        _mock_response("draft_0 is my choice {broken json"),
        _mock_response(VOTE_JSON),
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("Fallback test?", cfg)

    assert "[Verdict]" in result["verdict_text"]
    assert len(result["votes"]) == 3
    for vote in result["votes"]:
        assert vote["choice"] == "draft_0"


# ---------------------------------------------------------------------------
# M4 tests — Devil's Advocate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_council_devils_advocate_in_transcript() -> None:
    """DA seat produces dissent entries in the transcript alongside critic entries."""
    cfg = _da_cfg()

    responses = [
        _mock_response(PROPOSE_TEXT),                          # propose draft_0
        _mock_response(CRITIQUE_TEXT),                         # critique (critic, seat 2)
        _mock_response("I dissent: the answer ignores edge cases."),  # dissent (DA, seat 3)
        # round_cap (max_rounds=1) — no straw poll
        _mock_response(VOTE_JSON),   # vote proposer
        _mock_response(VOTE_JSON),   # vote critic
        _mock_response(VOTE_JSON),   # vote DA
        _mock_response(VOTE_JSON),   # vote judge
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("Test with DA?", cfg)

    dissent_entries = [e for e in result["transcript"] if e.get("kind") == "dissent"]
    assert len(dissent_entries) == 1
    assert "[Verdict]" in result["verdict_text"]
    assert mock_llm.call_count == 7


# ---------------------------------------------------------------------------
# M4 tests — judge_decides mechanism
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_judge_decides_mechanism() -> None:
    """judge_decides skips member votes; judge writes the verdict directly."""
    cfg = AppConfig(
        council=CouncilConfig(
            seats=[
                SeatConfig(seat_id=1, role="proposer", provider="anthropic", model="claude-haiku-4-5"),
                SeatConfig(seat_id=2, role="critic", provider="moonshot", model="kimi-k2"),
                SeatConfig(seat_id=3, role="judge", provider="google", model="gemini/gemini-2.5-flash"),
            ],
            max_rounds=1,
            min_distinct_providers=3,
        ),
        voting=VotingConfig(mechanism="judge_decides"),
    )

    responses = [
        _mock_response(PROPOSE_TEXT),                              # propose draft_0
        _mock_response(CRITIQUE_TEXT),                             # critique
        # round_cap → vote_node skips → synthesize_node calls judge
        _mock_response("[Verdict]\nThe judge has decided: 42."),   # judge decides
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("Judge decides test?", cfg)

    assert "[Verdict]" in result["verdict_text"]
    assert result["terminated_by"] == "judge"
    assert len(result["votes"]) == 0
    assert mock_llm.call_count == 3


# ---------------------------------------------------------------------------
# M4 tests — tie-break flows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_council_tie_user_pending() -> None:
    """3-way tie (each seat votes for a different draft) → tie_break=user → tie_user_pending."""
    cfg = _tie_cfg(tie_break="user")

    # max_rounds=3 → drafts 0,1,2; straw poll runs after draft_1 only (not unanimous)
    responses = [
        _mock_response(PROPOSE_TEXT),    # propose draft_0
        _mock_response(CRITIQUE_TEXT),   # critique draft_0
        # check_termination: len=1 < 2, no straw, continue
        _mock_response(PROPOSE_TEXT),    # propose draft_1
        _mock_response(CRITIQUE_TEXT),   # critique draft_1
        _mock_response(STRAW_DRAFT0),    # straw poll critic → draft_0
        _mock_response("draft_1"),       # straw poll judge → draft_1 (not unanimous)
        _mock_response(PROPOSE_TEXT),    # propose draft_2
        _mock_response(CRITIQUE_TEXT),   # critique draft_2
        # check_termination: len=3 >= max_rounds=3, round_cap
        _mock_response(VOTE_DRAFT0_EQ),  # vote proposer → draft_0 (conf 0.7)
        _mock_response(VOTE_DRAFT1_EQ),  # vote critic   → draft_1 (conf 0.7)
        _mock_response(VOTE_DRAFT2_EQ),  # vote judge    → draft_2 (conf 0.7)
        # 3-way tie at equal confidence → is_tie=True; tie_break=user → pending
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("Tie test?", cfg)

    assert result["terminated_by"] == "tie_user_pending"
    assert "TIE" in result["verdict_text"]
    assert mock_llm.call_count == 11


@pytest.mark.asyncio
async def test_council_judge_tie_break() -> None:
    """3-way tie → tie_break=judge → judge breaks tie → verdict produced."""
    cfg = _tie_cfg(tie_break="judge")

    responses = [
        _mock_response(PROPOSE_TEXT),    # propose draft_0
        _mock_response(CRITIQUE_TEXT),   # critique draft_0
        _mock_response(PROPOSE_TEXT),    # propose draft_1
        _mock_response(CRITIQUE_TEXT),   # critique draft_1
        _mock_response(STRAW_DRAFT0),    # straw poll critic
        _mock_response("draft_1"),       # straw poll judge → not unanimous
        _mock_response(PROPOSE_TEXT),    # propose draft_2
        _mock_response(CRITIQUE_TEXT),   # critique draft_2
        _mock_response(VOTE_DRAFT0_EQ),  # vote proposer → draft_0
        _mock_response(VOTE_DRAFT1_EQ),  # vote critic   → draft_1
        _mock_response(VOTE_DRAFT2_EQ),  # vote judge    → draft_2
        # 3-way tie → judge breaks it
        _mock_response("draft_0\nI choose draft_0 because it is most complete."),
    ]

    with patch("llmcouncil.council.llm_adapter.litellm.acompletion", new_callable=AsyncMock) as mock_llm, \
         patch("llmcouncil.council.llm_adapter.litellm.completion_cost", return_value=0.001):
        mock_llm.side_effect = responses
        result = await run_council("Tie judge test?", cfg)

    assert "[Verdict]" in result["verdict_text"]
    assert result["terminated_by"] == "judge"
    assert mock_llm.call_count == 12


# ---------------------------------------------------------------------------
# Synthesizer unit tests
# ---------------------------------------------------------------------------

def test_render_verdict_template() -> None:
    votes = [
        VotePayload(seat_id=1, choice="draft_0", confidence=0.9, rationale="Good"),
        VotePayload(seat_id=2, choice="draft_0", confidence=0.8, rationale="Agree"),
        VotePayload(seat_id=3, choice="draft_0", confidence=0.7, rationale="OK"),
    ]
    text, minority = render_verdict(
        winning_draft_text="The answer.",
        mechanism="simple_majority",
        winning_votes=3,
        total_votes=3,
        votes=votes,
        include_minority=False,
        minority_concerns=[],
    )
    assert "[Verdict]" in text
    assert "The answer." in text
    assert "simple_majority (3 of 3 seats)" in text
    assert minority is None


def test_render_verdict_with_minority() -> None:
    votes = [
        VotePayload(seat_id=1, choice="draft_0", confidence=0.9, rationale=""),
        VotePayload(seat_id=2, choice="draft_1", confidence=0.6, rationale="Disagree", concerns=["issue A"]),
    ]
    text, minority = render_verdict(
        winning_draft_text="Winner text.",
        mechanism="simple_majority",
        winning_votes=1,
        total_votes=2,
        votes=votes,
        include_minority=True,
        minority_concerns=["issue A", "Dissent (seat 2): Disagree"],
    )
    assert "[Minority view]" in text
    assert minority is not None
    assert "issue A" in minority


def test_build_council_graph_compiles() -> None:
    graph = build_council_graph()
    assert graph is not None
