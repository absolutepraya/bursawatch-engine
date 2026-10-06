from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from domain import CompanyCandidate, Provider, SourceKind
from state import complete_provider_bootstrap, provider_bootstrap_complete


_TUNTUN_TOPIC_ID = 3743
_IDX_TICKER = r"[A-Z]{4}"
_TUNTUN_UPDATE_HEADER = re.compile(r"^(?:Midday|Evening) Update_Tuntun Sekuritas_\d{8}$", re.IGNORECASE)
_TUNTUN_SOURCE_LINE = re.compile(r"^Sumber\s*:\s*.+?\s*$", re.IGNORECASE)
_TICKER_LEAD = re.compile(
    rf"^(?P<ticker>{_IDX_TICKER})\s*(?:\([^\r\n]*\))?\s*:\s*\S.*$"
)
_CORPORATE_ISSUER_HEADER = re.compile(rf"^(?P<ticker>{_IDX_TICKER})\s+\([^\r\n]+\)\s*$")
_TUNTUN_SECTIONS = (
    "Headline",
    "Overview",
    "Sector",
    "Top Movers",
    "Net Foreign Buy (Value)",
    "Net Foreign Sell (Value)",
    "Macro & Global",
    "Industry",
    "Corporate",
)
_SPECIAL_TOPIC = re.compile(
    rf"^Special Topics?\s*:\s*(?P<ticker>{_IDX_TICKER})\s*(?:\([^\r\n)]+\))?\s*:\s*\S.*$"
)
_TUNTUN_DECORATED_HEADLINE = re.compile(rf"^📰\s*(?P<ticker>{_IDX_TICKER})(?=\s)")
_TUNTUN_HEADLINE_TICKER = re.compile(rf"(?<![A-Z0-9])(?P<ticker>{_IDX_TICKER})(?![A-Z0-9])")
_TUNTUN_DECORATED_PARENTHESIZED_TICKER = re.compile(
    rf"^📰\s*[^\r\n()]+?\s*\((?P<ticker>{_IDX_TICKER})\)(?=\s|:|-|$)"
)
_TUNTUN_FOREIGN_PARTNER_HEADLINE = re.compile(
    rf"^📰\s*.+?\s+China-(?P<ticker>{_IDX_TICKER})(?=\s|:|-|\(|$)"
)
_TUNTUN_SUBSIDIARY_HEADLINE = re.compile(
    rf"^(?:📰\s*)?Anak\s+[Uu]saha\s+(?P<primary>{_IDX_TICKER})"
    rf"(?:\s*(?:,|dan|&)\s*(?P<secondary>{_IDX_TICKER}))?\b"
)
_TUNTUN_EXCLUDED_CONTENT = re.compile(
    r"(?:^|[:\n])\s*(?:daily|midday|evening|market|macro|sector)\b"
    r"|\b(?:promo(?:tional|tion|si)?|customer service|layanan pelanggan)\b",
    re.IGNORECASE,
)
_PHINTRACO_TICKER_TITLE = re.compile(
    rf"^(?:Notes|Company Flash):\s*(?P<ticker>{_IDX_TICKER})(?=\s|:|-|\(|$)"
)
_PHINTRACO_COMPANY_NOTES_TICKER = re.compile(rf"[–-]\s*(?P<ticker>{_IDX_TICKER})\.IJ\b")
_PHINTRACO_BRANDED_NOTES = re.compile(r"^Phintraco Sekuritas Notes\s*\|", re.IGNORECASE)
_PHINTRACO_QUICK_NOTES = re.compile(r"^PHINTAS Quick Notes\s*\|", re.IGNORECASE)
_PHINTRACO_COMPANY_UPDATE = re.compile(r"^Phintraco Sekuritas Company Update\s*:?[ \t]*$", re.IGNORECASE)
_PHINTRACO_HEADLINE_TICKER = re.compile(rf"^(?P<ticker>{_IDX_TICKER})(?=\s|:|-|\(|$)")
_PHINTRACO_QUICK_NOTE_SUBSIDIARY_HEADLINE = re.compile(
    rf"^(?i:Anak\s+Usaha)\s+(?P<primary>{_IDX_TICKER})"
    rf"(?:\s*(?:,|(?i:dan)|&)\s*(?P<secondary>{_IDX_TICKER}))?\b"
)
_PHINTRACO_STOCK_LINE = re.compile(
    rf"^(?P<ticker>{_IDX_TICKER})\s*(?:\([^\r\n)]+\))?\s*(?::|-)\s*\S.*$"
)
# Reserved four-character acronyms are checked against the current IDX Stock
# List before being added. Do not add ambiguous names that are live issuers.
_NON_ISSUER_TICKERS = frozenset(
    {
        "APBD",
        "APBN",
        "APEC",
        "BEI",
        "BI",
        "BKPM",
        "BMKG",
        "BPJS",
        "BRIN",
        "BUMD",
        "BUMN",
        "CAGR",
        "CCUS",
        "CPO",
        "EBIT",
        "ESDM",
        "FCFE",
        "FCFF",
        "FED",
        "FLNG",
        "FOMC",
        "HGBT",
        "IDX",
        "IHSG",
        "ISPO",
        "IUPK",
        "JCI",
        "KPEI",
        "KPPU",
        "KSEI",
        "LCGC",
        "LQ45",
        "OECD",
        "OIL",
        "OPEC",
        "PLTA",
        "PLTU",
        "POJK",
        "PUPR",
        "REER",
        "RKAB",
        "ROIC",
        "RSPO",
        "RUPS",
        "SOFR",
        "SPBU",
        "TKDN",
        "USD",
        "WACC",
        "WIPO",
    }
)


