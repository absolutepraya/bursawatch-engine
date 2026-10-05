# Morning brief price coverage and delivery research

Research date: 4 October 2026. Design source: `bb03cdb`; current source inspection: Bursawatch main `9102eaf`. Findings and recommendations only. No product implementation, production-state inspection, scheduler changes, or Discord publication occurred. Provider rights and alternatives are recorded in the [companion research](2026-10-04-morning-brief-provider-coverage-and-rights-research.md).

## Result

The sampled conglomerate price history is technically available, but public automated use is not approved by this check. All 188 mapped tickers have the recent aligned price history required for five 10/3 rotation observations. Dated market caps and complete sector membership remain unverified, so this does not prove the 90-percent market-cap coverage condition or that all 34 baskets qualify. The existing delivery owner supplies durable individual operations, not an atomic morning publication or a deadline guarantee.

## Live price and catalog checks

The unchanged [Arthara CSV](references/konglo_tickers_arthara_2026-09-22.csv) contains 210 memberships, 34 groups, and 188 unique tickers. Read it with UTF-8 BOM handling (`utf-8-sig`). Group memberships overlap intentionally.

A bounded, key-free Yahoo chart sample ran from 19:42:38 to 19:42:44 WIB on 4 October. It made one GET per symbol with `range=6mo`, `interval=1d`, and dividend/split events, three concurrent requests, a 12-second timeout, no retries, and a stop rule for HTTP 429. All 191 requests returned parseable chart results: 188 mapped equities, IHSG, and two sector-index candidates. Access availability does not establish permission for recurring collection; no further Yahoo collection is recommended until the rights finding is resolved.

Endpoint pattern: `https://query1.finance.yahoo.com/v8/finance/chart/{encoded-symbol}?range=6mo&interval=1d&events=div%2Csplits`. The [IHSG response endpoint](https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE?range=6mo&interval=1d&events=div%2Csplits) is a live data observation, not a documented supported API contract.

| Check | Observed result | Limit |
| --- | --- | --- |
| IHSG `^JKSE` | 122 daily OHLC observations from 2 April through 2 October | Not independently reconciled to IDX official sessions or prices |
| 188 mapped equities | 126 to 130 positive daily closes each, latest 2 October | One point-in-time sample, not a service-level commitment |
| Recent alignment | Every mapped equity has positive finite close and adjusted close on all latest 18 IHSG dates, 9 September through 2 October | No cap weights collected; no weighted coverage proof |
| Constant recent series | None of the 188 is constant across those 18 dates | Does not establish that every observation represents a trade |
| `IDXENERGY.JK`, `IDXFINANCE.JK` | One close each, dated 2 October | Insufficient for sector-index rotation |
| Corporate-action metadata | 104 equity responses include dividends; four include splits: DSSA, MEGA, MLPT, RAJA | Events in a six-month response, not verified corporate-action completeness |

The equity responses and IHSG do not share identical full histories. BBCA has four dates absent from the IHSG response: 14, 15, 27, and 28 May. Do not infer official trading days from one provider's stock timestamps, take the union of dates, or convert missing index observations into zero returns. The cause of these discrepancies was not established.

