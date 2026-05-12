"""Tests for §26 validation metrics computation and dashboard formatting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from llmcouncil.persistence.db import init_db
from llmcouncil.persistence.models import (
    CostLedger,
    PreferencePoll,
    Session,
    ShadowRun,
    Vote,
)
from llmcouncil.validation.metrics import ValidationMetrics, compute_metrics, format_dashboard


def _make_db(tmp_path: Path):
    return init_db(tmp_path / "test.sqlite")


def _session(sid: str, days_ago: int = 0) -> Session:
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return Session(
        id=sid,
        started_at=now,
        finished_at=now,
        trigger="explicit",
        protocol="fixed",
        max_rounds=3,
        status="done",
    )


# ---------------------------------------------------------------------------
# Empty DB
# ---------------------------------------------------------------------------

def test_compute_metrics_empty_db(tmp_path: Path) -> None:
    factory = _make_db(tmp_path)
    with factory() as db:
        m = compute_metrics(db)
    assert m.council_sessions == 0
    assert m.days_logged == 0


# ---------------------------------------------------------------------------
# Sessions and days logged
# ---------------------------------------------------------------------------

def test_days_logged_from_session_dates(tmp_path: Path) -> None:
    factory = _make_db(tmp_path)
    with factory() as db:
        db.add(_session("s1", days_ago=10))
        db.add(_session("s2", days_ago=0))
        db.commit()
        m = compute_metrics(db)
    assert m.days_logged == 11  # 10-day span + 1
    assert m.council_sessions == 2


# ---------------------------------------------------------------------------
# Preference polls
# ---------------------------------------------------------------------------

def test_preference_counts(tmp_path: Path) -> None:
    factory = _make_db(tmp_path)
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(_session("s1"))
        for choice in ["council", "council", "single", "tie"]:
            db.add(PreferencePoll(asked_at=now, choice=choice))
        db.commit()
        m = compute_metrics(db)
    assert m.pref_council == 2
    assert m.pref_single == 1
    assert m.pref_tie == 1


# ---------------------------------------------------------------------------
# Disagreement rate
# ---------------------------------------------------------------------------

def test_disagreement_detected(tmp_path: Path) -> None:
    factory = _make_db(tmp_path)
    with factory() as db:
        db.add(_session("s1"))
        # Two different vote choices → dissent
        db.add(Vote(session_id="s1", seat_id=1, choice_label="A", confidence=0.8, rationale="r"))
        db.add(Vote(session_id="s1", seat_id=2, choice_label="B", confidence=0.7, rationale="r"))
        db.commit()
        m = compute_metrics(db)
    assert m.sessions_with_dissent == 1


def test_no_disagreement_when_unanimous(tmp_path: Path) -> None:
    factory = _make_db(tmp_path)
    with factory() as db:
        db.add(_session("s1"))
        db.add(Vote(session_id="s1", seat_id=1, choice_label="A", confidence=0.9, rationale="r"))
        db.add(Vote(session_id="s1", seat_id=2, choice_label="A", confidence=0.9, rationale="r"))
        db.commit()
        m = compute_metrics(db)
    assert m.sessions_with_dissent == 0


# ---------------------------------------------------------------------------
# format_dashboard
# ---------------------------------------------------------------------------

def test_format_dashboard_no_data() -> None:
    m = ValidationMetrics()
    text = format_dashboard(m)
    assert "0 days" in text
    assert "no polls yet" in text
    assert "Trigger status" in text


def test_format_dashboard_with_data() -> None:
    m = ValidationMetrics(
        days_logged=18,
        council_sessions=24,
        pref_council=13,
        pref_single=7,
        pref_tie=2,
        sessions_with_dissent=14,
        latencies_ms=[28000, 31000, 45000],
    )
    text = format_dashboard(m)
    assert "18 days" in text
    assert "24 council sessions" in text
    assert "council" in text
    assert "Disagreement" in text


def test_format_dashboard_pivot_ready_when_conditions_met() -> None:
    m = ValidationMetrics(
        days_logged=35,
        council_sessions=35,
        pref_council=10,   # 10/25 = 40% < 60% → red flag
        pref_single=15,
        pref_tie=0,
        sessions_with_dissent=10,
    )
    text = format_dashboard(m)
    assert "PIVOT READY" in text
