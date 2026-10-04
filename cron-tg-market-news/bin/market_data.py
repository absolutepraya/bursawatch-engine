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
import re


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    company_name: str
    latest_price: float
    one_day_change: float
    one_day_percent: float
    one_week_change: float
    one_week_percent: float
    one_month_change: float | None = None
    one_month_percent: float | None = None
    three_month_change: float | None = None
    three_month_percent: float | None = None
    as_of: str | None = None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fallback_company_name(ticker: str, source_text: str) -> str:
    """Return the most complete issuer name available in provider text."""
    escaped = re.escape(ticker)
    legal_name = re.compile(
        r"(?P<name>PT\s+[A-Za-z0-9][A-Za-z0-9.,&'’/ -]*?"
        r"(?:\s+\(Persero\))?\s+Tbk\.?)\b",
        re.IGNORECASE,
    )
    patterns = (
        rf"\b{escaped}\s*\(([^)]+)\)",
        rf"\b([^\n()]+?)\s*\({escaped}\)",
    )

    for pattern in patterns:
        match = re.search(pattern, source_text, flags=re.IGNORECASE)
        if match:
            parenthetical = " ".join(match.group(1).split()).strip(" -:|")
            legal_match = legal_name.search(parenthetical)
            if legal_match:
                return " ".join(legal_match.group("name").split()).strip(" -:|")

    legal_match = legal_name.search(source_text)
    if legal_match:
        return " ".join(legal_match.group("name").split()).strip(" -:|")

    for pattern in patterns:
        match = re.search(pattern, source_text, flags=re.IGNORECASE)
        if match:
            name = " ".join(match.group(1).split()).strip(" -:|")
            if name:
                return name
    return ticker


def get_market_snapshot(ticker: str, source_text: str) -> MarketSnapshot | None:
    snapshot = news_format.get_market_snapshot(ticker)
    if snapshot is None:
        return None
    return MarketSnapshot(company_name=fallback_company_name(ticker, source_text), **{key: snapshot[key] for key in MarketSnapshot.__dataclass_fields__ if key != "company_name"})
