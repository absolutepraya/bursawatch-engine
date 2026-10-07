# Morning brief feasibility validation, 5 October 2026

Design source: [morning brief spec](2026-09-27-bursawatch-morning-brief-design-spec.md). This is a bounded data and public-documentation investigation, not product implementation or a production-health claim. No job, service, destination, external message, provider contact or public chart was created.

## Five-credit account sample

The run used five authenticated requests, each documented at one credit, no retries and no redirects. All returned HTTP 200. A stable explicit User-Agent and raw-key Authorization were used. The key stayed in the ignored canonical project `lib-sectors/.env`; no key, authorization header or raw exception was printed. No quota/usage/rate header appeared in the sampled responses.

| Probe | Verified result | Limit |
| --- | --- | --- |
| `/v2/close/?date=2026-10-02&limit=30&offset=0` | 30 positive closes, all dated 2 October; pagination total 962 and next offset 30 | First page only, not full-universe price coverage |
| `/v2/index-daily/ihsg/?start=2026-09-01&end=2026-10-02` | 24 positive index closes, distinct dates | No OHLC, volume or finalization flag |
| `/v2/daily/BBCA/` for the same window | 24 complete positive OHLC/volume/close/cap rows; all dates match IHSG exactly | One stock, not every mapped member |
| `/v2/company/corporate-actions/DSSA/` | Reports splits dated 9 April 2026 (ratio 25) and 18 July 2024 (ratio 10) | Provider report, not independently verified issuer event |
| `/v2/daily/DSSA/?start=2026-04-01&end=2026-04-17` | 12 rows spanning the reported split, with continuous-looking closes and dated caps | Does not establish provider-wide adjustment semantics |

BBCA's 2 October close was 6,100 and dated cap was IDR 744,458,026,950,000, matching the earlier screener sample's numeric cap. This gives a dated sample and local consistency check, not a cheap dated-cap export contract for all members or proof of point-in-time share-count fidelity.

DSSA returned close 2,680 and cap IDR 516,270,054,400,000 on 8 April, then close 3,120 and cap IDR 601,030,809,600,000 on 9 April. Both increased by the same factor, about 1.164179, so implied shares computed as cap/close stayed constant. There is no 25-fold price discontinuity in the returned history. This suggests split normalization in that historical series, but cannot establish whether all closes are split-adjusted, whether raw daily bulk closes use the same convention, or how corrections affect stored prices. **Do not blindly apply the reported split again**, which could double-adjust the series. Verify convention, ratio direction and consistent stored price units before implementing an adjustment ledger.

A one-member arithmetic sample using BBCA and IHSG confirmed that direct 10-session close ratios and compounding the ten daily returns agree. The 24 aligned levels were sufficient for all five 10/3 observations. This is not validation of a complete sector/conglomerate basket or its weighted coverage.

Private sampled responses are outside Git at `/tmp/bursawatch-sectors-feasibility-20261005.json`, mode 0600, with no credentials or HTTP headers. The prior 962-member mapping sample is also outside Git. No DB or cache implementation was introduced.

## Actual account budget, user screenshot

The user supplied the dashboard screenshot showing:

| Pool | Remaining | Expiry shown |
| --- | ---: | --- |
| Sectors Hackathon 2026 | 988 | 8 October 2026 |
| Credits | 600 | 17 March 2027 |
| Total | 1,588 | Each pool retains its own expiry |

The screenshot shows 12 requests this period and says the hackathon pool is used first. The 12 recorded successful requests match two diagnostic screeners, five membership-export pages and five feasibility probes. The initial HTTP 403 is absent from that successful count. Actual provider balance should still be read from the dashboard, rather than inferred from arbitrary request counters.

