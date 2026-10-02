# Shared stock news

Language for news presentation across platform sources. Market coverage,
headings, and multi-company item policy are recorded in the
[universal-format discussion](../specs/2026-10-02-universal-stock-news-format.md).

## Language

**Platform source**:
The medium through which a publication enters Bursawatch, such as Telegram,
X, WhatsApp, Instagram, or a Stockbit RSS feed.
_Avoid_: Publisher, route

**Publisher**:
The institution, account, or writer responsible for the source publication.
_Avoid_: Platform source, sorter

**News domain owner**:
The part of Bursawatch responsible for interpreting and publishing accepted
news from its supported sources.
_Avoid_: Platform source, Discord transport

**Stock-news card**:
The reader-facing presentation of a stock-news item, including its summary,
source provenance, and market context when a security is identified.
_Avoid_: Source publication, raw forwarding

**Independent issuer news item**:
A source-supported development about one issuer that can be reported without
borrowing facts from another unrelated story in the same publication.
_Avoid_: Every company mention, first ticker in a roundup

**Connected multi-company story**:
One development whose meaning depends on multiple companies, such as a single
acquisition. Mentioning several issuers does not make it several independent
news items.
_Avoid_: Issuer roundup, unrelated news batch

**Education content**:
A general lesson about investing methods, strategies, psychology, or market
mechanics whose primary purpose is teaching rather than reporting a concrete
issuer development or substantive current market analysis.
_Avoid_: All analysis, any mention of earnings or charts

**Security identity**:
The exact listed instrument and exchange to which market data belongs. A
ticker-shaped word alone does not establish this identity.
_Avoid_: Company mention, guessed ticker

**Prepared news card**:
The fixed representation of a news card chosen for publication, including
the market values displayed with it.
_Avoid_: Freshly repriced retry, source publication
