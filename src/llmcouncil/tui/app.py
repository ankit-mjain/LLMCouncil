"""TUI dashboard — M5 notification layer. Full Textual impl in M6."""

from __future__ import annotations

from llmcouncil.config import AppConfig


class CouncilTUI:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self._notifications: list[tuple[str, str]] = []  # (kind, message)

    def notify(self, kind: str, message: str) -> None:
        """Record a notification for display (escalation, memory_recall, search, etc.)."""
        self._notifications.append((kind, message))

    def get_notifications(self) -> list[tuple[str, str]]:
        return list(self._notifications)

    def run(self) -> None:
        raise NotImplementedError("TUI dashboard not yet implemented (M6).")
