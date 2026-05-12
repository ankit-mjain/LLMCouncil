"""Compute §26.3 validation metrics and render the §26.5 dashboard."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession


@dataclass
class ValidationMetrics:
    days_logged: int = 0
    council_sessions: int = 0
    # A/B preference counts
    pref_council: int = 0
    pref_single: int = 0
    pref_tie: int = 0
    pref_skip: int = 0
    # Shadow cost
    shadow_run_count: int = 0
    council_cost_total: float = 0.0
    shadow_cost_total: float = 0.0
    # Latency (ms) per verdict entry
    latencies_ms: list[int] = field(default_factory=list)
    # Disagreement
    sessions_with_dissent: int = 0


def compute_metrics(db: "DBSession") -> ValidationMetrics:
    """Read all validation tables and return a populated ValidationMetrics."""
    from llmcouncil.persistence.models import (
        CostLedger,
        PreferencePoll,
        Session,
        ShadowRun,
        TranscriptEntry,
        Vote,
    )

    m = ValidationMetrics()

    sessions = db.query(Session).filter(Session.status == "done").all()
    m.council_sessions = len(sessions)
    if not sessions:
        return m

    dates = [s.started_at for s in sessions if s.started_at]
    if dates:
        m.days_logged = (max(dates) - min(dates)).days + 1

    polls = db.query(PreferencePoll).filter(PreferencePoll.choice.isnot(None)).all()
    for p in polls:
        if p.choice == "council":
            m.pref_council += 1
        elif p.choice == "single":
            m.pref_single += 1
        elif p.choice == "tie":
            m.pref_tie += 1
        else:
            m.pref_skip += 1

    session_ids = [s.id for s in sessions]
    ledger = db.query(CostLedger).filter(CostLedger.session_id.in_(session_ids)).all()
    m.council_cost_total = sum(r.usd for r in ledger)

    shadow_runs = db.query(ShadowRun).all()
    m.shadow_run_count = len(shadow_runs)
    m.shadow_cost_total = sum(r.usd for r in shadow_runs)

    verdict_entries = (
        db.query(TranscriptEntry)
        .filter(
            TranscriptEntry.session_id.in_(session_ids),
            TranscriptEntry.kind == "verdict",
        )
        .all()
    )
    m.latencies_ms = [e.latency_ms for e in verdict_entries if e.latency_ms]

    for sid in session_ids:
        votes = db.query(Vote).filter(Vote.session_id == sid).all()
        if len({v.choice_label for v in votes}) >= 2:
            m.sessions_with_dissent += 1

    return m


def format_dashboard(m: ValidationMetrics) -> str:
    """Render §26.5 validation dashboard as a plain-text string."""
    lines: list[str] = [
        f"LLMCouncil Validation — {m.days_logged} days in, {m.council_sessions} council sessions logged",
        "",
    ]

    total_polls = m.pref_council + m.pref_single + m.pref_tie
    if total_polls:
        pct_c = int(100 * m.pref_council / total_polls)
        pct_s = int(100 * m.pref_single / total_polls)
        pct_t = int(100 * m.pref_tie / total_polls)
        lines.append(
            f"A/B preference         council {pct_c}%  single {pct_s}%  tie {pct_t}%"
            f"   (n={total_polls})"
        )
    else:
        lines.append("A/B preference         no polls yet")

    if m.latencies_ms:
        sorted_lat = sorted(m.latencies_ms)
        p50 = statistics.median(sorted_lat) / 1000
        p95 = sorted_lat[min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)] / 1000
        lines.append(f"Latency P50 / P95      {p50:.0f} s / {p95:.0f} s   (target 30 / 75)")
    else:
        lines.append("Latency P50 / P95      no data yet")

    satisfactory = m.pref_council  # user chose council = satisfied
    if satisfactory and m.council_cost_total:
        c_per = m.council_cost_total / satisfactory
        lines.append(f"Cost / satisfactory    ${c_per:.4f} council")
    else:
        lines.append("Cost / satisfactory    no data yet")

    disagree_pct = (
        int(100 * m.sessions_with_dissent / m.council_sessions)
        if m.council_sessions else 0
    )
    lines.append(
        f"Disagreement rate      {m.sessions_with_dissent} / {m.council_sessions} sessions"
        f" had ≥1 dissenting vote  ({disagree_pct}%)"
    )

    # Trigger evaluation
    days_ok = m.days_logged >= 30 and m.council_sessions >= 30

    pref_flag = False
    if total_polls:
        pref_flag = (m.pref_council / total_polls) < 0.60

    cost_flag = False
    if m.shadow_run_count and m.shadow_cost_total and satisfactory:
        c_per = m.council_cost_total / satisfactory
        s_per = m.shadow_cost_total / m.shadow_run_count
        cost_flag = c_per > 2 * s_per

    disagree_flag = m.council_sessions > 0 and (m.sessions_with_dissent / m.council_sessions) < 0.20

    lines += [
        "",
        "Trigger status:",
        f"  {'✓' if days_ok else '✗'} days ≥ 30 and sessions ≥ 30"
        f" ({m.days_logged}d / {m.council_sessions} sessions)",
        f"  {'⚠' if pref_flag else '✓'} A/B preference"
        + (" < 60% (red flag)" if pref_flag else " ≥ 60%"),
        f"  {'⚠' if cost_flag else '✓'} cost ratio"
        + (" > 2× (red flag)" if cost_flag else " ≤ 2×"),
        f"  {'⚠' if disagree_flag else '✓'} disagreement rate"
        + (" < 20% (red flag)" if disagree_flag else " ≥ 20%"),
    ]

    red_flags = sum([pref_flag, cost_flag, disagree_flag])
    pivot_met = days_ok and red_flags >= 1
    lines.append(
        f"→ {'PIVOT READY' if pivot_met else 'continue v1'}"
        f" (days {'✓' if days_ok else '✗'}, {red_flags} red flag(s))"
    )

    return "\n".join(lines)