These are finite pools, **not a verified recurring 1,000-credit monthly allowance**. Published [Insider pricing](https://sectors.app/pricing) describes 5,000 monthly credits, but it does not apply automatically to this hackathon account. A historical [free-credit announcement](https://sectors.app/release/3.0.0) also does not establish recurring renewal. No public remaining-credit endpoint was found in the [OpenAPI schema](https://raw.githubusercontent.com/supertypeai/sectors_api_docs/main/schema.json); the collaborative browser returned Authentication required on both status and open, so the user screenshot is the account evidence.

The daily estimate of 33 stock-close pages plus one IHSG request is supported by the first bulk page's total 962. At 34 credits/session, a hypothetical 22-session month is 748 credits before weights, initialization, corrections, other crons and retry costs. The 600-credit non-hackathon pool covers at most 17 full price-only sessions, not ongoing free operation.

An illustrative 18-session full-universe history initialization would cost 18 times 33 = 594 bulk-page credits, plus one IHSG history request if not already cached, about 595 credits before weights and action checks. The completed first bulk page and IHSG sample can reduce duplicate requests when eligible. This is an estimate, **not approval for the full load**. A per-symbol initialization for all 962 members costs about 962 stock requests and may also return dated caps, so compare total validated input cost rather than select a bootstrap solely on closing-price cost. A cheap screener snapshot still lacks a verified cap-effective-date field. Expiry hour/timezone and grant renewal were not established.

## Corporate-action and billing documentation

The public schema exposes a marketwide `/v2/corporate-actions/` calendar. Specify `type=stock_split`: it documents one credit for that action type and up to 90 days. Omitting the type requests all seven action types and costs seven credits. Split fields include an ex-date, symbol, ratio and optional related dates. Neither completeness nor reverse-split direction was sampled here.

The [Sectors changelog](https://docs.sectors.app/api-references/v2/changelog) documents successful/404 billing and normally no credit charge for 400, authentication denials, 429 or server errors, with a natural-language screener exception. The daily/bulk-close schemas do not expose a split-adjustment flag or adjusted-close field. They document dated IDR caps, but not historical share-count fidelity or correction policy. Public Sectors display/cache rights remain unverified because complete current terms could not be fetched; provider examples do not grant redistribution rights.

## Free-chart decision and remaining render inputs

The user chose **free accounts, prioritizing LuxAlgo SMC plus RSI divergence**. Omit Volume from the primary saved layout to fit the [TradingView Basic two-indicator limit](https://www.tradingview.com/pricing/). Its one saved layout can hold this dedicated chart. The [built-in RSI](https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/) has a Calculate Divergence option, so the divergence does not require a third study. Retain the previously confirmed swing structure/recent order blocks, RSI(14), light theme, hidden grids, ticker text and daily framing.

[Chart-IMG documentation](https://doc.chart-img.com/) separately lists BASIC at 50 requests/day, 800 by 600, with provider watermark. The later private renders below verify key access and indicator loading. Saved-profile cleanup, precise framing and legibility still need validation.

Local validation placeholders were initially prepared at the project root and subsequently moved into the user-requested shared package: canonical ignored `/Users/absolutepraya/Documents/Projects/Hermes/lib-chart-img/.env`, mode 0600: `CHART_IMG_API_KEY` and `CHART_IMG_LAYOUT_ID`. The design worktree links to that file, with a blank `.env.example` template. This is project-scoped validation configuration, not a live cron/service environment or a VPS provisioning choice. The Sectors credential stays in its confirmed `lib-sectors/.env`. Future runtime wiring and worktree-helper changes remain implementation work.

## Public chart rights are a concrete gate

The current [Chart-IMG terms](https://chart-img.com/terms), read through a successful Serper scrape after empty native extraction, limit personal/free content to personal use and require written consent before provider data/documents are made public. This leaves public Discord/demo use uncleared, even though private rendering is technically available. [TradingView policies](https://www.tradingview.com/policies/) allow attributed chart snapshots but cannot override the rendering provider's terms. Preserve TradingView and LuxAlgo identification. [LuxAlgo's indicator page](https://www.luxalgo.com/library/indicator/smart-money-concepts-smc/) confirms the script's CC BY-NC-SA license; copying code and publishing captured output are distinct rights questions.

No provider was contacted. A concrete clarification for a later authorized contact is: May a free Chart-IMG account render one daily IDX Composite chart from a shared TradingView layout using public LuxAlgo SMC and built-in RSI divergence, retain visible attribution, and post the PNG in a public noncommercial Discord morning brief and hackathon demo? Confirm whether this needs written consent or a specific plan, and whether attachment retention is permitted.

## Remaining gates

- Confirm split/adjustment behavior across stored bulk sessions and historical daily series; verify representative primary corporate actions before normalizing.
- Prove a complete dated cap snapshot and full member price coverage without hiding missing weights.
- Choose a bounded initial-history cost and ongoing credit ceiling respecting the two expiry dates and other cron consumers.
- Complete saved-layout cleanup and verify the resulting private render; resolve public posting rights before public integration. Key/layout access is verified.
- Verify the official amended calendar, selected evidence corpus and optional source access.
- Keep competition eligibility and production rollout separately reviewed. The behavior spec is agreed, but these facts can expose a new design frontier.

## User-directed monthly budget, 5 October

The user directed budgeting **1,000 Sectors credits per operating month**, with manual top-ups when the credit balance depletes. This is the user's chosen spending envelope, not an assertion that the current account has a recurring subscription grant. No purchase or automatic top-up was performed or authorized.

Use a conservative 23 IDX trading sessions in the monthly plan:

| Workload | Budgeted credits |
| --- | ---: |
| Daily stock closes + IHSG | 782 |
| Weekly cap metadata export | 25 |
| Daily stock-split calendar | 23 |
| Retries and price corrections | 70 |
| Other Sectors evidence requests | 50 |
| Unallocated reserve | 50 |
| **Total monthly ceiling** | **1,000** |

Prices: 33 full-universe pages plus one IHSG request per session, 23 times 34 = 782. The weekly cap line assumes five structured pages per refresh and at most five refreshes in the month, 25 total. It is a budget allocation, not proof that a complete economically dated cap snapshot can be obtained by this screener path. If this date contract fails, do not silently substitute 962 per-stock requests per weekly refresh: use the agreed bounded snapshot fallback/omission and revisit the economical input method. The bulk page count must also be checked against the frozen selected universe and any provider-wide growth that changes required pages.

The optional marketwide stock-split calendar is budgeted at one credit per session only with `type=stock_split`; never omit the type and incur the seven-type charge. This ledger remains a validation aid, not an instruction to double-adjust already normalized prices. Retries/corrections and other evidence calls have explicit separate allocations; callers share cached responses and debit one coordination ledger. Additional crons must fit the same envelope or receive a deliberately revised allocation. Unused allocations may be reassigned within the ceiling, with records preserved. A host ledger cannot enforce unrelated consumers on other machines; dashboard balance remains the account authority.

Historical initialization is a separate one-time budget: approximately 595 credits for 18 full-universe closing sessions plus IHSG before dated weights/actions, reduced by eligible existing cached inputs. It is not repeated every month and no full load has been run. If initial loading must share the first month's 1,000-credit ceiling, the full steady-state allowance cannot also be spent that month; schedule or reallocate explicitly. The user's existing expiring hackathon pool is a candidate setup funding source, not automatic permission for an unbounded fetch.

## Independent DSSA split corroboration

[DSSA's issuer financial statements](https://dssa.co.id/documents/Dian_Swastatika_Sentosa_Tbk__Maret_2026_.pdf), PDF page 159 (printed page 148), Note 47, confirm the split became effective 9 April 2026 at 1:25, increasing shares from 7,705,523,200 to 192,638,080,000. Both sampled Sectors cap/close ratios equal the post-split 192,638,080,000 shares, including the pre-event 8 April row. That strongly supports retrospectively split-normalized prices with compatible cap units in this sample; the universal bulk/stored-history adjustment convention still needs verification. A preliminary issuer announcement targeted a different date, so use the later financial statement for the effective event.

The [shared Chart-IMG library direction](2026-10-05-shared-chart-img-client-architecture.md) supersedes the initial root environment placement. The provider key is shared; each caller retains explicit layout/profile ownership. No client code was added. Subsequent private validation renders are recorded below.

## Private shared-layout render, successful 5 October

The user filled `lib-chart-img/.env` and confirmed layout sharing for `vQj9F2JC`. At 00:56:14 WIB, one private `POST /v2/tradingview/layout-chart/vQj9F2JC` requested `IDX:COMPOSITE`, interval `1D`, PNG, 800 by 600, with a 90-second timeout and no retries. The x-api-key was loaded privately from the canonical package file, mode 0600, and was never printed. No session cookies were used. The non-storage endpoint returned HTTP 200, `image/png`, 95,549 bytes, a valid PNG signature and dimensions 800 by 600, after 9.23 seconds. No public storage URL or Discord post was created.

The private artifact is `/tmp/bursawatch-ihsg-layout-vQj9F2JC-20261005.png`, mode 0600, outside Git. Visual inspection confirms daily IDX Composite candles, light background, LuxAlgo SMC rendering, an RSI Divergence Indicator pane with length 14, a visible symbol/header, and retained TradingView/Chart-IMG marks. The displayed close is 6,036.888, matching the sampled Sectors 2 October close. That match supports prior-session consistency but the image response alone does not provide an explicit last-bar timestamp or prove generic cutoff enforcement.

The saved layout is not yet the agreed final profile: it contains `Vol` with an error marker, a visible range around May through October rather than three months, hidden bearish divergence labels (`H Bear`), and prominent blue diagonal lines. SMC's exact minimal swing/order-block settings were not verified from the screenshot. Shared Layout does not document study-list removal or styling overrides, so removing the volume study and adjusting indicator settings must happen in the saved TradingView layout, followed by saving and another bounded private render. Zoom/movement controls may tune framing but do not establish an exact calendar window without verification.

The user supplied a TradingView notice that the vendor does not provide volume for this symbol and instructed removing Volume altogether. Both primary and fallback IHSG profiles now omit Volume. The current primary render proves working key, shared-layout access and indicator loading, not finished styling, current-volume support, layout immutability, public display rights or production delivery.

## Private layout recheck, 5 October at 06:43 WIB

One further request used the same non-storage endpoint and payload, a 90-second timeout, no cookies and no retries. It returned HTTP 200, image/png, 95,549 bytes and dimensions 800 by 600 after 9.56 seconds. The private artifact `/tmp/bursawatch-ihsg-layout-vQj9F2JC-recheck-20261005.png` has mode 0600 and is byte-for-byte identical to the first render. Visual inspection still shows the erroring Volume study, May-to-October framing, hidden bearish divergence labels and blue diagonal annotations.

The captured profile therefore has not changed. This does not distinguish an unsaved layout from provider caching or another saved-layout issue. Do not repeatedly render the same unchanged profile. Remove Volume, save the three-month framing, disable hidden divergences and verify minimal SMC settings in TradingView before the next bounded recheck. No public chart, layout edit or production operation occurred.

## Cheap cap dating, documentation result and reopened decision

The [companies screener](https://docs.sectors.app/api-references/v2/indonesia/screener/companies) documents market_cap, last_close_price and annual outstanding_shares[YYYY]. Its documented field list and public schema expose no cap-effective date, latest-close date, current dated share count or as-of query parameter. Five 200-row pages can collect 962 caps for five credits, but their retrieval timestamp cannot be presented as the economic date of those caps. Five refreshes consume the 25-credit allocation before retries, which belong to the separate shared retry allowance.

The [company report](https://docs.sectors.app/api-references/v2/indonesia/report/company-report) overview example includes latest_close_date with market_cap and last_close_price. This is a per-symbol, per-section one-credit route, not a bulk substitute, and the example alone does not guarantee synchronized cap and price dates. [Stock daily data](https://docs.sectors.app/api-references/v2/indonesia/transaction/daily) remains the documented per-symbol dated-cap route. [Total IDX cap](https://docs.sectors.app/api-references/v2/indonesia/transaction/idx-total) is an aggregate and cannot determine member weights.

Multiplying a dated close by shares inferred from an undated cap/price pair does not establish dated shares. Issuance, buybacks, conversions, splits and retrospective adjustments can invalidate that inference. Matching screener prices to dated bulk closes supports price alignment only, not a universal cap-effective-date guarantee. The BBCA sample match remains useful limited evidence.

This reopens a user decision: preserve the economically dated-cap requirement pending provider confirmation, or explicitly accept weekly provider snapshots labeled with collection time and an unverified underlying effective date. The latter preserves the affordable cap-weighted illustration but weakens its freshness claim; collection age, not economic cap age, would govern the weekly refresh and extra-week fallback. Neither alternative has been adopted by this investigation. No additional authenticated Sectors requests were made.

Initial history funding is also pending: the approximately 595-credit closing-history estimate is separate from the agreed 1,000-credit steady operating month. A proposed bounded setup envelope of 600 credits would cover that estimate, not all possible setup validation, weights or actions. The full initial load remains unperformed and implementation is not authorized by a budget decision.

## User decisions confirmed after the cap-date investigation

The user accepted collection-dated weekly provider cap snapshots with the underlying effective date explicitly unverified. Collection age governs the weekly refresh and one-extra-week fallback. The economic-date requirement is superseded, not verified. Valid cap values, complete snapshot coverage, the 90-percent basket coverage threshold and compatible price units remain necessary.

The user also accepted a separate one-time history allowance of at most 600 credits for the approximately 595-credit bootstrap estimate, outside the 1,000-credit monthly operating budget. Reuse eligible existing inputs; do not expand the setup allowance automatically for additional work. No full load or implementation occurred in this confirmation turn.

## Full-universe close pagination, bounded follow-up

The next validation stated a ceiling of 32 additional Sectors credits and reused the cached first 30-row page for 2 October. Sequential requests used at least one second between completed calls, no redirects and no automatic retries. The first 25 new pages succeeded, then attempt 26 returned HTTP 429 at offset 780. The run stopped immediately and preserved its partial artifact at `/tmp/bursawatch-sectors-full-close-coverage-20261005.json`, mode 0600, outside Git.

The 26 collected pages contain 780 distinct symbols, all with positive closes and the requested 2 October date. Their declared pagination total remains 962; there are no duplicates or symbols outside the imported membership set. After normalizing the provider's .JK suffix against CSV tickers, 159 of the 188 conglomerate members have collected closes. The remaining 182 universe symbols, including 29 conglomerate members, are **uncollected**, not proven provider omissions. This incomplete prefix cannot validate full-universe or cap-weighted basket coverage.

The new successful requests cost an estimated 25 credits at the documented rate; the changelog normally exempts HTTP 429 from credit billing, but dashboard decrement was not independently verified. The error's rate-limit headers were not retained, so this run cannot establish Retry-After, the account's exact request window or the cause of the limit. Do not retry immediately, infer one request per second is safe for sustained batches, or consume the 600-credit history allowance to bypass the limit. Shared-client design needs resumable page checkpoints, a coordinated account-level request budget and bounded cooldown behavior. No recurring client, DB or job was implemented.

## Official calendar evidence and distribution terms follow-up

The indexed official [IDX 2026 calendar announcement](https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Peng-00171%20Libur%20Bursa%202026-No.%20Peng-00171BEI.POP09-2025.pdf), Peng-00171/BEI.POP/09-2025 dated 23 September 2025, lists 22 October sessions and no October holidays except weekends. On that published schedule, the preceding session for Monday 5 October is Friday 2 October; remaining scheduled October dates are 5 to 9, 12 to 16, 19 to 23 and 26 to 30. Native IDX fetching returned 403 and scraper fetching failed, so evidence here is indexed/extracted official text, not a newly downloaded complete PDF. No later 2026 amendment was found, which does not prove none exists. A September 2026 adjustment result concerns the 2027 calendar and must not be applied to 2026.

The current [Sectors terms](https://sectors.app/terms-of-service), marked last updated 26 September 2026, were retrieved successfully by Serper after native fetching returned 429. This supersedes the earlier unavailable-terms finding. General permitted-use language covers personal noncommercial or internal business use; a separate section explicitly addresses Sectors Financial API and commercial use through an Enterprise agreement. Generic prohibited-use clauses restrict systematic compilation and automation/extraction, while the documented API necessarily enables programmatic requests. Public evidence does not reconcile those generic restrictions with the account's API-specific or hackathon agreement, nor expressly settle durable caching or public distribution of derived rotation charts. Do not infer that API access resolves these questions.

[Chart-IMG API documentation](https://doc.chart-img.com/) explicitly describes chart-storage endpoints for worldwide publication and lists BASIC storage retention of 14 days. Its [terms](https://chart-img.com/terms) also describe personal/free use restrictions and written consent before provided data/documents are made public. Searches did not locate an explicit official FAQ reconciling those statements for a scheduled public Discord digest. Record **conflicting provider guidance**, rather than definitive permission or a definitive blanket prohibition. A [publisher Discord bot example](https://github.com/hawooni/cf-chart-img-discord-bot) establishes technical posting capability, not this account's licensing contract. The private non-storage validation used here remains distinct from a public-storage or Discord publication.

No provider was contacted, no account agreement was changed, and no public artifact or live job was created.

## Coverage resume completed within the original credit ceiling

After a multi-minute quiet interval, one bounded request at offset 780 succeeded. The six remaining offsets then succeeded with five-second pauses between completed requests and no further automatic retries. This supports a temporary rate-window explanation for the earlier denial, but does not establish the exact account limit or a guaranteed safe pace. Public documentation does not publish a numeric v2 request window or reset policy. The [security recipe](https://github.com/supertypeai/sectors_api_docs/blob/main/recipes/api-security/01-securing-api-usage.mdx) gives generic backoff guidance; the [changelog](https://docs.sectors.app/api-references/v2/changelog) separately identifies quota error codes, so HTTP 429 alone should not be treated as proof of temporary throttling.

The final artifact contains **962 distinct positive closes, all dated 2 October**, matching the complete imported 962-symbol membership set with zero missing, unexpected or duplicate symbols. All **188 unique conglomerate members** have closes after .JK normalization. Every sector's collected count matches the earlier metadata export: Energy 91, Basic Materials 114, Industrials 66, Consumer Non-Cyclicals 131, Consumer Cyclicals 161, Healthcare 41, Financials 107, Properties & Real Estate 93, Technology 47, Infrastructures 71, Transportation & Logistic 40.

The follow-up used 32 successful new pages, one reused cached page and one HTTP 429 denial: 33 new attempts, **32 estimated billable credits**, within the stated ceiling. Actual balance was not read back from the account dashboard. No history-bootstrap allowance was consumed. This verifies complete positive one-session price coverage and recoverable pagination, not active trading status, unchanging future daily coverage, split-adjusted history consistency or valid cap-weighted basket calculations. A positive close can still represent an inactive or suspended security; eligibility must remain a separate decision backed by evidence.

## Complete cap-value coverage and cross-endpoint checks

A further bounded investigation stated an eight-credit ceiling and completed exactly eight successful requests, with five-second pauses between calls and no retries. Five structured `/v2/companies/` pages used `where=sector IS NOT NULL`, `order_by=market_cap`, `limit=200`, offsets 0/200/400/600/800 and `include_query_values=true`. Sorting by cap exposes cap values without filtering away null or nonpositive values. Pages contained 200/200/200/200/162 rows and each declared total 962.

All **962 distinct mapped stocks have finite positive cap values**, with no missing or unexpected symbols. All 11 sectors and all 34 conglomerate groups, covering the 188 unique CSV stocks, therefore have complete positive cap inputs in this collected snapshot. This validates the five-credit collection method and basic cap coverage, not economic effective dates, eligible historical member sets or future refresh quality. Record collection timestamp and the already agreed effective-date-unverified label. The private artifact is `/tmp/bursawatch-sectors-cap-and-unit-check-20261005.json`, mode 0600, outside Git.

The remaining probes requested historical full-universe close pages at offset 240 for 8 and 9 April, plus DSSA daily history for 1 September to 2 October. Both historical pages span CTBN through DNAR and **do not contain DSSA**. They cannot establish split-window cross-endpoint compatibility. Both declare total 956, versus 962 in October: historical pagination must use each requested date's actual result set and cursor, never infer a stock's historical page from its current position.

DSSA's latest daily row is dated 2 October, close 1,140 and cap IDR 219,607,411,200,000. Its daily close exactly matches the same-date completed bulk feed, and its cap exactly matches this screener snapshot. BBCA's screener cap IDR 744,458,026,950,000 also matches the cached 2 October daily cap. These are two consistent cap samples and two consistent current-price samples when including BBCA; they do not establish universal dated cap or split-adjustment semantics. No double adjustment was applied, no full history was loaded, and no product implementation occurred.

An independent offline join confirmed the counts and exact BBCA/DSSA matches. DSSA's September window consistently implies 192,638,080,000 shares from cap divided by close, matching the April 8/9 ratio. Earlier sampled April 1/2/6 rows imply slightly different quantities. Rounded adjusted closes could explain this, but the cause is unproven; do not use exact cap/close reconstruction as a universal share-count or action-validation contract.

## Historical DSSA cross-endpoint comparison resolved

Two additional successful requests fetched offset 270 for 8 and 9 April with limit 30, five-second spacing and no retries. Both pages contain DSSA. Bulk close is 2,680 on 8 April and 3,120 on 9 April, exactly matching the cached per-stock daily history on both sides of the independently corroborated 9 April 1:25 split. This resolves the earlier sampled-page gap and establishes cross-endpoint compatibility for this event. The private artifact `/tmp/bursawatch-sectors-dssa-historical-bulk-20261005.json` is mode 0600 and outside Git. Estimated cost is two credits; the full history allowance remains untouched.

Together with the post-split share-unit evidence, this sample supports already normalized historical prices in both endpoints. Never apply the reported split again solely because an action exists. It is not a universal adjustment contract, reverse-split test or point-in-time share-count guarantee. Keep the agreed exclusion of members with unhandled actions and the 90-percent cap coverage threshold for other events. This evidence can support a bounded implementation acceptance case later without inventing provider-wide guarantees.

## Saved-layout recheck and public TradingView inspection

The user confirmed saving the requested cleanup. One private non-storage rerender completed at 08:10:26 WIB: HTTP 200, image/png, 95,664 bytes, 800 by 600, 9.45 seconds, no cookies or retries. The artifact `/tmp/bursawatch-ihsg-layout-vQj9F2JC-saved-cleanup-20261005.png` is mode 0600. Its bytes differ from the earlier PNG, but it still visibly contains Vol, hidden bearish divergence and May-to-October framing.

The collaborative browser became available in this turn. Opening the exact public layout `https://www.tradingview.com/chart/vQj9F2JC/` in View Only Mode shows layout name Main (with a banana icon), Volume, LuxAlgo and RSI Divergence Indicator, matching the old profile. Its details pane states last market update 2 October 16:54 GMT+7 and close 6,036.8880. This strengthens the prior-session match for the inspected view but does not supply a general API image last-bar timestamp contract.

The mismatch is also present on the public TradingView page, so it is not explained solely by Chart-IMG image caching. Owner save failure is not established. [Sharing guidance](https://www.tradingview.com/support/solutions/43000606515-how-to-share-charts-in-view-only-mode/) identifies layout-specific URLs and warns that subsequent edits do not update copies. [Layout guidance](https://www.tradingview.com/support/solutions/43000692404-layouts-charts-drawings-indicators-and-their-interaction/) describes distinct layout URLs and multi-tab overwrite risk. [Saving guidance](https://www.tradingview.com/support/solutions/43000762820-the-changes-i-make-are-not-saved-in-my-layout/) describes explicit save behavior. None proves the current cause. Chart-IMG's resetZoom changes framing, not documented cache invalidation or study refresh.

Next diagnostic requires comparing the owner's updated layout URL/name with this public URL. If the owner uses a different ID, use the supplied corrected ID after explicit confirmation. If the same ID shows different saved/public states, investigate sharing synchronization. No copy, layout deletion, owner settings edit or sharing toggle was performed.

## Source-evidence read surface review

The [proposed read contract](2026-10-05-morning-brief-source-evidence-read-contract.md) records available normalized fields, provider-specific text and attribution limitations, absence of a bounded source-event window API, and the consistent snapshot needed for frozen selection. A Published Feed query is not a substitute for collected source evidence. Retention and actual accepted production coverage remain unverified. The incomplete original-publisher field reopens a narrow decision about disclosed canonical-publisher fallback versus excluding unattributable records. No new endpoint or credential was implemented.

## Owner URL confirmed and publisher policy settled

The user supplied the exact Indonesian owner URL with layout ID vQj9F2JC and accepted using available publisher metadata without additional origin-verification complexity. The spec and source-read proposal now record that settled policy.

The collaborative browser opened the exact supplied URL, including its symbol query, in View Only Mode. The page still identifies Main (banana icon), Volume, LuxAlgo and RSI Divergence Indicator. The localized host therefore does not explain the old shared profile. The owner and configured IDs match; no API key, layout ID or cookie change is warranted from this evidence. Investigate owner-save/shared-state synchronization rather than repeating API renders or alleging unsaved edits. No layout edit or sharing toggle was performed.