An independent key-free [Twelve Data IDX instrument catalog](https://api.twelvedata.com/stocks?exchange=IDX) returned 944 rows. All 188 mapped ticker strings appear in it. Catalog membership establishes discovery only, not available price history, adjustments, entitlement, latency, or display rights. This is a useful acceptance-test universe for a licensed-provider evaluation.

Temporary response data and summary remain outside Git at `/tmp/morning-brief-yahoo-coverage-20261004.json` and `/tmp/morning-brief-yahoo-summary-20261004.json`. They contain no credentials. The method and aggregate observations are retained here; market-data response files are not repository artifacts.

## Calculation and data-quality consequences

These are deductions from the agreed formula, not new user decisions:

1. Five latest positions require **18 aligned closing levels**, yielding 17 one-session returns. The earliest displayed position is `t-4`; its momentum uses `X(t-7)`; that ten-session return starts at closing level `t-17`. Fetch extra history for gaps and validation, rather than exactly 18 dates.
2. For complete valid mapped caps `m_j`, calculate coverage as `sum(eligible m_j) / sum(all mapped m_j)`. At coverage of at least 0.90, a defensible normalization is `w_j = m_j / sum(eligible m_j)` across one eligible member set for the entire chart history. This makes a fully invested included-member basket and must be disclosed as such. Keeping original weights without normalization implicitly allocates the omitted share to cash and is a different method. Normalization remains a recommendation pending agreement.
3. Daily constant-percentage weighting and ten-session compounding reproduce the selected fixed-snapshot illustration. They are different from weighting ten-session member returns directly or deriving holdings and letting weights drift. Keep the selected formula intact.
4. Determine whether the selected price field is split-adjusted price return or dividend-adjusted total return. Comparing dividend-adjusted member returns against an IHSG price index changes the interpretation. Recommended starting basis: compatible split-adjusted price returns versus IHSG price return, with explicit treatment of rights issues and other capital changes. Do not assume a field named adjusted close implements that exact basis.
5. Missing observations and suspensions must be handled explicitly. A repeated close can be a provider carry-forward, a genuine unchanged trade, or suspension. Do not manufacture a valid-price-coverage result through unconditional forward filling. If action treatment cannot be verified, exclude the member consistently, recalculate cap coverage, and suppress an ineligible basket.
6. Three visible months and RSI(14) need a longer retrieval range. The mathematical seed needs 15 closes; Wilder smoothing remains sensitive to the initialization. Use extra warm-up observations, preserve the chosen seed/method, and compare against a known reference on identical closes. The six-month IHSG sample provides enough history for that evaluation, not proof of indicator equivalence.
7. Record weight `effective_at`, `retrieved_at`, weekly `refresh_due_at`, and fallback expiry separately. A retrieval timestamp alone does not prove when caps were measured. Express the approved one-extra-week allowance against the missed scheduled refresh, then test holidays and failed refreshes. The exact refresh weekday and boundary remain to be chosen.

## Delivery evidence at current main

Inspected source, not production evidence:

- [`models.py`](../../../../service-bursawatch-discord-delivery/bin/discord_delivery/models.py) limits content to 2,000 characters, permits attachment-only creates, and disallows `message_reference` in create payloads. The shared client has the same restriction. A closing-review literal reply therefore requires a separately reviewed contract extension; a stored message link does not require this extension.
- [`store.py`](../../../../service-bursawatch-discord-delivery/bin/discord_delivery/store.py) blocks successors behind earlier nonterminal operations with the same ordering key. Both delivered and rejected operations unblock successors. This is ordering, not dependency success or an atomic multi-message batch. A separate ordering key does not prevent another publisher from interleaving in the channel.
- [`discord_gateway.py`](../../../../service-bursawatch-discord-delivery/bin/discord_delivery/discord_gateway.py) adds a deterministic nonce and disables mention parsing. [`worker.py`](../../../../service-bursawatch-discord-delivery/bin/discord_delivery/worker.py) reconciles uncertain creates. The client waits on the same operation and returns the latest receipt; acceptance or a wait timeout is not a delivery receipt.

Official [Create Message documentation](https://docs.discord.com/developers/resources/message#create-message) confirms the 2,000-character content limit, multipart files, reply references, and a nonce uniqueness window of only a few minutes. That window cannot substitute for a durable ledger across a delayed restart. Official [rate-limit documentation](https://docs.discord.com/developers/topics/rate-limits) requires respecting returned retry delays; outage or rate-limit time can exceed the publication budget.

### Recommended publication contract to settle before implementation

Preserve the agreed IHSG text, IHSG image, sector text, sector image, conglomerate text, conglomerate image sequence. Freeze both source evidence and final publication payloads; persist per-step operation key, digest, attachment identity, result, and Discord message ID. Use a run identity containing trading date and publication revision. Restart recovery reuses the same accepted keys and bytes instead of rerendering or regenerating text.

| Condition | Recommended behavior |
| --- | --- |
| Generated analysis unavailable before publication begins | Select deterministic facts-only version from the frozen bundle, once; keep that version immutable |
| Chart missing before its create is accepted | Record the omission, publish the available section text with a missing-chart notice, skip the unavailable image step |
| Create accepted but still pending | Query the same operation; do not create a replacement operation |
| Response lost / create outcome uncertain | Reconcile; do not infer absence from a timeout or advance a dependent step as though delivery succeeded |
| Required text rejected | Stop its dependent image; persist the partial-publication failure rather than relying on the ordering queue to stop it |
| Delivered steps followed by interruption | Resume only unfinished steps; preserve earlier messages and the morning text anchor |
| Analysis finishes after facts-only publication was accepted | Keep the original morning publication; do not silently replace it or introduce a second morning outlook |
| 08:00 reached during delivery failure | Record missed deadline and partial receipts; later retry expiry and reader-visible late-publication policy still require a decision |

Reserve delivery time before 08:00. Waiting until exactly 08:00 to choose fallback cannot meet an 08:00 delivery deadline. A configurable earlier assembly cutoff, for example 07:55, is a recommendation, not a newly confirmed requirement. Prebuild the deterministic fallback from frozen 07:30 inputs so a hung agent cannot prevent it from being selected. Neither a six-message batch nor recovery latency is proven until isolated fake-transport interruption cases are exercised in future implementation.

Existing source contracts are architectural evidence only. The competition entry must independently satisfy its new-repository and reuse rules. No copying of current Bursawatch implementation or use of its live sender is approved by this research.

## Trading calendar and optional-source access

The official [IDX holiday page](https://www.idx.co.id/id/tentang-bei/jadwal-libur-bursa) exists, but native fetching returned 403. Serper's fallback scrape exposed a 2026 calendar image at `https://www.idx.co.id/media/k2qp2iay/2026_ind2_page-0001.jpg`; fetching the image also returned 403. The calendar's date contents were not verified. A separately located [2026 exchange holiday announcement](https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Peng-00171%20Libur%20Bursa%202026-No.%20Peng-00171BEI.POP09-2025.pdf) is a discovery lead, not an extracted or validated calendar. Cache an official dated calendar and handle later amendments; weekday-only scheduling is insufficient.

Official pages exist for [UMA](https://www.idx.co.id/id/berita/unusual-market-activity-uma), [suspensions](https://www.idx.co.id/id/berita/suspensi), and [special-monitoring-board securities](https://www.idx.co.id/id/perusahaan-tercatat/daftar-efek-pemantauan-khusus). UMA and monitoring-board native fetches were blocked; complete machine-readable intake and historical transitions have not been verified. A current membership list is not an entry/exit event feed. Absence of collected announcements must not be presented as no restrictions.

For macro catalysts, the [Federal Reserve calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) was directly readable and is a suitable dated primary source for FOMC events. The official [Bank Indonesia 2026 RDG schedule announcement](https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/sp_2730825.aspx) was discovered, but native fetch timed out and the fallback scraper received an access-denied page. This is source discovery, not verified ingestion coverage. Optional sections may be omitted with an accurate availability notice; these feeds should not block the fixed morning core when its evidence floor is met.

## Remaining evidence needed

- A licensed price provider's account-level sample covering IHSG OHLC and all mapped equities, compatible action adjustments, response dates, freshness, bulk budget, and the specific Discord/public-demo display permission.
- Complete dated sector membership and numeric cap weights for every mapped member, with a verified effective date; then measure the actual 90-percent cap coverage rather than ticker-count coverage.
- Official calendar contents and update path; verified coverage for any optional UMA, suspension, FCA, corporate-action, and macro sections included in the product.
- Agreement on normalization/action basis, weekly snapshot boundary, earlier fallback-selection time, and late/partial delivery policy. These choices remain design work.

## Follow-up: universe and calendar reconciliation

The official [IDX stock list](https://www.idx.co.id/id/data-pasar/data-saham/daftar-saham) remained inaccessible to native fetching, but the Serper fallback scrape returned the first ten rows and a total of 962 entries. Twelve Data's public IDX catalog returned 944 rows in the same investigation. These counts are not necessarily the same instrument universe or as-of date. They are a reconciliation warning, not proof of exactly 18 missing ordinary shares. Compare normalized symbols, instrument types, listings/delistings, and effective dates before defining complete sector coverage. All 188 conglomerate ticker strings match the provider catalog; that does not settle the broader sector universe. The fetched IDX table did not supply sector membership, and the official classification PDF could not be extracted, so Sectors classification remains the previously permitted fallback to evaluate.

Serper's indexed text for the official [2026 holiday announcement](https://www.idx.co.id/StaticData/NewsAndAnnouncement/ANNOUNCEMENTSTOCK/Exchange/Peng-00171%20Libur%20Bursa%202026-No.%20Peng-00171BEI.POP09-2025.pdf) explicitly lists 14, 15, 27 and 28 May 2026, the four dates found in BBCA's history but absent from the IHSG response. This is stronger evidence that the extra stock rows fall on planned exchange holidays, but the PDF still returned 403 and the fallback PDF scrape failed. The complete calendar, amendments, and the cause of the provider's extra rows remain unverified. Do not populate a production calendar solely from search snippets.

Recommended acceptance sequence: obtain the authoritative amended calendar, normalize dates in Asia/Jakarta, exclude non-session rows before arithmetic, and require prices for the same verified sessions across IHSG and included members. A provider's latest stock date cannot substitute for a verified session calendar.

### Bounded account-level acceptance sample

Before paying for or integrating an alternative price source, test JKSE and representative mapped names including BBCA, a recorded split name such as DSSA, and an officially verified suspended or newly listed name when identified. Pin XIDX, daily interval, split adjustment, and a history window spanning the relevant action. Verify currency, session dates, actual OHLC, action consistency, missing/stale behavior, prior-session finalization by the cutoff, and remaining credits. Expand to all 188 only after the small sample and account entitlement are understood. No credential or paid-history test has been performed in this continuation.

The public-source investigation now yields a concrete validation sequence, but cannot prove Sectors account response fields, cap dates, or Twelve Data history without account access. Provider contact, a subscription purchase, and implementation remain separate actions.

## Subsequent user decisions

The user approved normalization to 100 percent of eligible members, split-adjusted price returns excluding dividend reinvestment, 07:55 fallback selection, and unfinished-step publication retry expiry at 08:15 with late labeling. These supersede the unconfirmed recommendations in this research record. The parent spec records the full eight-decision round and the intended Sectors numerical source for both custom rotation views, with Chart-IMG separately rendering the IHSG candles. Historical Yahoo/Twelve Data findings are not current integration choices. Provider capabilities and quota remain unverified beyond the small Sectors metadata sample.
