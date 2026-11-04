# Shared generated-news format

This library owns writing guidance, deterministic native-currency quotes and
source-neutral Discord cards. Owners retain relevance, routing, intake,
leases, media, receipts and retry state. Read README.md before changes.

Do not add deterministic education classifiers, semantic style gates, model
generated prices, external sends or state migrations. Preserve optional quote
failures as placeholders. Keep old frozen owner payloads immutable. Run this
library's synthetic tests, consumer suites and `bash scripts/test-all`.

For new generated-news headlines, normalize the first cased subject character
without lowercasing names or rewriting an exact ticker prefix. Keep this
nonblocking and preserve raw forwarding, specialized Swing/status output,
and old frozen messages.

## Company News contract (subject-v2)

New ordinary company-news claims require `subject.company` with exactly
`business_home` (`ID`, `US`, `GLOBAL`, or `UNKNOWN`), `listing_status`
(`listed`, `private`, `pre_ipo`, `formerly_listed`, or `unknown`), and
`security_market` (`ID`, `US`, or empty). The subject retains its source-grounded
`kind`, `name`, and exact supporting `evidence`. Noncompany subjects have no
company details. Reject unknown fields and contradictory subject/route pairs.

Every card focuses on one company, public or private. Counterparties can supply
necessary context; do not duplicate a connected transaction. Use natural
headlines naming the company, without a mandatory ticker prefix. Report the
event, figures, timing and source-supported significance without inventing a
stock-price implication. Keep IPO plans and former tickers qualified.

Route by primary business home: `id_stocks_news` for Indonesia,
`us_stocks_news` for the US, and `global_company_news` for elsewhere or unknown.
An exchange, publisher location, source language or legal shell does not
establish business home. Missing configured company destinations are terminal
audited skips with a routing warning, not Macro fallback or later backlog.

Security identity is separate from destination. Only a verified current
security belonging to the focus company permits a ticker and optional tracker.
Source-mentioned tickers also require independent verification in v2. Private,
pre-IPO, formerly listed and unresolved companies have no empty stock fields.
Supported quote markets remain ID and US; a Global company may have a US quote,
and companies listed only on other exchanges remain text-only.

Existing v1 leases, prepared cards, delivery destinations and operations retain
their original contract. Raw forwarding, Swing/Board and Stock Information
retain their specialized behavior. See the accepted
[design](../docs/specs/2026-11-03-company-news-format.md).
