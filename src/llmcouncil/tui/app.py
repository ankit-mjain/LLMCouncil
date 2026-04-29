"""TUI dashboard — M0 stub. Full impl in M6."""

from __future__ import annotations

from llmcouncil.config import AppConfig


class CouncilTUI:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def run(self) -> None:
        raise NotImplementedError("TUI dashboard not yet implemented (M6).")
