# Shared company news

Language for news presentation across platform sources. Market coverage,
headings, and multi-company item policy are recorded in the
[universal-format discussion](../specs/2026-10-02-universal-stock-news-format.md)
and the later [company-news design](../specs/2026-11-03-company-news-format.md).
The definitions below reflect accepted design decisions, independently of
implementation or production adoption.

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

**Company-news card**:
The reader-facing presentation of a company-news item focused on one company,
including its summary, source provenance, and applicable market context.
The focus company may be publicly listed or private.
_Avoid_: Stock-news card, company roundup, source publication, raw forwarding

**Company-news destination group**:
A geographic grouping by the focus company's primary business home:
Indonesia, US, or Global. Each includes public and private companies.
_Avoid_: Listing requirement, quote market, Macro fallback

**Global Company News**:
Company news about businesses based outside Indonesia and the US, or whose
primary business home cannot be established.
_Avoid_: Macro News, US-listed-company news, assumed country

**Primary business home**:
The country in which the focus company is principally based as a business.
It is distinct from the exchange where its securities trade.
_Avoid_: Listing country, publisher location, counterparty location

**Focus company**:
The single company whose development a company-news item primarily reports.
Its identity is distinct from any listed security associated with it.
_Avoid_: First ticker mentioned, every company named

**News headline**:
A natural, descriptive statement of the selected news that names the focus
company when central. Prefix the headline with the verified current ticker
and a colon when available; otherwise use the company name.
_Avoid_: Invented or former ticker prefix, source account name, investment instruction

**Company-news item**:
A substantive, source-supported development focused on one company,
independently of whether it is listed, private, preparing an IPO, or formerly
listed. Unrelated company developments are separate items.
_Avoid_: Listed-company-only news, company roundup, every company mention

**Connected multi-company story**:
One development whose meaning depends on multiple companies, such as a single
acquisition. A card retains one focus company while other companies supply
necessary context; mentioning them does not establish distinct news items.
_Avoid_: Company roundup, unrelated news batch, duplicate transaction cards

**Education content**:
A general lesson about investing methods, strategies, psychology, or market
mechanics whose primary purpose is teaching rather than reporting a concrete
issuer development or substantive current market analysis.
_Avoid_: All analysis, any mention of earnings or charts

**Security identity**:
The exact listed instrument and exchange to which market data belongs. A
ticker-shaped word alone does not establish this identity.
_Avoid_: Company mention, guessed ticker, proposed IPO ticker

**Current focus-company security**:
A verified currently listed security belonging to the card's focus company,
distinct from a proposed IPO security, former listing, or parent's security.
_Avoid_: Historical ticker, inherited parent ticker

**Prepared news card**:
The fixed representation of a news card chosen for publication, including
the market values displayed with it.
_Avoid_: Freshly repriced retry, source publication
