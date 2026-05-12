"""Session budget tracker — raises BudgetExceededError before calls that would exceed limits."""

from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceededError(Exception):
    def __init__(self, spent: float, limit: float) -> None:
        self.spent = spent
        self.limit = limit
        super().__init__(
            f"Session budget exceeded: ${spent:.4f} spent of ${limit:.4f} limit"
        )


@dataclass
class BudgetTracker:
    per_session_usd: float
    _spent_usd: float = field(default=0.0, init=False)

    def check(self, estimated_usd: float = 0.0) -> None:
        """Raise BudgetExceededError if spending estimated_usd would meet or exceed the session limit."""
        if self._spent_usd + estimated_usd >= self.per_session_usd:
            raise BudgetExceededError(spent=self._spent_usd, limit=self.per_session_usd)

    def record(self, usd: float) -> None:
        self._spent_usd += usd

    @property
    def spent(self) -> float:
        return self._spent_usd

    @property
    def remaining(self) -> float:
        return max(0.0, self.per_session_usd - self._spent_usd)
