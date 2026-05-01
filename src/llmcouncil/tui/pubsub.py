"""In-process event bus for streaming council events to the TUI."""

from __future__ import annotations

import asyncio

from llmcouncil.tui.events import CouncilEvent


class EventBus:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[CouncilEvent] = asyncio.Queue()

    def emit(self, event: CouncilEvent) -> None:
        self._queue.put_nowait(event)

    async def get(self) -> CouncilEvent:
        return await self._queue.get()

    def get_nowait(self) -> CouncilEvent | None:
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    def drain(self) -> list[CouncilEvent]:
        events: list[CouncilEvent] = []
        while True:
            event = self.get_nowait()
            if event is None:
                break
            events.append(event)
        return events

    @property
    def size(self) -> int:
        return self._queue.qsize()
