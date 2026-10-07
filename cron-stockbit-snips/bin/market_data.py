from __future__ import annotations

from pathlib import Path as _NewsPath
import sys as _news_sys
_news_bin = _NewsPath(__file__).resolve().parents[2] / "lib-news-format" / "bin"
if not _news_bin.is_dir():
    _news_bin = _NewsPath.home() / ".agents/skills/lib-news-format/bin"
if str(_news_bin) not in _news_sys.path:
    _news_sys.path.insert(0, str(_news_bin))
import news_format

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
    as_of: str | None = None


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
    snapshot = news_format.get_market_snapshot(ticker)
    if snapshot is None:
        return None
    return MarketSnapshot(**{key: snapshot[key] for key in MarketSnapshot.__dataclass_fields__})


def get_company_context(ticker: str, route: str):
    """Optional analyst and company context; any provider failure leaves the card unchanged."""
    try:
        return news_format.get_company_context(ticker, route)
    except Exception:
        return None
