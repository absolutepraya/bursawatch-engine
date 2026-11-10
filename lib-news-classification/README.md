# News subject classification

`bin/news_subject.py` is the shared contract for ordinary Company, Industry,
and Macro news. Existing source-analysis agents identify the central subject
and quote its supporting evidence in the same analysis call. Owners validate
the subject against their supplied source and derive the destination category.
No source name, headline template, company list, sector keyword list, or
ticker position decides a category.

Company identity and subject classification are separate: a source-grounded
company name can produce Company News without a verified ticker or quote.
Sector-wide stories remain Industry News when companies are examples. Broad
economic stories remain Macro News when companies or sectors are examples.
Independent company stories split; a connected transaction stays together.

`news_subject.py` has no I/O. The separate `news_identity.py` performs bounded
read-only Yahoo Finance searches for exact company-name or exact symbol and
exchange matches. Exact symbol queries can return the provider's company name
and, when available, a matching record's headquarters country as a hint. The
country and exchange do not establish primary business home by themselves.
For an uppercase four-letter IDX ticker, the lookup searches its `.JK` symbol
first, then tries the unqualified ticker if necessary. It accepts only the exact
symbol on the Jakarta exchange, preventing a same-named foreign security or
another company's name from being substituted.
When the focus name is just the ticker, the quoted focus evidence must also
begin with the verified issuer or directly pair that issuer with the ticker.
Ticker-only mentions can therefore remain text-only even when a market lookup
returns a security. For a named focus, the evidence's first sentence or line must name it, so a company
mentioned only in a later sentence stays a counterparty.
A matching issuer elsewhere in the source is insufficient.
An unresolved lookup says why in `reason`: `no_match` (the provider answered and has no record), `ambiguous`, `error`, `timeout` or `busy`. Only `no_match` lets an IDX symbol-only subject be forwarded as the sender wrote it.
It has no credentials, source state, model calls, or message delivery.
Owners expose `lookup-company` through their managed wrappers. An externally
proposed ticker is independently verified before selection is persisted. When
the source directly binds a product name to an explicit ticker, owners may
verify that exact ticker even when the legal company name differs from the
source wording; ambiguous or indirect mentions remain unresolved;
unresolved identity falls back to company-name Company News without a tracker. Owners retain source eligibility, market coverage, intake, leases,
frozen destinations, and delivery receipts. Specialized Swing and Stock
Information retain their separate contracts. Old frozen output is never
reclassified. A lease records the new contract before requiring its subject
object, so an already outstanding legacy lease can settle normally.

Run `python -m pytest -q lib-news-classification/tests`. Deploy this library
before its consumer owners through the reviewed release manifest or the
separately approved library deployment helper.

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

## Industry geography

New industry classifications include `subject.industry` with exactly `region`:
`ID`, `US`, `GLOBAL`, or `UNKNOWN`. Route by the central industry market, not
publisher, source language, currency, company example or listing exchange:
`id_industry_news`, `us_industry_news`, or `global_industry_news`. Other-country,
worldwide and unresolved geography use Global. US sector indices and US Big
Tech aggregates are US; Malaysian palm oil and global oil shipping are Global.
Company stories still focus on one company; industry examples do not create
duplicate company cards. Industry cards have no company ticker or price block.
Missing configured destinations are terminal audited skips with a visible
warning, never an Indonesia or Macro fallback. Industry metadata is an additive
subject-v2 extension; retained legacy subjects, prepared cards, destinations
and operation identities keep their saved contract.
