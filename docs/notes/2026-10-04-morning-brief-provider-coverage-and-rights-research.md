# Morning brief provider coverage and publication rights

Research date: 4 October 2026. Design investigation only. The initial public-source pass used no credential or paid request. The bounded account follow-up below made three authenticated Sectors requests: one HTTP 403 and two HTTP 200 responses. No provider contact, production write, or client implementation was performed. This supplements the [morning brief design spec](2026-09-27-bursawatch-morning-brief-design-spec.md); it does not change the agreed formula or chart-source boundary.

## Finding

**Superseding user direction:** Sectors only. Twelve Data is ruled out; its findings below remain an investigation record, not a current shortlist or subscription recommendation. The user has filled `SECTORS_API_KEY` in the ignored project-scoped `lib-sectors/.env`, linked into the design worktree. The first request was denied, but two diagnostic follow-ups succeeded; the small metadata sample is verified below.

Technical price availability and permission to automate or publish it are separate gates. Yahoo remains technically useful for bounded investigation, but a working public chart URL does not establish either permission. EODHD and Twelve Data expose commercial licensing paths; neither has yet been validated as a licensed end-to-end source for this exact Discord product. The alternative-provider catalog findings below are retained only as historical research under the superseding Sectors-only instruction.

Evidence categories below distinguish **documented**, **live sampled**, **indexed only**, and **unknown**. Provider documentation examples are not our own live measurements.

## Provider comparison

| Candidate | Coverage evidence | Publication/access evidence | Remaining gate |
| --- | --- | --- | --- |
| Yahoo Finance | Earlier price samples are retained in the design spec; this research does not repeat the full price survey. | Official general terms require prior permission for automated collection and constrain commercial reuse. | Obtain applicable permission and resolve regional/product terms; successful downloads are insufficient. |
| EODHD | Jakarta exchange catalog exists; documented daily OHLC and adjustment APIs. IHSG symbol and actual IDX history completeness remain unknown. | Personal terms prohibit display and redistribution, including repackaged information; commercial quote path exists. | Confirm exact IHSG coverage, required rights, source provenance, latency and commercial quote. |
| Twelve Data | Live key-free catalog: 944 IDX equity records and an Indonesian index record `JKSE`. | Terms provide explicit external-display/redistribution paths through appropriate rights/add-ons or agreement. | Verify daily OHLC history, adjustment semantics, all required symbols, account entitlement, quote and external-chart rights. |
| Direct IDX data services | Official indexed catalog offers EOD and historical products. Native page/PDF fetching failed in this session. | A direct subscription path exists, but this product's contract and price are unverified. | Request applicable EOD/historical and derived/display terms after authorization; no contact made. |

## Yahoo: stronger access-rights evidence, incomplete display conclusion

**Documented via Serper page scrape after native HTTP 999:** [Yahoo general terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html), Section 4, require express prior permission for automated collection; they also restrict commercial reuse and derivative distribution without written permission. Regional applicability and any separate data license remain unresolved. The appropriate conclusion is that this session has not established a permitted automated public product.

