"""Session budget tracker — raises BudgetExceededError before calls that would exceed limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


class BudgetExceededError(Exception):
    def __init__(self, spent: float, limit: float) -> None:
        self.spent = spent
        self.limit = limit
        super().__init__(
            f"Session budget exceeded: ${spent:.4f} spent of ${limit:.4f} limit"
        )


class DailyBudgetExceededError(Exception):
    def __init__(self, spent: float, limit: float) -> None:
        self.spent = spent
        self.limit = limit
        super().__init__(
            f"Daily budget exceeded: ${spent:.4f} spent of ${limit:.4f} daily limit"
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


# ---------------------------------------------------------------------------
# Daily spend tracker — module-level, resets automatically at midnight.
# In-memory only; resets on process restart. Provides a lightweight guard
# without requiring DB access in the hot path.
# ---------------------------------------------------------------------------

_daily_spent: float = 0.0
_daily_date: str = ""  # ISO date string of the last reset


def check_daily_budget(per_day_usd: float) -> None:
    """Raise DailyBudgetExceededError if today's accumulated spend meets or exceeds per_day_usd."""
    _reset_if_new_day()
    if _daily_spent >= per_day_usd:
        raise DailyBudgetExceededError(spent=_daily_spent, limit=per_day_usd)


def record_daily_spend(usd: float) -> None:
    """Add usd to today's accumulated daily spend."""
    global _daily_spent
    _reset_if_new_day()
    _daily_spent += usd


def get_daily_spent() -> float:
    """Return today's accumulated spend (for display/testing)."""
    _reset_if_new_day()
    return _daily_spent


def _reset_if_new_day() -> None:
    global _daily_spent, _daily_date
    today = date.today().isoformat()
    if _daily_date != today:
        _daily_spent = 0.0
        _daily_date = today
