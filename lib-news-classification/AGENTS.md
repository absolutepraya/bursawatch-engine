# Shared ordinary-news classification

This library owns the source-grounded subject schema, shared semantic model
instruction, and deterministic subject-to-route validation. It does not infer
categories from keywords, tickers, publishers, templates, or section names.
`news_subject.py` performs no I/O. The separate `news_identity.py` allows only
bounded read-only Yahoo company/security discovery, never arbitrary URLs,
source-state mutation, model calls, delivery, or extra news facts. Require
unique normalized company-name and exchange agreement; ambiguity or failure
retains company-name Company News without a tracker.

Keep category and security resolution separate. Company, industry and macro
are semantic subjects. An unknown ticker never changes a company into Macro.
Source owners enforce the new contract at claim and submission boundaries;
already frozen output and outstanding legacy leases remain compatible.

Run `python -m pytest -q tests`. Include cases with company examples in sector
stories, sector context in company stories, tickerless named companies,
industry-focused government policy, and broad policy with company examples.

## Company News contract (subject-v2)

New ordinary company-news claims require `subject.company` with exactly
`business_home` (`ID`, `US`, `GLOBAL`, or `UNKNOWN`), `listing_status`
(`listed`, `private`, `pre_ipo`, `formerly_listed`, or `unknown`), and
`security_market` (`ID`, `US`, or empty). The subject retains its source-grounded
`kind`, `name`, and exact supporting `evidence`. Noncompany subjects have no
company details. Reject unknown fields and contradictory subject/route pairs.

Every card focuses on one company, public or private. Counterparties can supply
necessary context; do not duplicate a connected transaction. Use natural
headlines prefixed with the verified current ticker and a colon when available;
otherwise use the company name. Report the event, figures, timing and
source-supported significance without inventing a
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