def _candidate(
    provider: Provider,
    source_message_id: int,
    ticker: str | None,
    source_kind: SourceKind,
    published_at: datetime,
    source_text: str,
    direct_image: bool,
    *,
    candidate_id: str = "",
) -> CompanyCandidate:
    return CompanyCandidate(
        provider=provider,
        source_message_id=source_message_id,
        ticker=ticker,
        source_kind=source_kind,
        published_at=published_at,
        source_text=source_text,
        direct_image=direct_image,
        candidate_id=candidate_id,
    )


def _ticker_from_match(match: re.Match[str]) -> str | None:
    ticker = match["ticker"]
    return None if ticker in _NON_ISSUER_TICKERS else ticker


def _issuer_ticker(ticker: str) -> str | None:
    return None if ticker in _NON_ISSUER_TICKERS else ticker


def _headline_ticker(headline: str) -> str | None:
    return next(
        (
            issuer_ticker
            for match in _TUNTUN_HEADLINE_TICKER.finditer(headline)
            if (issuer_ticker := _issuer_ticker(match["ticker"])) is not None
        ),
        None,
    )


def _strip_source_footer(content: str) -> str:
    return "\n".join(
        line for line in content.splitlines() if _TUNTUN_SOURCE_LINE.match(line.strip()) is None
    ).strip()


def _section_name(line: str) -> str | None:
    heading = line.strip().lstrip("># ").strip("*_ ")
    return next(
        (
            name for name in _TUNTUN_SECTIONS
            if re.fullmatch(re.escape(name) + r"[^\w]*", heading, re.IGNORECASE)
        ),
        None,
    )


def _section_index(lines: list[str], name: str) -> int | None:
    return next(
        (index for index, line in enumerate(lines) if _section_name(line) == name),
        None,
    )


def _section_body(lines: list[str], start: int) -> list[str]:
    end = next(
        (index for index in range(start + 1, len(lines)) if _section_name(lines[index])),
        len(lines),
    )
    return lines[start + 1 : end]


def _paragraph_blocks(lines: list[str]) -> list[str]:
    raw_blocks: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line.strip())
        elif current:
            raw_blocks.append("\n".join(current))
            current = []
    if current:
        raw_blocks.append("\n".join(current))

    blocks: list[str] = []
    index = 0
    while index < len(raw_blocks):
        current_block = raw_blocks[index]
        next_block = raw_blocks[index + 1] if index + 1 < len(raw_blocks) else None
        if (
            next_block is not None
            and current_block[-1] not in ".!?"
            and next_block[-1] in ".!?"
        ):
            blocks.append(f"{current_block}\n\n{next_block}")
            index += 2
            continue
        blocks.append(current_block)
        index += 1
    return blocks


