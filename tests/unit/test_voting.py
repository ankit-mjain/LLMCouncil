"""Voting engine unit tests."""

from __future__ import annotations

from llmcouncil.council.voting import VotePayload, simple_majority, straw_poll_unanimous


def _vote(seat_id: int, choice: str, confidence: float = 0.8) -> VotePayload:
    return VotePayload(seat_id=seat_id, choice=choice, confidence=confidence, rationale="")


def test_simple_majority_clear_winner() -> None:
    votes = [_vote(1, "draft_0"), _vote(2, "draft_0"), _vote(3, "draft_1")]
    winner, is_tie = simple_majority(votes)
    assert winner == "draft_0"
    assert is_tie is False


def test_simple_majority_tie_broken_by_confidence() -> None:
    # 1 vote each; draft_1 has higher mean confidence → wins
    votes = [
        _vote(1, "draft_0", 0.5),
        _vote(2, "draft_1", 0.9),
    ]
    winner, is_tie = simple_majority(votes)
    assert winner == "draft_1"
    assert is_tie is False


def test_simple_majority_true_tie() -> None:
    # 1 vote each; equal confidence → is_tie=True
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


def test_straw_poll_unanimous_true() -> None:
    assert straw_poll_unanimous(["draft_0", "draft_0", "draft_0"]) is True


def test_straw_poll_unanimous_single() -> None:
    assert straw_poll_unanimous(["draft_0"]) is True


def test_straw_poll_unanimous_false() -> None:
    assert straw_poll_unanimous(["draft_0", "draft_1"]) is False
