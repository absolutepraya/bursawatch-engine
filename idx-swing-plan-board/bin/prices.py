"""Strict Yahoo closing-price intake and factual Swing-plan classification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re
from zoneinfo import ZoneInfo

import yfinance as yf

from models import MarketState


WIB = ZoneInfo("Asia/Jakarta")
_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{3})*")
_LEVEL = re.compile(
    rf"^(?:(?P<operator><=|>=|<|>)\s*)?(?P<first>{_INTEGER.pattern})(?:\s+to\s+(?P<second>{_INTEGER.pattern}))?$"
)


@dataclass(frozen=True)
class ParsedLevel:
    """One source-written level and its exact comparison semantics."""

    operator: str | None
    lower_bound: Decimal
    upper_bound: Decimal | None = None

    def contains(self, value: Decimal) -> bool:
        if self.upper_bound is not None:
            return self.lower_bound <= value <= self.upper_bound
        if self.operator == "<":
            return value < self.lower_bound
        if self.operator == "<=":
            return value <= self.lower_bound
        if self.operator == ">":
            return value > self.lower_bound
        if self.operator == ">=":
            return value >= self.lower_bound
        return value == self.lower_bound

    def is_breached_by(self, value: Decimal) -> bool:
        """Use the source comparator literally, with a bare stop as ``<=``."""
        if self.upper_bound is not None:
            return self.contains(value)
        if self.operator == "<":
            return value < self.lower_bound
        if self.operator in {None, "<="}:
            return value <= self.lower_bound
        if self.operator == ">":
            return value > self.lower_bound
        return value >= self.lower_bound

    def is_reached_by(self, value: Decimal) -> bool:
        """A range target is reached at its lower edge; comparators stay literal."""
        if self.upper_bound is not None or self.operator is None:
            return value >= self.lower_bound
        if self.operator == ">":
            return value > self.lower_bound
        if self.operator == ">=":
            return value >= self.lower_bound
        if self.operator == "<":
            return value < self.lower_bound
        return value <= self.lower_bound


@dataclass(frozen=True)
class ParsedPlanLevels:
    entry: ParsedLevel
    stop_loss: ParsedLevel
    targets: tuple[ParsedLevel, ...]


def parse_plan_levels(
    entry: str, stop_loss: str, targets: Sequence[str]
) -> ParsedPlanLevels:
    """Parse only the small, source-approved integer grammar used by the board."""
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)) or not targets:
        raise ValueError("targets must be a non-empty sequence")
    return ParsedPlanLevels(
        entry=_parse_level(entry, "entry"),
        stop_loss=_parse_level(stop_loss, "stop_loss"),
        targets=tuple(_parse_level(target, "target") for target in targets),
    )


def classify_close(close: Decimal, levels: ParsedPlanLevels) -> MarketState:
    """Label an observed close, never an inferred price or trading instruction."""
    if not isinstance(close, Decimal) or not close.is_finite():
        raise ValueError("close must be a finite Decimal")
    if levels.stop_loss.is_breached_by(close):
        return MarketState.STOP_LOSS_BREACHED
    reached = [
        number
        for number, target in enumerate(levels.targets, start=1)
        if target.is_reached_by(close)
    ]
    if reached:
        return MarketState.from_target_number(min(max(reached), 5))
    if levels.entry.contains(close):
        return MarketState.ENTRY_ZONE
    if close < levels.entry.lower_bound:
        return MarketState.BELOW_ENTRY
    return MarketState.ABOVE_ENTRY


def _history(symbol: str):
    return yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)


def fetch_session_close(ticker: str, session_date: date) -> Decimal | None:
    """Return Yahoo's final valid bar only when it belongs to this IDX session."""
    if not isinstance(ticker, str) or not ticker or not isinstance(session_date, date):
        raise ValueError("ticker and session_date are required")
    try:
        history = _history(f"{ticker.upper()}.JK")
        if history is None or history.empty or "Close" not in history:
            return None
        closes = history["Close"].dropna()
        if closes.empty:
            return None
        timestamp = closes.index[-1]
        bar_day = _bar_date(timestamp)
        if bar_day != session_date:
            return None
        close = _decimal_close(closes.iloc[-1])
        return close
    except Exception:
        return None


def _parse_level(value: str, name: str) -> ParsedLevel:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    match = _LEVEL.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"{name} must be a bare integer, comparator, or range")
    operator = match.group("operator")
    second = match.group("second")
    if second is not None and operator is not None:
        raise ValueError(f"{name} cannot combine a comparator and range")
    first_value = _integer(match.group("first"))
    if first_value <= 0:
        raise ValueError(f"{name} must be positive")
    if second is None:
        return ParsedLevel(operator, first_value)
    second_value = _integer(second)
    if second_value <= 0 or second_value < first_value:
        raise ValueError(f"{name} range is invalid")
    return ParsedLevel(None, first_value, second_value)


def _integer(token: str) -> Decimal:
    # Periods are the reviewed Indonesian group separator, never a decimal point.
    return Decimal(token.replace(".", ""))


def _bar_date(timestamp: object) -> date:
    # pandas Timestamp accepts both naive and timezone-aware Yahoo indices.
    if hasattr(timestamp, "tzinfo") and getattr(timestamp, "tzinfo") is not None:
        return timestamp.tz_convert(WIB).date()  # type: ignore[union-attr]
    return timestamp.date()  # type: ignore[union-attr]


def _decimal_close(value: object) -> Decimal | None:
    try:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        close = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not close.is_finite() or close <= 0:
        return None
    return close
