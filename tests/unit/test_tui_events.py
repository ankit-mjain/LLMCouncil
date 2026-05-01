"""EventBus and CouncilEvent unit tests."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from llmcouncil.tui.events import CouncilEvent
from llmcouncil.tui.pubsub import EventBus


def _evt(kind: str = "notification", session: str = "s1") -> CouncilEvent:
    return CouncilEvent(kind=kind, session_id=session, payload={"msg": "hello"})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CouncilEvent
# ---------------------------------------------------------------------------

def test_council_event_ts_set_automatically() -> None:
    evt = _evt()
    assert isinstance(evt.ts, datetime)


def test_council_event_payload_stored() -> None:
    evt = CouncilEvent(kind="verdict", session_id="abc", payload={"text": "done"})  # type: ignore[arg-type]
    assert evt.payload["text"] == "done"
    assert evt.session_id == "abc"


# ---------------------------------------------------------------------------
# EventBus — synchronous operations
# ---------------------------------------------------------------------------

def test_event_bus_starts_empty() -> None:
    bus = EventBus()
    assert bus.size == 0


def test_event_bus_emit_increments_size() -> None:
    bus = EventBus()
    bus.emit(_evt())
    assert bus.size == 1


def test_event_bus_drain_returns_all_events() -> None:
    bus = EventBus()
    bus.emit(_evt("round_change"))
    bus.emit(_evt("transcript_entry"))
    bus.emit(_evt("verdict"))
    drained = bus.drain()
    assert len(drained) == 3
    assert bus.size == 0


def test_event_bus_drain_empty_returns_empty_list() -> None:
    bus = EventBus()
    assert bus.drain() == []


def test_event_bus_get_nowait_none_when_empty() -> None:
    bus = EventBus()
    assert bus.get_nowait() is None


def test_event_bus_get_nowait_returns_event() -> None:
    bus = EventBus()
    evt = _evt()
    bus.emit(evt)
    result = bus.get_nowait()
    assert result is evt
    assert bus.size == 0


# ---------------------------------------------------------------------------
# EventBus — async get
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_bus_async_get() -> None:
    bus = EventBus()
    evt = _evt("cost_update")
    bus.emit(evt)
    result = await asyncio.wait_for(bus.get(), timeout=1.0)
    assert result is evt
