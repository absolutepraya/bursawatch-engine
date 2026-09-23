from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    latest_price: float
    one_day_change: float | None
    one_day_percent: float | None
    one_week_change: float | None
    one_week_percent: float | None
    one_month_change: float | None
    one_month_percent: float | None
    three_month_change: float | None
    three_month_percent: float | None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _change(latest: float, earlier: float | None) -> tuple[float | None, float | None]:
    if earlier is None or earlier <= 0:
        return None, None
    return latest - earlier, ((latest / earlier) - 1) * 100


def get_market_snapshot(ticker: str) -> MarketSnapshot | None:
    """Return a nonzero IDX snapshot, or None when Yahoo has no usable data."""
    try:
        import yfinance as yf

        quote = yf.Ticker(f"{ticker}.JK")
        history = quote.history(period="1y", interval="1d", auto_adjust=False, raise_errors=True)
        closes = [
            value
            for value in (_number(item) for item in history.get("Close", []))
            if value is not None and value > 0
        ]
        if len(closes) < 6:
            return None
        fast_info = quote.fast_info
        latest = _number(fast_info.get("last_price")) or closes[-1]
        previous = _number(fast_info.get("previous_close")) or closes[-2]
        if latest <= 0 or previous <= 0:
            return None
        one_day = _change(latest, previous)
        one_week = _change(latest, closes[-6])
        one_month = _change(latest, closes[-23] if len(closes) >= 23 else None)
        three_month = _change(latest, closes[-67] if len(closes) >= 67 else None)
        return MarketSnapshot(
            latest_price=latest,
            one_day_change=one_day[0],
            one_day_percent=one_day[1],
            one_week_change=one_week[0],
            one_week_percent=one_week[1],
            one_month_change=one_month[0],
            one_month_percent=one_month[1],
            three_month_change=three_month[0],
            three_month_percent=three_month[1],
        )
    except Exception:
        return None
