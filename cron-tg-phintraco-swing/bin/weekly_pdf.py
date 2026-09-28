"""Bounded text and chart extraction for Phintraco's weekly swing PDF."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

import pymupdf


MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_PAGES = 12
MAX_PLANS = 24
MAX_CHART_BYTES = 8 * 1024 * 1024
MAX_CHART_DIMENSION = 4096
_FILENAME_RE = re.compile(r"^PHINTAS Weekly Swing Trading Ideas_(\d{8})\.pdf$")
_HEADING_RE = re.compile(
    r"^\s*(?P<number>\d{1,2})\s*\.\s+(?P<ticker>[A-Z]{4})\s*[-–—]\s*(?P<descriptor>.+?)\s*$"
)
_NUMBERED_LINE_RE = re.compile(r"^\s*\d{1,2}\s*\.")
_DATE_RE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?,\s*(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_STOP_RE = re.compile(r"\bSL\s*(?:[:=]\s*)?([<>]=?\s*[\d,]+)", re.IGNORECASE)
_TARGET_RE = re.compile(r"^\s*Target\s+Price(?:\s+(\d+))?\s*:\s*(.*?)\s*$", re.IGNORECASE)
_LEVEL_RE = re.compile(r"(?:[<>]=?\s*)?\d[\d,]*(?:\s*(?:-|to)\s*\d[\d,]*)?", re.IGNORECASE)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class WeeklyPdfError(ValueError):
    """The document is outside the supported weekly report contract."""


@dataclass(frozen=True)
class Target:
    number: int | None
    value: str


@dataclass(frozen=True)
class WeeklySetup:
    ticker: str
    descriptor: str
    trend: str
    ma_indicator: str
    potential_upside: str
    potential_downside: str
    entry: str
    stop_loss: str
    targets: tuple[Target, ...]
    page_number: int
    section_number: int
    chart_bytes: bytes


@dataclass(frozen=True)
class QuarantinedPage:
    page_number: int
    reason: str


@dataclass(frozen=True)
class WeeklyPdfResult:
    report_date: date
    setups: tuple[WeeklySetup, ...]
    quarantined_pages: tuple[QuarantinedPage, ...]


@dataclass(frozen=True)
class _Line:
    x0: float
    y0: float
    text: str


@dataclass(frozen=True)
class _Section:
    number: int
    ticker: str
    descriptor: str
    line: _Line
    lines: tuple[_Line, ...]


class _PageError(ValueError):
    pass


def parse_weekly_pdf(filename: str, pdf_bytes: bytes) -> WeeklyPdfResult:
    """Parse a supported weekly PDF, quarantining ambiguous pages."""
    filename_match = _FILENAME_RE.fullmatch(filename)
    if filename_match is None:
        raise WeeklyPdfError("unsupported weekly PDF filename")
    try:
        expected_date = date.fromisoformat(
            f"{filename_match.group(1)[:4]}-{filename_match.group(1)[4:6]}-{filename_match.group(1)[6:8]}"
        )
    except ValueError as exc:
        raise WeeklyPdfError("weekly PDF filename contains an invalid report date") from exc
    if not isinstance(pdf_bytes, bytes) or not pdf_bytes or len(pdf_bytes) > MAX_PDF_BYTES:
        raise WeeklyPdfError("weekly PDF is empty or exceeds the size limit")

    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise WeeklyPdfError("weekly PDF could not be opened") from exc
    try:
        if document.is_encrypted or document.needs_pass:
            raise WeeklyPdfError("encrypted weekly PDFs are not supported")
        if not 1 <= document.page_count <= MAX_PAGES:
            raise WeeklyPdfError("weekly PDF page count is outside the supported limit")

        report_date = _extract_report_date(document, expected_date)
        if sum(1 for page in document if _heading_count(page) > 0) > MAX_PLANS:
            raise WeeklyPdfError("weekly PDF has too many ticker plans")

        parsed_pages: list[tuple[int, list[WeeklySetup]]] = []
        quarantines: dict[int, str] = {}
        for page_index, page in enumerate(document):
            try:
                parsed_pages.append((page_index + 1, _parse_page(page, page_index + 1)))
            except _PageError as exc:
                quarantines[page_index + 1] = str(exc)

        occurrences: dict[str, list[int]] = {}
        for page_number, setups in parsed_pages:
            for setup in setups:
                occurrences.setdefault(setup.ticker, []).append(page_number)
        duplicate_pages = {
            page_number
            for pages in occurrences.values()
            if len(pages) > 1
            for page_number in pages
        }
        for page_number in duplicate_pages:
            quarantines[page_number] = "weekly plan document has duplicate ticker sections"

        setups = tuple(
            setup
            for page_number, page_setups in parsed_pages
            if page_number not in quarantines
            for setup in page_setups
        )
        if not setups and not quarantines:
            raise WeeklyPdfError("weekly PDF contains no recognized ticker plans")
        return WeeklyPdfResult(
            report_date=report_date,
            setups=setups,
            quarantined_pages=tuple(
                QuarantinedPage(page_number, quarantines[page_number])
                for page_number in sorted(quarantines)
            ),
        )
    finally:
        document.close()


def _extract_report_date(document: Any, expected_date: date) -> date:
    page = document[0]
    candidates: list[date] = []
    for line in _text_lines(page):
        if line.x0 > page.rect.width * 0.45 or line.y0 > 120:
            continue
        match = _DATE_RE.search(line.text)
        if match is None:
            continue
        try:
            candidates.append(
                date(
                    int(match.group("year")),
                    _MONTHS[match.group("month").lower()],
                    int(match.group("day")),
                )
            )
        except ValueError as exc:
            raise WeeklyPdfError("weekly PDF has an invalid printed report date") from exc
    if candidates != [expected_date]:
        raise WeeklyPdfError("weekly PDF printed date does not match its filename")
    return candidates[0]


def _heading_count(page: Any) -> int:
    return sum(
        1
        for line in _text_lines(page)
        if line.x0 <= page.rect.width * 0.48 and _HEADING_RE.fullmatch(line.text)
    )


def _text_lines(page: Any) -> list[_Line]:
    lines: list[_Line] = []
    text_flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", flags=text_flags)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if text:
                x0, y0, _, _ = line["bbox"]
                lines.append(_Line(x0=x0, y0=y0, text=text))
    return sorted(lines, key=lambda line: (line.y0, line.x0))


def _parse_page(page: Any, page_number: int) -> list[WeeklySetup]:
    lines = [line for line in _text_lines(page) if line.x0 <= page.rect.width * 0.48]
    heading_positions = [
        index for index, line in enumerate(lines) if _HEADING_RE.fullmatch(line.text)
    ]
    malformed_numbered = any(
        _NUMBERED_LINE_RE.match(line.text) and _HEADING_RE.fullmatch(line.text) is None
        for line in lines
    )
    if malformed_numbered or not heading_positions:
        raise _PageError("weekly plan page has an unsupported ticker heading")

    sections: list[_Section] = []
    for position, start in enumerate(heading_positions):
        match = _HEADING_RE.fullmatch(lines[start].text)
        assert match is not None
        end = heading_positions[position + 1] if position + 1 < len(heading_positions) else len(lines)
        section_lines = tuple(lines[start + 1 : end])
        sections.append(
            _Section(
                number=int(match.group("number")),
                ticker=match.group("ticker"),
                descriptor=match.group("descriptor").strip(),
                line=lines[start],
                lines=section_lines,
            )
        )

    tickers = [section.ticker for section in sections]
    if len(set(tickers)) != len(tickers):
        raise _PageError("weekly plan page has duplicate ticker sections")

    extracted: list[tuple[_Section, dict[str, Any]]] = []
    for section in sections:
        extracted.append((section, _parse_section(section)))

    charts = _chart_blocks(page)
    if len(charts) != len(sections):
        raise _PageError("weekly plan page has an ambiguous chart association")

    boundaries = [section.line.y0 for section in sections] + [page.rect.height - 1]
    assigned: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(sections))}
    for chart in charts:
        center_y = (chart["bbox"][1] + chart["bbox"][3]) / 2
        matches = [
            i
            for i in range(len(sections))
            if sections[i].line.y0 <= center_y < boundaries[i + 1]
        ]
        if len(matches) != 1:
            raise _PageError("weekly plan page has an ambiguous chart association")
        assigned[matches[0]].append(chart)
    if any(len(assigned[index]) != 1 for index in range(len(sections))):
        raise _PageError("weekly plan page has an ambiguous chart association")

    output: list[WeeklySetup] = []
    for index, (section, fields) in enumerate(extracted):
        chart = assigned[index][0]
        output.append(
            WeeklySetup(
                ticker=section.ticker,
                descriptor=section.descriptor,
                trend=fields["trend"],
                ma_indicator=fields["ma_indicator"],
                potential_upside=fields["potential_upside"],
                potential_downside=fields["potential_downside"],
                entry=fields["entry"],
                stop_loss=fields["stop_loss"],
                targets=fields["targets"],
                page_number=page_number,
                section_number=section.number,
                chart_bytes=chart["image"],
            )
        )
    return output


def _parse_section(section: _Section) -> dict[str, Any]:
    values = {
        "trend": _field_values(section.lines, r"Trend\s*:\s*(.*)"),
        "ma_indicator": _field_values(section.lines, r"MA\.?\s*Indicator\s*:\s*(.*)"),
        "potential_upside": _field_values(section.lines, r"Potential\s+Upside\s*:\s*(.*)"),
        "potential_downside": _field_values(section.lines, r"Potential\s+Downside\s*:\s*(.*)"),
        "action": _field_values(section.lines, r"ACTION\s*:\s*(.*)"),
        "entry": _field_values(section.lines, r"Entry\s*:\s*(.*)"),
    }
    if len(values["action"]) != 1 or values["action"][0].casefold() != "buy":
        raise _PageError("weekly plan page has an incomplete Buy setup")
    if len(values["entry"]) != 1 or not _valid_level(values["entry"][0]):
        raise _PageError("weekly plan page has an incomplete Buy setup")

    stops: list[str] = []
    targets: list[Target] = []
    for line in section.lines:
        stop_matches = list(_STOP_RE.finditer(line.text))
        stops.extend(_normalize_level(match.group(1)) for match in stop_matches)
        target_match = _TARGET_RE.fullmatch(line.text)
        if target_match is None:
            continue
        target_value = _STOP_RE.sub("", target_match.group(2)).strip(" ;,\t")
        target_value = _normalize_level(target_value)
        if not _valid_level(target_value):
            raise _PageError("weekly plan page has malformed target levels")
        target_number = int(target_match.group(1)) if target_match.group(1) else None
        if target_number is not None and not 1 <= target_number <= 6:
            raise _PageError("weekly plan page has unsupported target numbering")
        targets.append(Target(target_number, target_value))

    if len(stops) != 1 or not _valid_level(stops[0]) or not targets:
        raise _PageError("weekly plan page has an incomplete Buy setup")
    numbers = [target.number for target in targets if target.number is not None]
    if len(set(numbers)) != len(numbers) or (numbers and any(target.number is None for target in targets)):
        raise _PageError("weekly plan page has duplicate or ambiguous target numbering")
    targets.sort(key=lambda target: target.number if target.number is not None else 0)

    for key in ("trend", "ma_indicator", "potential_upside", "potential_downside"):
        if len(values[key]) > 1:
            raise _PageError("weekly plan page has duplicate setup fields")
    return {
        "trend": values["trend"][0] if values["trend"] else "",
        "ma_indicator": values["ma_indicator"][0] if values["ma_indicator"] else "",
        "potential_upside": values["potential_upside"][0] if values["potential_upside"] else "",
        "potential_downside": values["potential_downside"][0] if values["potential_downside"] else "",
        "entry": _normalize_level(values["entry"][0]),
        "stop_loss": stops[0],
        "targets": tuple(targets),
    }


def _field_values(lines: tuple[_Line, ...], expression: str) -> list[str]:
    pattern = re.compile(rf"^\s*{expression}\s*$", re.IGNORECASE)
    return [match.group(1).strip() for line in lines if (match := pattern.fullmatch(line.text))]


def _normalize_level(value: str) -> str:
    normalized = value.strip().replace("−", "-").replace("–", "-").replace("—", "-")
    normalized = re.sub(r"\s*-\s*", " to ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"([<>]=?)\s+", r"\1", normalized)
    return normalized


def _valid_level(value: str) -> bool:
    return _LEVEL_RE.fullmatch(value.strip()) is not None


def _chart_blocks(page: Any) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    seen_xrefs: set[int] = set()
    for info in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        width = int(info.get("width", 0))
        height = int(info.get("height", 0))
        aspect_ratio = width / height if height else 0
        if (
            x0 >= page.rect.width * 0.48
            and width >= 256
            and height >= 128
            and width <= MAX_CHART_DIMENSION
            and height <= MAX_CHART_DIMENSION
            and 1.65 <= aspect_ratio <= 2.1
            and y0 >= 20
            and y1 <= page.rect.height - 20
        ):
            xref = int(info.get("xref", 0))
            if xref == 0 or xref in seen_xrefs:
                raise _PageError("weekly plan page has an ambiguous chart association")
            seen_xrefs.add(xref)
            try:
                image = page.parent.extract_image(xref)
            except Exception as exc:
                raise _PageError("weekly plan page has an unreadable chart image") from exc
            if (
                image.get("ext", "").lower() not in {"jpeg", "jpg"}
                or len(image.get("image", b"")) > MAX_CHART_BYTES
            ):
                raise _PageError("weekly plan page has an unsupported chart image")
            charts.append({"bbox": info["bbox"], "image": image["image"]})
    return sorted(charts, key=lambda chart: (chart["bbox"][1], chart["bbox"][0]))
