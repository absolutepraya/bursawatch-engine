from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re


_SOURCE_SECTIONS = {
    "Unusual Market Activity (UMA)": "uma",
    "Suspend": "suspend_in",
    "Unsuspend": "suspend_out",
    "FCA In": "fca_in",
    "FCA Out": "fca_out",
}
_SECTION_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z ()&/-]*?)\s*:\s*$")
_EFFECTIVE_DATE_LINE = re.compile(
    r"^\s*Effective\s+date\s*:\s*(\d{1,2} [A-Za-z]+ \d{4})\s*$"
)
_TICKER_LINE = re.compile(r"^\s*>([A-Z]{4})\s*$")
_EMPTY_LINE = re.compile(r"^\s*>-\s*$")
_FOOTERS = {
    "By PHINTRACO SEKURITAS | Research",
    "-Disclaimer On -",
}
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


@dataclass(frozen=True, slots=True)
class StockStatus:
    source_message_id: int
    effective_date: date
    uma: tuple[str, ...]
    suspend_in: tuple[str, ...]
    suspend_out: tuple[str, ...]
    fca_in: tuple[str, ...]
    fca_out: tuple[str, ...]


class StockStatusError(ValueError):
    pass


def is_stock_information(text: str) -> bool:
    """Return whether the first source line exactly selects this format."""
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return first_line == "Stock Information"


def parse_stock_information(source_message_id: int, text: str) -> StockStatus:
    """Parse a complete Phintraco status post without inferring missing data."""
    lines = text.splitlines()
    if not lines or lines[0] != "Stock Information":
        raise StockStatusError("unexpected status post header")

    effective_dates: list[date] = []
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    empty_markers: set[str] = set()
    footers_started = False

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue

        date_match = _EFFECTIVE_DATE_LINE.fullmatch(raw_line)
        if date_match:
            if effective_dates or sections or footers_started:
                raise StockStatusError("duplicate or misplaced effective date")
            try:
                effective_dates.append(
                    datetime.strptime(date_match.group(1), "%d %B %Y").date()
                )
            except ValueError as exc:
                raise StockStatusError("invalid effective date") from exc
            continue
        if line.lower().startswith("effective date"):
            raise StockStatusError("invalid effective date")

        section_match = _SECTION_LINE.fullmatch(raw_line)
        if section_match:
            label = " ".join(section_match.group(1).split())
            field = _SOURCE_SECTIONS.get(label)
            if field is None:
                raise StockStatusError("unknown status section")
            if footers_started:
                raise StockStatusError("status section follows source footer")
            if field in sections:
                raise StockStatusError("duplicate status section")
            sections[field] = []
            current_section = field
            continue

        if line in _FOOTERS:
            if set(sections) != set(_SOURCE_SECTIONS.values()):
                raise StockStatusError("source footer precedes complete status sections")
            footers_started = True
            current_section = None
            continue

        if current_section is None or footers_started:
            raise StockStatusError("unexpected status post content")

        if _EMPTY_LINE.fullmatch(raw_line):
            if sections[current_section]:
                raise StockStatusError("empty marker mixed with ticker entries")
            if current_section in empty_markers:
                raise StockStatusError("duplicate empty marker")
            empty_markers.add(current_section)
            continue

        ticker_match = _TICKER_LINE.fullmatch(raw_line)
        if ticker_match:
            if current_section in empty_markers:
                raise StockStatusError("ticker entry follows empty marker")
            ticker = ticker_match.group(1)
            if ticker not in sections[current_section]:
                sections[current_section].append(ticker)
            continue

        raise StockStatusError("malformed status category entry")

    if len(effective_dates) != 1:
        raise StockStatusError("status post requires one effective date")
    if set(sections) != set(_SOURCE_SECTIONS.values()):
        raise StockStatusError("status post requires each status section once")

    return StockStatus(
        source_message_id=source_message_id,
        effective_date=effective_dates[0],
        uma=tuple(sections["uma"]),
        suspend_in=tuple(sections["suspend_in"]),
        suspend_out=tuple(sections["suspend_out"]),
        fca_in=tuple(sections["fca_in"]),
        fca_out=tuple(sections["fca_out"]),
    )


def format_stock_status(status: StockStatus, source_url: str) -> str:
    """Render the fixed grouped Discord message for a parsed status post."""
    effective_date = status.effective_date
    heading_date = (
        f"{_WEEKDAYS[effective_date.weekday()]}, "
        f"{effective_date.day:02d} {_MONTHS[effective_date.month - 1]} "
        f"{effective_date.year}"
    )
    content = [
        f"### <:phintraco:1531272488645038091> Stock Status: Web, {heading_date}"
    ]
    for label, tickers in (
        ("UMA", status.uma),
        ("Suspend In", status.suspend_in),
        ("Suspend Out", status.suspend_out),
        ("FCA In", status.fca_in),
        ("FCA Out", status.fca_out),
    ):
        entries = "\n".join(f"- {ticker}" for ticker in tickers) or "(None)"
        content.append(f"**{label}:**\n{entries}")
    content.append(f"[View in Telegram](<{source_url}>)")
    rendered = "\n\n".join(content)
    if len(rendered) > 2000:
        raise StockStatusError("rendered status message exceeds Discord limit")
    return rendered
