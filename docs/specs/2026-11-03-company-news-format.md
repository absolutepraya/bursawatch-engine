# Company-news format design

Status: design accepted and implemented in the company-news feature branch.
The user accepted the decisions below on 3 November 2026 and subsequently
authorized implementation, PR, merge and deployment. Local tests and browser
checks establish source behavior; production adoption requires release proof.

## Accepted decisions

1. Company-news eligibility depends on a substantive company development,
   independently of whether the company is listed, private, preparing an IPO,
   or formerly listed. Financing, IPO plans, acquisitions, financial results,
   and material business developments can qualify. Routine promotion and
   generic product announcements still require a relevance judgment.
2. Every generated company-news headline uses natural descriptive wording.
   Remove the mandatory `<TICKER>:` prefix, including for listed companies.
   Name the focus company when central; verified tickers are separate context.
3. The body explains what happened, relevant figures, timing, and
   source-supported significance. Listing status appears when it explains
   the event. Market information is optional and applicable only to a
   verified security. Private-company news needs no price block or empty
   stock fields, and summaries must not invent a stock-price implication.
4. Each company-news card must focus on exactly one company, whether private
   or public. A source containing unrelated company developments produces
   separate company-focused items rather than one roundup.
5. A connected transaction may name counterparties as necessary context
   while retaining one focus company. Another company receives its own card
   only when the source supports a distinct development about it, rather
   than repeating the same transaction.
6. Relevant company-news coverage includes companies worldwide, within the
   configured sources and relevance rules. Listing country must not force
   company news into Macro.
7. Proposed IPO tickers and former tickers may appear as factual context.
   A price tracker requires a verified current security belonging to the
   focus company. An IPO plan does not establish an active listing, and a
   private subsidiary does not automatically inherit its parent's ticker
   or price tracker.
8. Retain separate Indonesia and US company-news destinations and add a
   destination for companies elsewhere. Private companies also belong in
   these geographic groups.
9. Worldwide news does not initially expand price-tracker support beyond
   Indonesian and US securities. Company news about other exchanges remains
   publishable without a price block. Broader quote support is a separate
   change; a destination group does not establish a security's quote market.
10. Replace the reader-facing category name Stock News with Company News
    to reflect public and private coverage. Swing remains its own category.
11. Route by the focus company's primary business home, independently of
    listing exchange. A US-based private company belongs in US Company News;
    an Indonesian company belongs in Indonesia Company News; a China-based
    Nasdaq-listed company belongs in Global Company News. A verified US
    security of that China-based company may still supply a USD tracker.
    The US destination therefore changes from US-listed to US-based company
    coverage. Destination classification and quote-market selection are
    separate decisions.
12. If a company is identified but its primary business home cannot be
    established, route eligible news to Global Company News without inventing
    a country. Global therefore includes companies outside Indonesia and the
    US, plus those with unresolved business-home attribution.
13. If a source profile lacks the required company-news destination, skip
    that delivery with a visible routing warning. Do not substitute Macro or
    accumulate a backlog to publish when configuration is added. Subsequent
    new eligible stories use the configured destination. Normal retries for
    already prepared or submitted deliveries retain their existing rules.

These decisions revise the ticker-led headline and listed-issuer language
in the [earlier shared format design](2026-10-02-universal-stock-news-format.md).
The shared [news glossary](../glossaries/stock-news.md) records the accepted
vocabulary. Worldwide coverage, three geographic destination groups, and
business-home attribution are accepted, including ambiguous-geography and
unavailable-destination behavior. Deployment configuration is separate work.

## Format illustration

The following company and facts are fictional and illustrate presentation
only. Actual cards retain their source provenance and supported facts.

**PT Contoh Nusantara menyiapkan IPO untuk mendanai ekspansi**

Ringkasan: PT Contoh Nusantara berencana menggunakan dana IPO untuk menambah kapasitas produksi. Perusahaan belum mengumumkan jadwal penawaran maupun nilai dana yang ditargetkan.

This private-company card belongs in Indonesia Company News, with no ticker
prefix, price tracker, or empty stock fields. Its IPO plan is retained as a
plan, without implying that shares already trade. Concise source material
does not need extra paragraphs to fill a template.

For a connected transaction, a headline such as "Company A agrees to acquire
Company B" can retain Company A as the focus. Company B is necessary context;
the transaction alone does not justify another card repeating the same news.

## Design completion

The interview has no remaining open product decisions. Implementation must
carry company identity, business-home routing, and optional security identity
separately, and align source-owner eligibility, shared rendering, validation,
publication taxonomy, and reader-facing settings with this contract. This
document does not choose new internal route keys or prescribe a migration.

## Inherited scope boundaries

The design concerns generated company-news cards across existing platform
sources. Existing raw-forwarding settings, specialized Swing behavior, source
provenance, relevance exclusions, and delivery ownership remain authoritative.
News is not relabeled Macro because its ticker, quote, or company-news
destination is unavailable. Existing prepared or submitted cards and their
retry identities remain frozen under their original contract. Historical
message cleanup is separate from this design.

The accepted naming and destination decisions describe intended behavior.
They do not create or rename live channels, change profiles, deploy code,
alter schedules, or authorize replay or backfill. Those operations retain
the repository's review and approval boundaries.

The implementation preserves legacy internal ID/US route keys and adds
`global_company_news`. Subject-v2 embeds company geography, listing status
and optional security market separately. Source owners enforce claim-time
compatibility, and the formatter uses security market rather than destination
for optional quotes. Typed Delivery Owner channel operations support the
approved destination provisioning without direct watcher Discord access.

Validation includes synthetic private/IPO/former-listing and cross-border
examples, terminal missing-destination behavior, full package suites, both web
checks, Workers packaging, and local sample-workspace destination save/read-back
at desktop and 375px widths. Live rollout and natural-run evidence remain
separate from these local checks.
