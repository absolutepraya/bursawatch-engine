from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from domain import CompanyCandidate, Provider, SourceKind
from state import complete_provider_bootstrap, provider_bootstrap_complete


_TUNTUN_TOPIC_ID = 3743
_IDX_TICKER = r"[A-Z]{4}"
_TUNTUN_UPDATE_HEADER = re.compile(r"^(?:Midday|Evening) Update_Tuntun Sekuritas_\d{8}$", re.IGNORECASE)
_TUNTUN_SOURCE_LINE = re.compile(r"^Sumber\s*:\s*(?P<source>.+?)\s*$", re.IGNORECASE)
_TICKER_LEAD = re.compile(
    rf"^(?P<ticker>{_IDX_TICKER})\s*(?:\([^\r\n)]+\))?\s*:\s*\S.*$"
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
_PHINTRACO_HEADLINE_TICKER = re.compile(rf"^(?P<ticker>{_IDX_TICKER})(?=\s|:|-|\(|$)")
_PHINTRACO_STOCK_LINE = re.compile(
    rf"^(?P<ticker>{_IDX_TICKER})\s*(?:\([^\r\n)]+\))?\s*(?::|-)\s*\S.*$"
)
_NON_ISSUER_TICKERS = frozenset({"BEI", "BI", "CPO", "FED", "IDX", "IHSG", "JCI", "LQ45", "OIL", "USD"})


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
    source_name: str = "Tuntun Sekuritas",
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
        source_name=source_name,
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


def _source_attribution(content: str) -> tuple[str, str]:
    lines = content.splitlines()
    source_name = "Tuntun Sekuritas"
    retained: list[str] = []
    for line in lines:
        match = _TUNTUN_SOURCE_LINE.match(line.strip())
        if match is None:
            retained.append(line)
            continue
        source_name = " ".join(match["source"].strip(" *_").split()) or source_name
    return "\n".join(retained).strip(), source_name


def _section_index(lines: list[str], name: str) -> int | None:
    expected = name.casefold()
    return next(
        (index for index, line in enumerate(lines) if line.strip().casefold().startswith(expected)),
        None,
    )


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

        content, source_name = _source_attribution(text.strip())
        if not content:
            return []
        lines = content.splitlines()

        if _TUNTUN_UPDATE_HEADER.fullmatch(lines[0].strip()):
            return self._extract_update(message_id, lines, published_at, direct_image, source_name)

        if _TUNTUN_EXCLUDED_CONTENT.search(content):
            return []

        if lines[0].strip() in {"Corporate", "Corporate 🏢"}:
            return self._extract_corporate(message_id, lines[1:], published_at, direct_image, source_name)

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
                    source_name=source_name,
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
                    source_name=source_name,
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
                    source_name=source_name,
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
                    source_name=source_name,
                )
            ]
        if standalone is None:
            return []
        ticker = _ticker_from_match(standalone)
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
                source_name=source_name,
            )
        ]

    def _extract_update(
        self,
        message_id: int,
        lines: list[str],
        published_at: datetime,
        direct_image: bool,
        source_name: str,
    ) -> list[CompanyCandidate]:
        overview_index = _section_index(lines, "Overview")
        if overview_index is None:
            return []
        lead = "\n".join(line.strip() for line in lines[1:overview_index] if line.strip())
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
                    source_name=source_name,
                )
            )

        for section_name, prefix in (("Macro & Global", "macro"), ("Industry", "industry")):
            start = _section_index(lines, section_name)
            if start is None:
                continue
            end = len(lines)
            if section_name == "Macro & Global":
                industry_start = _section_index(lines, "Industry")
                if industry_start is not None and industry_start > start:
                    end = industry_start
            for index, block in enumerate(_paragraph_blocks(lines[start + 1 : end]), start=1):
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
                        candidate_id=f"{prefix}-{index}",
                        source_name=source_name,
                    )
                )
        return candidates

    def _extract_corporate(
        self,
        message_id: int,
        lines: list[str],
        published_at: datetime,
        direct_image: bool,
        source_name: str,
    ) -> list[CompanyCandidate]:
        candidates: list[CompanyCandidate] = []
        for line in lines:
            entry = line.strip()
            match = _TICKER_LEAD.match(entry)
            if match is None:
                continue
            ticker = _ticker_from_match(match)
            if ticker is None:
                continue
            candidates.append(
                _candidate(
                    self.provider,
                    message_id,
                    ticker,
                    SourceKind.CORPORATE_ENTRY,
                    published_at,
                    entry,
                    direct_image,
                    source_name=source_name,
                )
            )
        return candidates


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

        if _PHINTRACO_BRANDED_NOTES.match(header):
            headline = next((line.strip() for line in lines[1:] if line.strip()), "")
            title = _PHINTRACO_HEADLINE_TICKER.match(headline)
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
