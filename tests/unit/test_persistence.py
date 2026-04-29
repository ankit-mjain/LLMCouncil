"""Persistence layer — SQLAlchemy model and DB init tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from llmcouncil.persistence.db import init_db
from llmcouncil.persistence.models import (
    Base,
    CostLedger,
    Session,
    SeatsSnapshot,
    TranscriptEntry,
    Verdict,
    Vote,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_session():  # type: ignore[no-untyped-def]
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        yield session


def test_init_db_creates_file(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite"
    factory = init_db(db_path)
    assert db_path.exists()
    with factory() as session:
        assert session is not None


def test_session_round_trip(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rec = Session(
        id="sess-1",
        started_at=now,
        trigger="explicit",
        protocol="fixed",
        max_rounds=3,
        status="done",
        terminated_by="unanimous",
    )
    db_session.add(rec)
    db_session.commit()

    loaded = db_session.get(Session, "sess-1")
    assert loaded is not None
    assert loaded.protocol == "fixed"
    assert loaded.terminated_by == "unanimous"


def test_transcript_entry(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(Session(
        id="sess-2", started_at=now, trigger="explicit",
        protocol="fixed", max_rounds=3, status="done",
    ))
    db_session.add(TranscriptEntry(
        session_id="sess-2", round=0, seat_id=1, kind="draft",
        content_json='{"text": "hello"}', created_at=now,
        tokens_in=10, tokens_out=20, usd=0.001, latency_ms=500,
    ))
    db_session.commit()

    entries = db_session.query(TranscriptEntry).filter_by(session_id="sess-2").all()
    assert len(entries) == 1
    assert entries[0].kind == "draft"


def test_verdict_and_votes(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(Session(
        id="sess-3", started_at=now, trigger="explicit",
        protocol="fixed", max_rounds=3, status="done",
    ))
    db_session.add(Vote(
        session_id="sess-3", seat_id=2, choice_label="draft_0",
        confidence=0.85, rationale="Best answer",
    ))
    db_session.add(Verdict(
        session_id="sess-3", text="[Verdict]\nThe answer.",
        minority_text=None, mechanism="simple_majority", created_at=now,
    ))
    db_session.commit()

    v = db_session.get(Verdict, "sess-3")
    assert v is not None
    assert v.mechanism == "simple_majority"


def test_cost_ledger(db_session) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(CostLedger(
        session_id=None, provider="anthropic", model="claude-haiku-4-5",
        tokens_in=100, tokens_out=50, usd=0.002, ts=now,
    ))
    db_session.commit()

    rows = db_session.query(CostLedger).all()
    assert len(rows) == 1
    assert rows[0].provider == "anthropic"
