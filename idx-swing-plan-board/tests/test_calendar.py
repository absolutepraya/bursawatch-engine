from datetime import date
import sys

import pytest

from calendar import CalendarCoverageError, is_idx_trading_day, sessions_ago
from models import MarketState


def test_stdlib_calendar_loader_registers_its_module_name() -> None:
    assert "_idx_swing_stdlib_calendar" in sys.modules
    assert sys.modules["_idx_swing_stdlib_calendar"].month_name[1] == "January"


def test_calendar_skips_official_closures_and_counts_sessions() -> None:
    assert is_idx_trading_day(date(2026, 3, 19)) is False
    assert is_idx_trading_day(date(2026, 3, 25)) is True
    assert sessions_ago(date(2026, 3, 25), 1) == date(2026, 3, 17)
    assert MarketState.TP3_REACHED.value == "TP3 reached"


def test_calendar_fails_closed_for_uncovered_weekday_years() -> None:
    with pytest.raises(CalendarCoverageError, match="missing 2027"):
        is_idx_trading_day(date(2027, 1, 4))
    assert is_idx_trading_day(date(2027, 1, 2)) is False


def test_sessions_ago_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        sessions_ago(date(2026, 3, 25), -1)
