# Shared ordinary-news classification

This library owns the source-grounded subject schema, shared semantic model
instruction, and deterministic subject-to-route validation. It does not infer
categories from keywords, tickers, publishers, templates, or section names.
`news_subject.py` performs no I/O. The separate `news_identity.py` allows only
bounded read-only Yahoo company/security discovery, never arbitrary URLs,
source-state mutation, model calls, delivery, or extra news facts. Require
unique normalized company-name or exact-symbol and exchange agreement; ambiguity or failure
retains company-name Company News without a tracker.
For an explicit IDX ticker, first search its exact `.JK` symbol and accept only
the corresponding Jakarta-listed equity, with a bounded unqualified fallback.
An exact source product-name and ticker pair may support ticker lookup, but an
indirect association cannot. When a subject name is indistinguishable from a
proposed ticker and differs from the provider's issuer name, require focus
evidence naming the verified issuer or directly pairing it with the symbol.
A ticker headline, cashtag or stock reference alone does not bind a named
focus company to the issuer. A subject the sender names only by an IDX symbol is
forwarded instead: when the focus evidence contains the symbol and Yahoo
verifies the exact `.JK` symbol, it keeps its ticker, provided the model set
business home ID, the US market positively has no record of the symbol (a US
issuer with that symbol is a collision), the source writes no suffixed variant
such as `ROTI.B`, and the source does not tie it to a different legal issuer. A matching issuer elsewhere in the source is not focus
evidence. Treat other-market conflicts as ambiguous.
For a named focus company, naming it in the first sentence or line of the evidence is enough; a later mention is a counterparty.
A dropped ticker prefix becomes `Name: headline` for a real company name. A name that is only the unverified symbol stays unprefixed, because a `TICKER:` prefix marks a verified security.
This is a forwarder: an IDX subject the sender names only by a four-letter symbol that the focus evidence contains, and which Yahoo has no record of at all (lookup `reason: no_match`), keeps that symbol as written and its tracker falls back to placeholders. A timeout, provider error or ambiguous result still drops the ticker.
Otherwise retain the company story without a ticker. Optional provider headquarters country is a hint,
not proof of the primary business home, and never changes the route on its own.

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
