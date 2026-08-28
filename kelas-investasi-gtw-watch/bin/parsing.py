from __future__ import annotations

import re

from idx_tickers import is_idx_ticker
from models import GtwHeader, PlanSource


# The anchors deliberately reject captions, promotional suffixes, and tags such
# as #GTWXYZ. Ticker eligibility is checked against the local IDX snapshot.
_GTW_HEADER = re.compile(r"^Good\s+to\s+watch\s*-\s*([A-Za-z]{2,5})\s+#GTW$", re.IGNORECASE)
_LABEL_VALUE = re.compile(
    r"^\s*(?:[•*]\s*)?(?P<label>buy\s+area|tp(?:\s*\d+)?|target(?:\s*\d+)?|stop[-\s]?loss(?:\s+\w+)?)\s*[:=-]\s*(?P<value>.*?)\s*$",
    re.IGNORECASE,
)
_RANGE = re.compile(r"(?P<left>\d+(?:[.,]\d+)?)\s*(?:-|–|—)\s*(?P<right>\d+(?:[.,]\d+)?)")


def parse_gtw_header(text: str) -> GtwHeader | None:
    match = _GTW_HEADER.fullmatch(text.strip())
    if match is None:
        return None
    ticker = match.group(1).upper()
    if not is_idx_ticker(ticker):
        return None
    return GtwHeader(ticker=ticker)


def extract_plan(text: str) -> PlanSource:
    buy_area = "-"
    targets: list[str] = []
    stoploss = "-"

    for line in text.splitlines():
        match = _LABEL_VALUE.match(line)
        if match is None:
            continue
        label = match.group("label").lower().replace(" ", "")
        value = _plan_value(match.group("value"))
        if not value:
            continue
        if label == "buyarea":
            range_match = _RANGE.fullmatch(value)
            buy_area = (
                f"{range_match.group('left')} sampai {range_match.group('right')}"
                if range_match
                else value
            )
        elif label.startswith("tp") or label.startswith("target"):
            targets.append(value)
        else:
            stoploss = value

    return PlanSource(buy_area=buy_area, targets=", ".join(targets) or "-", stoploss=stoploss)


def _plan_value(value: str) -> str:
    return re.split(r"\s*(?:→|->)\s*", value, maxsplit=1)[0].strip()