class TuntunNewsAdapter:
    provider = Provider.TUNTUN

    def extract_candidates(
        self,
        message_id: int,
        text: str,
        published_at: datetime,
        topic_id: int | None,
        direct_image: bool,
    ) -> list[CompanyCandidate]:
        if topic_id != _TUNTUN_TOPIC_ID:
            return []

        content = _strip_source_footer(text.strip())
        if not content:
            return []
        lines = content.splitlines()

        if _TUNTUN_UPDATE_HEADER.fullmatch(lines[0].strip()):
            return self._extract_update(message_id, lines, published_at, direct_image)

        if _section_name(lines[0]) == "Corporate":
            return self._extract_corporate(message_id, _section_body(lines, 0), published_at, direct_image)

        if _TUNTUN_EXCLUDED_CONTENT.search(content):
            return []

        special_topic = _SPECIAL_TOPIC.match(lines[0].strip())
        if special_topic is not None:
            ticker = _ticker_from_match(special_topic)
            if ticker is None:
                return []
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.TUNTUN_SPECIAL_TOPIC,
                    published_at,
                    content,
                    direct_image,
                )
            ]

        headline = lines[0].strip()
        foreign_partner = _TUNTUN_FOREIGN_PARTNER_HEADLINE.match(headline)
        if foreign_partner is not None:
            ticker = _ticker_from_match(foreign_partner)
            if ticker is None:
                return []
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.TUNTUN_STANDALONE,
                    published_at,
                    content,
                    direct_image,
                )
            ]

        subsidiary = _TUNTUN_SUBSIDIARY_HEADLINE.match(headline)
        if subsidiary is not None:
            tickers = [
                ticker
                for name in ("primary", "secondary")
                if (raw_ticker := subsidiary.group(name)) is not None
                if (ticker := _issuer_ticker(raw_ticker)) is not None
            ]
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.TUNTUN_STANDALONE,
                    published_at,
                    content,
                    direct_image,
                )
                for ticker in tickers
            ]

        standalone = _TICKER_LEAD.match(headline)
        if standalone is None:
            standalone = _TUNTUN_DECORATED_PARENTHESIZED_TICKER.match(headline)
        if standalone is None:
            standalone = _TUNTUN_DECORATED_HEADLINE.match(headline)
        if standalone is None and headline.startswith("📰"):
            ticker = _headline_ticker(headline)
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.TUNTUN_STANDALONE,
                    published_at,
                    content,
                    direct_image,
                    candidate_id=ticker or "news",
                )
            ]
        if standalone is None:
            return []
        ticker = _ticker_from_match(standalone)
        if ticker is None:
            if headline.startswith("📰"):
                ticker = _headline_ticker(headline)
                return [
                    _candidate(
                        self.provider,
                        message_id,
                        ticker,
                        SourceKind.TUNTUN_STANDALONE,
                        published_at,
                        content,
                        direct_image,
                        candidate_id=ticker or "news",
                    )
                ]
            return []
        return [
            _candidate(
                self.provider,
                message_id,
                ticker,
                SourceKind.TUNTUN_STANDALONE,
                published_at,
                content,
                direct_image,
            )
        ]

    def _extract_update(
        self,
        message_id: int,
        lines: list[str],
        published_at: datetime,
        direct_image: bool,
    ) -> list[CompanyCandidate]:
        overview_index = _section_index(lines, "Overview")
        if overview_index is None:
            return []
        headline_index = _section_index(lines, "Headline")
        lead_lines = (
            _section_body(lines, headline_index)
            if headline_index is not None
            else lines[1:overview_index]
        )
        lead = "\n".join(line.strip() for line in lead_lines if line.strip())
        candidates: list[CompanyCandidate] = []
        if lead:
            headline = lead.splitlines()[0]
            ticker = _headline_ticker(headline)
            candidates.append(
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.TUNTUN_UPDATE_LEAD,
                    published_at,
                    lead,
                    direct_image,
                    candidate_id="lead",
                )
            )

        macro_start = _section_index(lines, "Macro & Global")
        industry_start = _section_index(lines, "Industry")
        if macro_start is not None:
            for index, block in enumerate(_paragraph_blocks(_section_body(lines, macro_start)), start=1):
                headline = block.splitlines()[0]
                candidates.append(
                    _candidate(
                        self.provider,
                        message_id,
                        _headline_ticker(headline),
                        SourceKind.TUNTUN_UPDATE_SECTION,
                        published_at,
                        block,
                        direct_image,
                        candidate_id=f"macro-{index}",
                    )
                )
        if industry_start is not None:
            for index, block in enumerate(_paragraph_blocks(_section_body(lines, industry_start)), start=1):
                headline = block.splitlines()[0]
                candidates.append(
                    _candidate(
                        self.provider,
                        message_id,
                        _headline_ticker(headline),
                        SourceKind.TUNTUN_UPDATE_INDUSTRY,
                        published_at,
                        block,
                        direct_image,
                        candidate_id=f"industry-{index}",
                    )
                )
        corporate_start = _section_index(lines, "Corporate")
        if corporate_start is not None:
            candidates.extend(self._extract_corporate(
                message_id, _section_body(lines, corporate_start), published_at, direct_image,
            ))
        return candidates

    def _extract_corporate(
        self,
        message_id: int,
        lines: list[str],
        published_at: datetime,
        direct_image: bool,
    ) -> list[CompanyCandidate]:
        entries_by_ticker: dict[str, str] = {}
        current_ticker: str | None = None
        current_lines: list[str] = []

        def flush() -> None:
            if current_ticker is not None and len(current_lines) > 1:
                entries_by_ticker.setdefault(current_ticker, "\n".join(current_lines).strip())

        for line in lines:
            entry = line.strip()
            normalized = re.sub(r"^[-•]\s+", "", entry)
            header = _CORPORATE_ISSUER_HEADER.fullmatch(normalized)
            if header is not None:
                flush()
                current_ticker = _ticker_from_match(header)
                current_lines = [entry]
                continue
            match = _TICKER_LEAD.match(normalized)
            if match is not None:
                ticker = _ticker_from_match(match)
                if current_ticker is not None and ticker == current_ticker:
                    current_lines.append(entry)
                    continue
                flush()
                current_ticker = None
                current_lines = []
                if ticker is not None:
                    # Preserve the first legacy entry and message-plus-ticker key.
                    entries_by_ticker.setdefault(ticker, entry)
                continue
            if re.match(rf"^{_IDX_TICKER}\s+\(", normalized):
                # An incomplete issuer header must not contaminate its predecessor.
                flush()
                current_ticker = None
                current_lines = []
            elif current_ticker is not None and entry:
                current_lines.append(entry)
        flush()
        return [
            _candidate(
                self.provider,
                message_id,
                ticker,
                SourceKind.CORPORATE_ENTRY,
                published_at,
                entry,
                direct_image,
            )
            for ticker, entry in entries_by_ticker.items()
        ]


