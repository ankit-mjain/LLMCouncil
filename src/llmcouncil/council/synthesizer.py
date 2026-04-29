"""Verdict renderer — implements the §11.5 template."""

from __future__ import annotations

from llmcouncil.council.voting import VotePayload


def render_verdict(
    winning_draft_text: str,
    mechanism: str,
    winning_votes: int,
    total_votes: int,
    votes: list[VotePayload],
    include_minority: bool,
    minority_concerns: list[str],
) -> tuple[str, str | None]:
    confidences = [v.confidence for v in votes]
    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    min_conf = min(confidences) if confidences else 0.0
    max_conf = max(confidences) if confidences else 0.0

    verdict = (
        f"[Verdict]\n{winning_draft_text}\n\n"
        f"[Council notes]\n"
        f"- Mechanism: {mechanism} ({winning_votes} of {total_votes} seats)\n"
        f"- Confidence: mean={mean_conf:.2f} (range {min_conf:.1f}–{max_conf:.1f})"
    )

    minority: str | None = None
    if include_minority and minority_concerns:
        minority = "\n".join(f"- {c}" for c in minority_concerns)
        verdict += f"\n\n[Minority view]\n{minority}"

    return verdict, minority
