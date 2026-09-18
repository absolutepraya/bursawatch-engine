from datetime import date
import sys

import pytest

from calendar import is_idx_trading_day, sessions_ago
from models import MarketState


def test_stdlib_calendar_loader_registers_its_module_name() -> None:
    assert "_idx_swing_stdlib_calendar" in sys.modules
    assert sys.modules["_idx_swing_stdlib_calendar"].month_name[1] == "January"


def test_calendar_is_intentionally_weekday_only_and_counts_weekdays() -> None:
    assert is_idx_trading_day(date(2026, 3, 19)) is True
    assert is_idx_trading_day(date(2026, 3, 25)) is True
    assert sessions_ago(date(2026, 3, 25), 1) == date(2026, 3, 24)
    assert MarketState.TP3_REACHED.value == "TP3 reached"


def test_calendar_never_requires_year_specific_holiday_coverage() -> None:
    assert is_idx_trading_day(date(2027, 1, 4)) is True
    assert is_idx_trading_day(date(2027, 1, 2)) is False


def test_sessions_ago_rejects_negative_counts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        sessions_ago(date(2026, 3, 25), -1)