def phintraco_news_headline(candidate: CompanyCandidate) -> str:
    """Read the headline slot of supported branded news, never body text."""
    if candidate.provider is not Provider.PHINTRACO:
        return ""
    lines = candidate.source_text.strip().splitlines()
    if not lines:
        return ""
    header = lines[0].strip()
    if not (
        _PHINTRACO_BRANDED_NOTES.match(header)
        or _PHINTRACO_QUICK_NOTES.match(header)
        or _PHINTRACO_COMPANY_UPDATE.match(header)
    ):
        return ""
    return next((line.strip() for line in lines[1:] if line.strip()), "")


class PhintracoNewsAdapter:
    provider = Provider.PHINTRACO

    def extract_candidates(
        self,
        message_id: int,
        text: str,
        published_at: datetime,
        direct_image: bool,
    ) -> list[CompanyCandidate]:
        content = text.strip()
        if not content or content.startswith("Market Review"):
            return []
        lines = content.splitlines()
        header = lines[0].strip()

        if header.startswith("Notes:") or header.startswith("Company Flash:"):
            title = _PHINTRACO_TICKER_TITLE.match(header)
            if title is None:
                return []
            ticker = _ticker_from_match(title)
            if ticker is None:
                return []
            source_kind = (
                SourceKind.PHINTRACO_NOTE
                if header.startswith("Notes:")
                else SourceKind.PHINTRACO_COMPANY_FLASH
            )
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    source_kind,
                    published_at,
                    content,
                    direct_image,
                )
            ]

        if header.startswith("Company Notes"):
            issuer_line = lines[1].strip() if len(lines) > 1 else ""
            title = _PHINTRACO_COMPANY_NOTES_TICKER.search(issuer_line)
            if title is None:
                return []
            ticker = _ticker_from_match(title)
            if ticker is None:
                return []
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.PHINTRACO_NOTE,
                    published_at,
                    content,
                    direct_image,
                )
            ]

        if _PHINTRACO_BRANDED_NOTES.match(header) or _PHINTRACO_QUICK_NOTES.match(header):
            headline = next((line.strip() for line in lines[1:] if line.strip()), "")
            if not headline:
                return []
            title = _PHINTRACO_HEADLINE_TICKER.match(headline)
            subsidiary = (
                _PHINTRACO_QUICK_NOTE_SUBSIDIARY_HEADLINE.match(headline)
                if _PHINTRACO_QUICK_NOTES.match(header)
                else None
            )
            if title is not None:
                ticker = _ticker_from_match(title)
            elif subsidiary is not None:
                primary = _issuer_ticker(subsidiary["primary"])
                secondary = subsidiary["secondary"]
                ticker = (
                    primary
                    if primary is not None and (secondary is None or _issuer_ticker(secondary) is None)
                    else None
                )
            else:
                ticker = None
            source_kind = (
                SourceKind.PHINTRACO_QUICK_NOTE
                if _PHINTRACO_QUICK_NOTES.match(header)
                else SourceKind.PHINTRACO_NOTE
            )
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    source_kind,
                    published_at,
                    content,
                    direct_image,
                )
            ]

        if _PHINTRACO_COMPANY_UPDATE.match(header):
            headline = next((line.strip() for line in lines[1:] if line.strip()), "")
            if not headline:
                return []
            title = _PHINTRACO_HEADLINE_TICKER.match(headline)
            ticker = _ticker_from_match(title) if title is not None else None
            return [
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.PHINTRACO_COMPANY_UPDATE,
                    published_at,
                    content,
                    direct_image,
                )
            ]

        if header not in {"Stock Information", "Stock Information:"}:
            return []
        candidates: list[CompanyCandidate] = []
        for line in lines[1:]:
            entry = line.strip()
            status = _PHINTRACO_STOCK_LINE.match(entry)
            if status is None:
                continue
            ticker = _ticker_from_match(status)
            if ticker is None:
                continue
            candidates.append(
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.PHINTRACO_STOCK_INFORMATION,
                    published_at,
                    entry,
                    direct_image,
                )
            )
        return candidates


async def fetch_unseen_messages(client: Any, entity: Any, min_id: int) -> list[Any]:
    return [
        message async for message in client.iter_messages(entity, min_id=min_id, reverse=True)
    ]


async def bootstrap_provider(
    client: Any,
    entity: Any,
    state: dict[str, object],
    provider: Provider,
) -> bool:
    if provider_bootstrap_complete(state, provider):
        return False

    latest_id = 0
    async for message in client.iter_messages(entity, limit=1):
        message_id = getattr(message, "id", 0)
        if isinstance(message_id, int) and not isinstance(message_id, bool) and message_id > latest_id:
            latest_id = message_id
    return complete_provider_bootstrap(state, provider, latest_id)
