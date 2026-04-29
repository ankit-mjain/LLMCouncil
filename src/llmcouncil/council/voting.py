"""Voting engine — simple majority and unanimity detection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class VotePayload:
    seat_id: int
    choice: str
    confidence: float
    rationale: str
    concerns: list[str] = field(default_factory=list)


def simple_majority(votes: list[VotePayload]) -> tuple[str, bool]:
    """Return (winning_draft_label, is_tie).

    Tie-breaking: mean confidence among supporters. If still equal, is_tie=True
    and caller must apply the configured tie-break rule.
    """
    tally: Counter[str] = Counter(v.choice for v in votes)
    ranked = tally.most_common()

    if len(ranked) >= 2 and ranked[0][1] == ranked[1][1]:
        top_count = ranked[0][1]
        tied = [d for d, c in ranked if c == top_count]

        by_draft: dict[str, list[float]] = {}
        for v in votes:
            by_draft.setdefault(v.choice, []).append(v.confidence)
        mean_conf = {d: sum(cs) / len(cs) for d, cs in by_draft.items()}

        winner = max(tied, key=lambda d: mean_conf.get(d, 0.0))
        conf_values = [mean_conf.get(d, 0.0) for d in tied]
        still_tied = len(set(conf_values)) == 1
        return winner, still_tied

    return ranked[0][0], False


def straw_poll_unanimous(choices: list[str]) -> bool:
    """True when all non-proposer seats would back the same draft."""
    return len(set(choices)) <= 1
