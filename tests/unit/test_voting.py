"""Voting engine unit tests."""

from __future__ import annotations

from llmcouncil.council.voting import (
    VotePayload,
    ranked_choice,
    simple_majority,
    straw_poll_unanimous,
    supermajority,
    weighted_vote,
)


def _vote(seat_id: int, choice: str, confidence: float = 0.8) -> VotePayload:
    return VotePayload(seat_id=seat_id, choice=choice, confidence=confidence, rationale="")


# ---------------------------------------------------------------------------
# simple_majority
# ---------------------------------------------------------------------------

def test_simple_majority_clear_winner() -> None:
    votes = [_vote(1, "draft_0"), _vote(2, "draft_0"), _vote(3, "draft_1")]
    winner, is_tie = simple_majority(votes)
    assert winner == "draft_0"
    assert is_tie is False


def test_simple_majority_tie_broken_by_confidence() -> None:
    votes = [
        _vote(1, "draft_0", 0.5),
        _vote(2, "draft_1", 0.9),
    ]
    winner, is_tie = simple_majority(votes)
    assert winner == "draft_1"
    assert is_tie is False


def test_simple_majority_true_tie() -> None:
    votes = [
        _vote(1, "draft_0", 0.7),
        _vote(2, "draft_1", 0.7),
    ]
    _winner, is_tie = simple_majority(votes)
    assert is_tie is True


def test_simple_majority_unanimous() -> None:
    votes = [_vote(1, "draft_2"), _vote(2, "draft_2"), _vote(3, "draft_2")]
    winner, is_tie = simple_majority(votes)
    assert winner == "draft_2"
    assert is_tie is False


# ---------------------------------------------------------------------------
# supermajority
# ---------------------------------------------------------------------------

def test_supermajority_unanimous() -> None:
    votes = [_vote(1, "draft_0"), _vote(2, "draft_0"), _vote(3, "draft_0")]
    winner, is_tie = supermajority(votes)
    assert winner == "draft_0"
    assert is_tie is False


def test_supermajority_2_of_3_qualifies() -> None:
    # 2 of 3 votes = 66.7% ≥ threshold(2/3 = 66.7%) → qualifies
    votes = [_vote(1, "draft_0"), _vote(2, "draft_0"), _vote(3, "draft_1")]
    winner, is_tie = supermajority(votes)
    assert winner == "draft_0"
    assert is_tie is False


def test_supermajority_not_reached_signals_tie() -> None:
    # 1-1-1 split: no draft reaches ≥ 2 votes (required = 3 * 2/3 = 2.0)
    votes = [_vote(1, "draft_0"), _vote(2, "draft_1"), _vote(3, "draft_2")]
    _winner, is_tie = supermajority(votes)
    assert is_tie is True


# ---------------------------------------------------------------------------
# ranked_choice
# ---------------------------------------------------------------------------

def test_ranked_choice_majority_first_pref() -> None:
    votes = [_vote(1, "draft_0"), _vote(2, "draft_0"), _vote(3, "draft_1")]
    winner, is_tie = ranked_choice(votes)
    assert winner == "draft_0"
    assert is_tie is False


def test_ranked_choice_instant_runoff() -> None:
    votes = [
        VotePayload(seat_id=1, choice="draft_0", confidence=0.8, rationale="",
                    rankings=["draft_0", "draft_1"]),
        VotePayload(seat_id=2, choice="draft_1", confidence=0.7, rationale="",
                    rankings=["draft_1", "draft_0"]),
        VotePayload(seat_id=3, choice="draft_2", confidence=0.6, rationale="",
                    rankings=["draft_2", "draft_0"]),
    ]
    # First round: 1-1-1 → eliminate draft_2 → seat_3 transfers to draft_0
    # Second round: draft_0=2, draft_1=1 → draft_0 wins
    winner, is_tie = ranked_choice(votes)
    assert winner == "draft_0"
    assert is_tie is False


def test_ranked_choice_two_way_tie() -> None:
    votes = [
        VotePayload(seat_id=1, choice="draft_0", confidence=0.7, rationale="",
                    rankings=["draft_0", "draft_1"]),
        VotePayload(seat_id=2, choice="draft_1", confidence=0.7, rationale="",
                    rankings=["draft_1", "draft_0"]),
    ]
    _winner, is_tie = ranked_choice(votes)
    assert is_tie is True


# ---------------------------------------------------------------------------
# weighted_vote
# ---------------------------------------------------------------------------

def test_weighted_vote_clear_winner() -> None:
    votes = [_vote(1, "draft_0"), _vote(2, "draft_1"), _vote(3, "draft_0")]
    weights = {1: 2.0, 2: 1.0, 3: 1.0}
    winner, is_tie = weighted_vote(votes, weights)
    assert winner == "draft_0"   # 3.0 vs 1.0
    assert is_tie is False


def test_weighted_vote_tie() -> None:
    votes = [_vote(1, "draft_0"), _vote(2, "draft_1")]
    weights = {1: 1.0, 2: 1.0}
    _winner, is_tie = weighted_vote(votes, weights)
    assert is_tie is True


def test_weighted_vote_default_weight() -> None:
    votes = [_vote(1, "draft_0"), _vote(2, "draft_0"), _vote(3, "draft_1")]
    winner, is_tie = weighted_vote(votes, {})   # all seats default to weight 1.0
    assert winner == "draft_0"
    assert is_tie is False


# ---------------------------------------------------------------------------
# straw_poll_unanimous
# ---------------------------------------------------------------------------

def test_straw_poll_unanimous_true() -> None:
    assert straw_poll_unanimous(["draft_0", "draft_0", "draft_0"]) is True


def test_straw_poll_unanimous_single() -> None:
    assert straw_poll_unanimous(["draft_0"]) is True


def test_straw_poll_unanimous_false() -> None:
    assert straw_poll_unanimous(["draft_0", "draft_1"]) is False