**Indexed/body discrepancy:** the search excerpt for [Yahoo's exchange/provider help](https://help.yahoo.com/kb/SLN2310.html) says redistribution is forbidden, but the fresh scrape omitted that blanket sentence. It instead identified provider-specific restrictions and Indonesia's `.JK` listing. Do not promote the search excerpt into a conclusively fetched current blanket clause. A homemade image and attribution alone do not establish permission. No supported volume allowance or SLA for the chart URL was found.

## EODHD: viable commercial inquiry, not a $19.99 public-feed approval

**Documented:** [EODHD terms](https://eodhd.com/financial-apis/terms-conditions) distinguish private analysis from group/business use and prohibit personal users from displaying or redistributing original or repackaged information. The same page cautions about indicative pricing and accuracy. Confirm provenance for the specific IDX/IHSG feed rather than assume official exchange closes. [Commercial licensing guidance](https://eodhd.com/financial-apis/commercial-vs-personal-license-use) directs commercial users toward a tailored quote.

[Personal pricing](https://eodhd.com/pricing) lists $19.99/month for EOD all-world, 100,000 daily calls and 1,000 requests/minute. These are listed personal-plan figures, not a quote or permission for this product. [Jakarta exchange catalog](https://eodhd.com/exchange/JK) establishes the `JK` exchange identity; no authenticated index lookup or OHLC sample was made.

[Daily-history documentation](https://eodhd.com/financial-apis/api-for-historical-data-and-volumes) documents raw OHLC, close adjusted for splits and dividends, and split-adjusted volume. Fully adjusted history can change after later dividends, so freeze the fetched calculation inputs and refetch a consistent window. It offers split-adjusted OHLC separately. Ordinary exchanges update roughly two to three hours after close, while some index feeds update later; verify IHSG specifically against the 07:30 cutoff. History requests cost one call per ticker regardless of length. Do not assume adjusted stock returns are economically comparable with a price-only IHSG series; selecting a return basis remains a design decision.

[Bulk documentation](https://eodhd.com/financial-apis/bulk-api-eod-splits-dividends) offers one exchange/day for 100 calls, versus 100 plus the named-ticker count for filtered requests. Bootstrap per-ticker histories and routine full-exchange daily refresh are therefore different cost shapes. Critically, its extended `MarketCapitalization` is current even when requesting a historical date. A historical price-row date is not a historical cap date. Bulk `date` can also fall back to a previous session or latest data; validate returned dates. JK-specific coverage and entitlement were not sampled.

## Twelve Data: live instrument discovery, prices still untested

**Live sampled without credentials:** these public metadata endpoints returned JSON with `status=ok`:

- [IDX stock catalog](https://api.twelvedata.com/stocks?exchange=IDX): `count=944`, including IDR common-stock records such as AADI, AALI and ABBA, with `exchange=IDX` and `mic_code=XIDX`.
- [Indonesian index catalog](https://api.twelvedata.com/indices?country=Indonesia): `count=1`, `symbol=JKSE`, `name=Jakarta Composite Index`, IDR, IDX/XIDX.

These are instrument records, not 944 complete histories, verified current official membership, or OHLC evidence. Historical depth, adjustments and missing prices still require an entitled bounded sample. Public [exchange page](https://twelvedata.com/exchanges/xidx) extraction was poor, so the JSON catalogs are the stronger discovery evidence.

**Documented:** [Twelve Data terms](https://twelvedata.com/terms), Sections 2 and 3, make external display/redistribution conditional on express tier/add-on or written rights and applicable third-party requirements. Their derived-data definition excludes reconstructable underlying data. A price candle image should not simply be assumed exempt. Confirm separately permission for candles, calculated RSI, basket-return/quadrant graphics, historical caching, Discord attachment retention, public demo recording, attribution and audience. No public commercial quote was verified here.

## Sectors metadata: cheap export plausible, effective date remains a blocker

Context7 was queried first for documentation, then the current primary references were inspected. [Companies screener](https://docs.sectors.app/api-references/v2/indonesia/screener/companies) documents IDX classifications, IDR market cap, pagination up to 200 rows, one credit for structured queries and three for natural-language queries. Its example exposes values in `query_values`, but the description of `include_query_values` is inconsistent with that example. No cap-effective timestamp appears in the reviewed schema. No authenticated request was made.

Inference: `ceil(N/200)` credits per export is only a lower-bound estimate if one structured query returns all required fields reliably. Freeze stable ticker ordering, reconcile pagination totals and missing classifications/caps, and distinguish collection time from economic effective date. A successful weekly HTTP fetch must not reset freshness for old economic data.

[Per-stock daily data](https://docs.sectors.app/api-references/v2/indonesia/transaction/daily) explicitly documents dated caps and one credit per ticker/window up to 90 calendar days. It can be evaluated as a dated-weight fallback, using only metadata under the agreed price boundary. For 188 unique mapped conglomerate names, one window would be 188 credits before failures or retries. Full sector-universe cost depends on actual membership. Corporate actions, cross-provider share units and membership-effective dates still need validation. No Sectors public-display or long-term cache grant was established by this investigation.

## Official-data and optional-section limits

[IDX data services](https://www.idx.co.id/en/products/idx-data-services/) and its indexed [2026 catalog](https://www.idx.co.id/media/rzfl4wzy/20260513_idx-data-services-catalogue-pricelist-non-ab-2026.pdf) are credible procurement starting points, but native fetches failed. Product-level OHLC fields, derived-display terms and fees remain unknown. No complete current UMA, suspension or FCA change feed was established in this pass. Keep those sections optional until current official coverage is demonstrated. Foreign-flow, news and event evidence do not repair absent candle data or weight timestamps.

## Concrete next investigation gates

1. For a licensed shortlist candidate, prove JKSE complete daily OHLC, warm-up closes and representative IDX histories, including a split, dividend, suspension and a newly listed name. Validate session timestamps and provider adjustments against primary events.
2. For metadata, prove complete classification/cap export plus economic effective date. If that date is absent, obtain provider clarification or evaluate explicitly dated daily caps; do not relabel fetch time as cap time.
3. Obtain a concrete rights/price answer for the exact product: two calculated rotation images and one IHSG candle/RSI image per trading morning, public Discord attachment retention, public demo, cached input history and no raw feed resale. Provider contact needs separate user authorization.
4. Freeze a compatible return basis and correction policy before comparing basket and IHSG returns. Then apply the agreed 90-percent cap coverage requirement; symbol-count coverage alone cannot satisfy it.

The parent investigation owns full conglomerate price sampling, local rotation arithmetic and delivery behavior. This note does not assert production health or authorize implementation.

## Follow-up: concrete provider capability and access checks

Additional key-free catalog calls on 4 October returned `access.global=Pro`, `access.plan=Pro`, and `access.plan_business=Venture` for both the [IDX exchange](https://api.twelvedata.com/exchanges?country=Indonesia&show_plan=true) and [IHSG JKSE](https://api.twelvedata.com/indices?country=Indonesia&show_plan=true). Discovery is free; these fields do not promise free historical-price entitlement. Account-level capabilities still need a bounded test.

Twelve Data's current [OpenAPI document](https://api.twelvedata.com/doc/swagger/openapi.json), checked through Context7 and directly fetched as JSON, documents daily OHLC histories, output sizes from 1 to 5,000, and explicit price-adjustment modes. Daily bars use exchange-local dates even when a timezone parameter is supplied. Use `mic_code=XIDX` to disambiguate equity symbols, and pin the adjustment mode rather than depend on a default. `adjust=splits` is a suitable candidate to test for compatibility with IHSG price returns; rights issues and other capital changes still require verification. Batch operations charge the sum of their constituent requests, not one credit per batch.

The [pricing explanation](https://twelvedata.com/pricing) states one time-series credit per symbol. Thus the mapped 188 equities plus IHSG imply 189 credits for one fetch per unique symbol, before retries, extra validation windows or global instruments. Sector and conglomerate memberships should share a deduplicated price cache. For a complete reconciled sector universe of `N` equity symbols, the corresponding estimate is `N+1`, not `N+188+1` when all conglomerate names already occur in the sector universe. These are arithmetic budget estimates, not paid requests or measured service limits.

The [business pricing page](https://twelvedata.com/pricing-business) separates Venture external display from Enterprise external distribution. Whether retained Discord images and a public demo fit display, distribution, or a special agreement remains unresolved. Its dynamic page exposes several credit and price configurations, so a specific product quote is still needed. Do not buy a plan solely because the catalog names Venture.

The provider's [EOD guidance](https://support.twelvedata.com/en/articles/12682324-end-of-day-eod-pricing-market-data) distinguishes preliminary and confirmed prices after exchange reconciliation. It does not establish an IDX-specific confirmation deadline or expose a confirmation flag in its displayed sample. A date and HTTP success alone cannot prove a confirmed prior-session close by 07:30. Include that condition in the bounded account sample and any later provider clarification.

### Dated caps: bulk-close endpoint does not solve this

The [Sectors daily full-universe close reference](https://docs.sectors.app/api-references/v2/indonesia/transaction/close) returns symbol, date and close, omits tickers with no recorded close, and costs one credit per page with a maximum of 30 rows. Its reviewed schema has no market cap. Therefore it cannot replace the dated-cap check and must not be repurposed into chart prices under the agreed separate-provider boundary.

A minimal Sectors account check should start with one structured companies request limited to three known tickers, stable symbol ordering, and `include_query_values=true`. It must verify actual numeric caps, sector fields, pagination and any effective-date metadata before scaling. A candidate filter referencing the desired fields can test their inclusion, but an example or filter is not proof that all required fields are returned. If cap time remains absent, one explicitly dated per-stock daily request can test whether dated caps are available, without using its price fields for charts. Budget the initial probe separately from a 188-name export; no authenticated request was made here.

A cheap full metadata export remains possible only if the returned field contract is verified. Filtering away missing caps would conceal mapped-member omissions, so reconcile every mapped ticker against the export before declaring a basket eligible. Missing weights make the cap coverage denominator unknown, even when every ticker has usable prices.

### Rights source availability

Serper did not locate a usable Sectors license page; Brave then surfaced the official enterprise offering, whose indexed text describes commercial licensing. Native Sectors home/FAQ/enterprise requests returned 429 and the fallback scrape failed. No further requests were made to those pages after the repeated limit. This supplies a procurement lead, not a grant for publishing Sectors-derived metadata or analysis. Account terms or provider clarification remain necessary.

Configuration ownership is now recorded in the [shared Sectors client architecture](2026-10-04-shared-sectors-client-architecture.md). The worktree-root placeholder was replaced by a canonical project `lib-sectors/.env`; machine-wide secret storage is explicitly ruled out.

## Authenticated bounded check, 4 October 2026

At 23:28:57 WIB, the first authenticated request to `https://api.sectors.app/v2/companies/` returned **HTTP 403**. The user-filled key was loaded privately from the canonical project `lib-sectors/.env`, whose mode was verified as `0600`. No key, authorization header, raw error body or credential-bearing exception was printed or stored in these notes. Redirects were disabled and no retry was attempted.

The structured parameters were:

```text
where=symbol in ['BBCA','BBRI','TLKM','BBCA.JK','BBRI.JK','TLKM.JK'] and market_cap > 0 and sector != '' and sub_sector != ''
order_by=symbol
limit=3
include_query_values=true
```

This filter was a small response-field probe, not a complete-universe export: filtering out missing fields would be inappropriate when later measuring basket eligibility. Both documented bare-symbol and response-suffix forms were included to avoid assuming how the screener matches symbols.

The run had a ceiling of three documented credits, one each for a structured screener, BBCA daily history, and IHSG daily history. It stopped after the first denial. **One authenticated request was attempted; the two history requests were not sent.** The structured screener is documented as costing one credit, but whether this failed request consumed any quota was not measured. No remaining-credit figure is claimed.

HTTP 403 establishes denial of this request, not its cause. Key validity, account endpoint entitlement, and provider or network access restrictions remain possible explanations. No error response was retained for classification. Consequently no numeric cap, classification, pagination, effective date, stock history, or IHSG account coverage was verified. Check the account dashboard for an active key and access to the v2 Companies Screener before another bounded attempt; do not assume a plan upgrade is required.

The [index-daily reference](https://docs.sectors.app/api-references/v2/indonesia/transaction/index-daily) confirms the planned IHSG path `/v2/index-daily/ihsg/` and date parameters. Its documented response contains `index_code`, `date`, and closing `price`, which still does not establish true OHLC candles. Both planned history probes used 1 September to 2 October 2026, within the documented 90-day maximum. These are planned requests, not sampled responses.

### Setup-page and request-header diagnosis, 4 October 2026

The user supplied screenshots showing zero recorded requests and pointed to the [v2 setup overview](https://docs.sectors.app/get-started/v2/overview#get-your-api-key). That page documents an Insider account and a raw API key in the `Authorization` header, matching all three probes. Context7 also surfaced conflicting Bearer examples in other recipes; the setup overview and screener endpoint reference are the applicable raw-key contract here. No key or account setting was changed.

At 23:33:52 WIB, a simplified structured request (`limit=3`, `order_by=-market_cap`, `include_query_values=true`) returned HTTP 200 with three rows and numeric-cap field names. It used the same urllib transport and key, but an explicit `User-Agent: python-requests/2.32.3` header. The response was JSON and the server header was `cloudflare`.

At 23:34:22 WIB, the original structured query reproduced above also returned HTTP 200 with that User-Agent. Its three returned rows were:

| Symbol | Positive numeric market cap, documented IDR units | Sector | Subsector |
| --- | --- | --- | --- |
| BBCA.JK | 744,458,026,950,000 | Financials | Banks |
| BBRI.JK | 462,133,707,687,960 | Financials | Banks |
| TLKM.JK | 222,889,987,350,000 | Infrastructures | Telecommunication |

The cap, sector and subsector were under each row's `query_values` (`symbol` remains a top-level field). Pagination reported `total_count=3`, `showing=3`, `limit=3`, `offset=0`, `has_next=false`, and `has_previous=false`. This verifies a filtered three-name response, not multi-page full-universe coverage. The returned object and row fields had no explicit cap-effective date; retrieval time must not stand in for that date.

**Superseding access finding:** the key works for the v2 Companies Screener. The original query succeeding after changing the User-Agent makes request-header filtering the likely explanation for the initial 403. This is an inference: the initial error body was not retained, and these sequential requests cannot exclude a transient restriction. The screenshots establish the dashboard's visible zero activity at the supplied capture, not why the first request was absent from it or whether failed attempts consume credits.

The original ceiling is now exhausted conservatively: **three request attempts total**, each against an endpoint documented at one structured-query credit. Two succeeded and one was denied; actual quota decrement is still unmeasured. No BBCA or IHSG history request was made. Further account sampling needs a fresh stated budget. Future client transport should set a stable identifying User-Agent explicitly and classify sanitized error bodies before attributing a denial to account entitlement. No client code or live deployment was added.

## Sector counts and incremental price budget, sampled 5 October

At 00:12:26 WIB, a bounded five-request metadata export completed with HTTP 200 on every page. Each request used `/v2/companies/`, `where=sector IS NOT NULL`, `order_by=symbol`, `limit=200`, `include_query_values=true`, and offsets 0, 200, 400, 600, 800. Page sizes were 200, 200, 200, 200, 162. The provider consistently reported `total_count=962`; 962 distinct symbols were collected without duplicate or missing sector fields. Completeness is for that non-null-sector filter, not independently reconciled official constituents or unclassified instruments. These were structured requests documented at one credit each; actual quota decrement was not read.

| Sectors classification | Stock count |
| --- | ---: |
| Basic Materials | 114 |
| Consumer Cyclicals | 161 |
| Consumer Non-Cyclicals | 131 |
| Energy | 91 |
| Financials | 107 |
| Healthcare | 41 |
| Industrials | 66 |
| Infrastructures | 71 |
| Properties & Real Estate | 93 |
| Technology | 47 |
| Transportation & Logistic | 40 |

All 188 distinct ticker strings in the user's unchanged conglomerate CSV occur in this metadata export. Therefore the sampled union is **962 unique stocks**, not 962 plus 188. This verifies symbol discovery and classification presence, not price availability, dated cap validity, or qualification under the 90-percent cap-coverage floor.

The [full-universe close endpoint](https://docs.sectors.app/api-references/v2/indonesia/transaction/close) documents a single dated session, at most 30 rows per page, and one credit per page. If the close feed contains approximately the same 962 symbols, a complete daily pull would require `ceil(962/30)=33` credits, plus one [IHSG closing-history](https://docs.sectors.app/api-references/v2/indonesia/transaction/index-daily) credit, approximately **34 credits per trading day**. A hypothetical 22-session month is **748 credits**, before metadata/weights, initial history, corporate-action verification, corrections, missing-data recovery or failures. These are documented-rate estimates; the daily-close feed was not called in this check and its actual pagination/count may differ because tickers lacking a recorded close are omitted.

Proposed incremental flow: fetch the last completed verified session once, append closes to the shared local history, reuse them for all sector/konglo baskets, and run rotation calculations locally. Holidays and weekends need no new completed-session price pull. A second cron should reuse that session's cache rather than repeat the provider fetch. Corporate-action adjustment must be verified before treating raw bulk closes as the confirmed split-adjusted inputs.

The earlier 189-credit estimate described a per-symbol conglomerate historical bootstrap, not the recommended ongoing daily request pattern. Initial historical loading remains a separate cost. Account allowance remains unknown, so no claim that 748 credits fits the user's free allocation is made. Exact sector membership is now sampled once as requested; no automatic refresh or DB implementation was introduced. A private sanitized membership sample is held outside Git at `/tmp/bursawatch-sectors-sector-membership-20261005.json`; no key or raw authorization material is present.
