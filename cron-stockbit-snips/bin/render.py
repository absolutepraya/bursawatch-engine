from __future__ import annotations

import re

from config import GREY_EMOJI, GREEN_EMOJI, RED_EMOJI, STOCKBIT_EMOJI
from market_data import MarketSnapshot
from models import Analysis, Article, Route


DISCORD_LIMIT = 2000
RINGKASAN_PREFIX = "*(Ringkasan)* "
INVESTMENT_LANGUAGE = re.compile(
    r"\b(?:buy|sell|entry|target|stop[\s-]*loss|valuation|bullish|bearish|upside|downside)\b",
    re.IGNORECASE,
)


def _idr(value: float, signed: bool = False) -> str:
    rounded = round(abs(value))
    prefix = "+" if signed and value > 0 else "-" if signed and value < 0 else ""
    return f"{prefix}{rounded:,}".replace(",", ".")


def _direction(value: float | None) -> str:
    if value is None or value == 0:
        return GREY_EMOJI
    return GREEN_EMOJI if value > 0 else RED_EMOJI


def _metric(label: str, change: float | None, percent: float | None) -> str:
    if change is None or percent is None:
        return f"{GREY_EMOJI} {label}: **-**"
    percent_text = f"{percent:+.2f}".replace(".", ",")
    return f"{_direction(change)} {label}: **{_idr(change, signed=True)} ({percent_text}%)**"


def _market_block(snapshot: MarketSnapshot | None) -> str:
    if snapshot is None:
        return (
            "Harga terakhir (IDR): **-**\n"
            f"{_metric('1D', None, None)}, {_metric('1W', None, None)},\n"
            f"{_metric('1M', None, None)}, {_metric('3M', None, None)}"
        )
    return (
        f"Harga terakhir (IDR): **{_idr(snapshot.latest_price)}**\n"
        f"{_metric('1D', snapshot.one_day_change, snapshot.one_day_percent)}, "
        f"{_metric('1W', snapshot.one_week_change, snapshot.one_week_percent)},\n"
        f"{_metric('1M', snapshot.one_month_change, snapshot.one_month_percent)}, "
        f"{_metric('3M', snapshot.three_month_change, snapshot.three_month_percent)}"
    )


def render(article: Article, analysis: Analysis, snapshot: MarketSnapshot | None = None) -> str:
    if analysis.route is Route.EXCLUDE:
        raise ValueError("excluded Stockbit article cannot be rendered")
    if not analysis.title or not analysis.summary:
        raise ValueError("Stockbit analysis title and summary are required")
    if INVESTMENT_LANGUAGE.search(analysis.summary):
        raise ValueError("Stockbit summary contains investment language")
    content = [
        f"### {STOCKBIT_EMOJI} {analysis.title}",
        "-# Stockbit",
        "",
        f"{RINGKASAN_PREFIX}{analysis.summary}",
    ]
    if analysis.route is Route.ID_STOCKS_NEWS:
        content.extend(["", _market_block(snapshot)])
    content.extend(["", f"[View on Stockbit](<{article.url}>)"])
    result = "\n".join(content)
    if len(result) > DISCORD_LIMIT:
        raise ValueError("Stockbit Discord content exceeds 2,000 characters")
    return result
