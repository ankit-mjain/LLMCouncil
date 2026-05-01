"""TUI event types for the in-process pubsub."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

EventKind = Literal[
    "seat_status",
    "transcript_entry",
    "cost_update",
    "round_change",
    "verdict",
    "notification",
]


@dataclass
class CouncilEvent:
    kind: EventKind
    session_id: str
    payload: dict[str, Any]
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
