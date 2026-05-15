"""BudgetTracker unit tests."""

from __future__ import annotations

import pytest

from llmcouncil.council.budget import (
    BudgetExceededError,
    BudgetTracker,
    DailyBudgetExceededError,
    check_daily_budget,
    get_daily_spent,
    record_daily_spend,
    _reset_if_new_day,
)


def test_budget_initial_state() -> None:
    tracker = BudgetTracker(per_session_usd=1.0)
    assert tracker.spent == 0.0
    assert tracker.remaining == 1.0


def test_budget_record_and_remaining() -> None:
    tracker = BudgetTracker(per_session_usd=1.0)
    tracker.record(0.30)
    assert pytest.approx(tracker.spent) == 0.30
    assert pytest.approx(tracker.remaining) == 0.70


def test_budget_check_within_limit() -> None:
    tracker = BudgetTracker(per_session_usd=1.0)
    tracker.record(0.40)
    tracker.check(0.50)  # 0.40 + 0.50 = 0.90 ≤ 1.0, should not raise


def test_budget_check_exceeds_limit() -> None:
    tracker = BudgetTracker(per_session_usd=1.0)
    tracker.record(0.80)
    with pytest.raises(BudgetExceededError) as exc_info:
        tracker.check(0.30)  # 0.80 + 0.30 = 1.10 > 1.0
    assert exc_info.value.spent == pytest.approx(0.80)
    assert exc_info.value.limit == pytest.approx(1.0)


def test_budget_check_no_estimate() -> None:
    tracker = BudgetTracker(per_session_usd=0.01)
    tracker.record(0.01)
    with pytest.raises(BudgetExceededError):
        tracker.check()  # spent == limit, any additional call exceeds


def test_budget_remaining_never_negative() -> None:
    tracker = BudgetTracker(per_session_usd=0.50)
    tracker.record(1.00)  # over-spend (recorded after the fact)
    assert tracker.remaining == 0.0


def test_budget_exceeded_error_message() -> None:
    err = BudgetExceededError(spent=0.45, limit=0.50)
    assert "0.4500" in str(err)
    assert "0.5000" in str(err)


def test_budget_multiple_records() -> None:
    tracker = BudgetTracker(per_session_usd=2.0)
    for _ in range(5):
        tracker.record(0.30)
    assert pytest.approx(tracker.spent) == 1.50
    assert pytest.approx(tracker.remaining) == 0.50


# ---------------------------------------------------------------------------
# Daily budget tracker (MED-003)
# ---------------------------------------------------------------------------

def _reset_daily() -> None:
    """Force-reset the module-level daily accumulator for test isolation."""
    import llmcouncil.council.budget as _bmod
    _bmod._daily_spent = 0.0
    _bmod._daily_date = ""


def test_daily_budget_check_within_limit() -> None:
    _reset_daily()
    record_daily_spend(1.00)
    check_daily_budget(5.00)  # should not raise


def test_daily_budget_check_exceeds_limit() -> None:
    _reset_daily()
    record_daily_spend(4.00)
    record_daily_spend(1.50)
    with pytest.raises(DailyBudgetExceededError) as exc_info:
        check_daily_budget(5.00)
    assert exc_info.value.spent == pytest.approx(5.50)
    assert exc_info.value.limit == pytest.approx(5.00)


def test_daily_budget_accumulates_across_records() -> None:
    _reset_daily()
    for _ in range(3):
        record_daily_spend(0.50)
    assert get_daily_spent() == pytest.approx(1.50)


def test_daily_budget_resets_on_new_day(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_daily()
    record_daily_spend(4.00)
    import llmcouncil.council.budget as _bmod
    from datetime import date
    monkeypatch.setattr(_bmod, "_daily_date", "1970-01-01")
    assert get_daily_spent() == pytest.approx(0.0)


def test_daily_budget_exceeded_error_message() -> None:
    err = DailyBudgetExceededError(spent=5.50, limit=5.00)
    assert "5.5000" in str(err)
    assert "5.0000" in str(err)
