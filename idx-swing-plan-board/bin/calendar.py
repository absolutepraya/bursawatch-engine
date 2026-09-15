"""Reviewed IDX trading-session calendar."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path


class CalendarCoverageError(RuntimeError):
    """Raised instead of treating an unreviewed weekday as an open session."""


_HOLIDAYS_PATH = Path(__file__).with_name("idx_trading_holidays.json")
HOLIDAYS_BY_YEAR: dict[str, set[str]] = {
    year: set(days) for year, days in json.loads(_HOLIDAYS_PATH.read_text()).items()
}


def is_idx_trading_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    try:
        holidays = HOLIDAYS_BY_YEAR[str(day.year)]
    except KeyError as exc:
        raise CalendarCoverageError(f"IDX holiday calendar is missing {day.year}") from exc
    return day.isoformat() not in holidays


def sessions_ago(anchor: date, count: int) -> date:
    if count < 0:
        raise ValueError("count must be non-negative")
    current = anchor
    remaining = count
    while remaining:
        current -= timedelta(days=1)
        if is_idx_trading_day(current):
            remaining -= 1
    return current
