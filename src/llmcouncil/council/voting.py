"""Voting engine — all mechanisms and straw-poll unanimity detection."""

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
    rankings: list[str] = field(default_factory=list)


def simple_majority(votes: list[VotePayload]) -> tuple[str, bool]:
    """Most-voted draft wins. Mean-confidence tie-break; is_tie=True if still equal."""
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


def supermajority(
    votes: list[VotePayload], threshold: float = 2 / 3
) -> tuple[str, bool]:
    """Requires ≥ threshold fraction of votes; is_tie=True if no draft qualifies."""
    tally: Counter[str] = Counter(v.choice for v in votes)
    total = len(votes)
    required = total * threshold

    qualifying = [(d, c) for d, c in tally.most_common() if c >= required]
    if qualifying:
        if len(qualifying) == 1:
            return qualifying[0][0], False
        by_conf: dict[str, list[float]] = {}
        for v in votes:
            by_conf.setdefault(v.choice, []).append(v.confidence)
        mean_conf = {d: sum(cs) / len(cs) for d, cs in by_conf.items()}
        winner = max(qualifying, key=lambda x: (x[1], mean_conf.get(x[0], 0.0)))[0]
        return winner, False

    # No draft reached the supermajority threshold — signal tie-break needed.
    winner, _ = simple_majority(votes)
    return winner, True


def ranked_choice(votes: list[VotePayload]) -> tuple[str, bool]:
    """Instant-runoff using VotePayload.rankings; falls back to .choice when empty."""
    all_candidates: set[str] = set()
    ballots: list[list[str]] = []
    for v in votes:
        prefs = v.rankings if v.rankings else [v.choice]
        ballots.append(prefs)
        all_candidates.update(prefs)

    candidates = set(all_candidates)

    while True:
        tally: Counter[str] = Counter()
        for ballot in ballots:
            for pref in ballot:
                if pref in candidates:
                    tally[pref] += 1
                    break

        if not tally:
            return sorted(candidates)[0], False

        total = sum(tally.values())
        top, top_count = tally.most_common(1)[0]

        if top_count > total / 2:
            return top, False

        if len(candidates) == 1:
            return top, False

        if len(candidates) == 2:
            ranked_all = tally.most_common()
            if ranked_all[0][1] == ranked_all[1][1]:
                return ranked_all[0][0], True
            return ranked_all[0][0], False

        min_count = min(tally.values())
        last_place = [d for d, c in tally.items() if c == min_count]
        # Eliminate exactly one per round; break last-place ties by label (last label out first).
        candidates -= {max(last_place)}


def weighted_vote(
    votes: list[VotePayload], seat_weights: dict[int, float]
) -> tuple[str, bool]:
    """Sum of per-seat weights per draft; is_tie=True if top two totals are equal."""
    totals: dict[str, float] = {}
    for v in votes:
        w = seat_weights.get(v.seat_id, 1.0)
        totals[v.choice] = totals.get(v.choice, 0.0) + w

    if not totals:
        return "draft_0", True

    sorted_drafts = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_drafts) >= 2 and abs(sorted_drafts[0][1] - sorted_drafts[1][1]) < 1e-9:
        return sorted_drafts[0][0], True
    return sorted_drafts[0][0], False


def straw_poll_unanimous(choices: list[str]) -> bool:
    """True when all non-proposer seats would back the same draft."""
    return len(set(choices)) <= 1
