"""Reviewed IDX trading-session calendar."""

from __future__ import annotations

from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import sys
import sysconfig


# This deterministic owner intentionally has a local ``calendar`` module.
# Third-party Yahoo/pandas imports also require stdlib calendar helpers while
# this module is on ``sys.path``. Re-export those helpers under their canonical
# names before adding the IDX-only API below.
_STDLIB_CALENDAR_NAME = "_idx_swing_stdlib_calendar"
_stdlib_calendar_spec = importlib.util.spec_from_file_location(
    _STDLIB_CALENDAR_NAME, Path(sysconfig.get_path("stdlib")) / "calendar.py"
)
if _stdlib_calendar_spec is None or _stdlib_calendar_spec.loader is None:
    raise RuntimeError("stdlib calendar module is unavailable")
_stdlib_calendar = importlib.util.module_from_spec(_stdlib_calendar_spec)
sys.modules[_STDLIB_CALENDAR_NAME] = _stdlib_calendar
try:
    _stdlib_calendar_spec.loader.exec_module(_stdlib_calendar)
except BaseException:
    sys.modules.pop(_STDLIB_CALENDAR_NAME, None)
    raise
for _name in dir(_stdlib_calendar):
    if not _name.startswith("_"):
        globals().setdefault(_name, getattr(_stdlib_calendar, _name))


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
