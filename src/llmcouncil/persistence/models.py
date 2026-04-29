"""SQLAlchemy ORM models — mirrors the SQLite schema from SPECS.md §14."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    trigger = Column(String, nullable=False)          # explicit | auto_escalate | single_shot
    protocol = Column(String, nullable=False)
    max_rounds = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="running")  # running | done | error
    total_tokens_in = Column(Integer, default=0)
    total_tokens_out = Column(Integer, default=0)
    total_usd = Column(Float, default=0.0)
    terminated_by = Column(String, nullable=True)     # unanimous | round_cap | judge | error


class SeatsSnapshot(Base):
    __tablename__ = "seats_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    seat_id = Column(Integer, nullable=False)
    role = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    weight = Column(Float, default=1.0)


class TranscriptEntry(Base):
    __tablename__ = "transcript_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    round = Column(Integer, nullable=False)
    seat_id = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)             # draft | critique | vote | verdict
    content_json = Column(Text, nullable=False)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    usd = Column(Float, default=0.0)
    latency_ms = Column(Integer, default=0)
    created_at = Column(DateTime, nullable=False)


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    seat_id = Column(Integer, nullable=False)
    choice_label = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False)
    concerns_json = Column(Text, nullable=True)


class Verdict(Base):
    __tablename__ = "verdicts"

    session_id = Column(String, ForeignKey("sessions.id"), primary_key=True)
    text = Column(Text, nullable=False)
    minority_text = Column(Text, nullable=True)
    mechanism = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)


class CostLedger(Base):
    __tablename__ = "cost_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    tokens_in = Column(Integer, nullable=False)
    tokens_out = Column(Integer, nullable=False)
    usd = Column(Float, nullable=False)
    ts = Column(DateTime, nullable=False)
