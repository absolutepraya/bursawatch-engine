from __future__ import annotations

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
    """Fetch one IDX quote from Yahoo Finance. A failure is intentionally non-fatal."""
    try:
        import yfinance as yf

        quote = yf.Ticker(f"{ticker}.JK")
        history = quote.history(period="1y", interval="1d", auto_adjust=False, raise_errors=True)
        closes = [
            value
            for value in (_number(value) for value in history.get("Close", []))
            if value is not None and value > 0
        ]
        if len(closes) < 6:
            return None
        fast = quote.fast_info
        latest = _number(fast.get("last_price")) or closes[-1]
        previous = _number(fast.get("previous_close")) or closes[-2]
        week_ago = closes[-6]
        if latest <= 0 or previous <= 0 or week_ago <= 0:
            return None
        month_ago = closes[-23] if len(closes) >= 23 else None
        three_months_ago = closes[-67] if len(closes) >= 67 else None
        try:
            info = quote.get_info()
        except Exception:
            info = {}
        name = info.get("longName") if isinstance(info, dict) else None
        if not isinstance(name, str) or not name.strip():
            name = fallback_company_name(ticker, source_text)
        return MarketSnapshot(
            company_name=" ".join(name.split()),
            latest_price=latest,
            one_day_change=latest - previous,
            one_day_percent=((latest / previous) - 1) * 100,
            one_week_change=latest - week_ago,
            one_week_percent=((latest / week_ago) - 1) * 100,
            one_month_change=None if month_ago is None else latest - month_ago,
            one_month_percent=None if month_ago is None else ((latest / month_ago) - 1) * 100,
            three_month_change=None if three_months_ago is None else latest - three_months_ago,
            three_month_percent=(
                None if three_months_ago is None else ((latest / three_months_ago) - 1) * 100
            ),
        )
    except Exception:
        return None
