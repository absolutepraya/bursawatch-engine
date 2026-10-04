# BursaWatch After-Close Review: Design Spec

Status: draft design specification, updated 4 October 2026. This is a design record, not implementation or production-change approval. Preserve this extension while the morning brief is the active design priority. Further closing-review design and implementation can wait until the morning brief is ready.

## Scope and current decisions

Publish a concise review of the same IDX trading session, targeting **18:00 WIB**, with **one LLM run per daily closing review**. The later publication target is intended to allow more time for end-of-day data availability; the user's impression that other securities firms publish at 18:00 is motivation, not a verified provider schedule or data guarantee.

The [morning brief design spec](2026-09-27-bursawatch-morning-brief-design-spec.md) owns the morning outlook, 07:30 evidence cutoff, 08:00 deadline, basket definitions, chart-source boundary, and shared image theme. The closing review reuses the frozen morning record and that day's delivered IHSG text anchor. It does not rewrite the morning outlook or add new competition eligibility assumptions.

1. **Closing review and reply anchor, 4 October.** The first closing-review text must reply to that day's morning IHSG text message, not its chart. Start with the observed IHSG session and an honest comparison with the frozen morning outlook; follow with an updated IHSG chart. The user also requested market-activity text and a corresponding visual, plus only material intraday news. Closing sector and conglomerate movers use text without repeating rotation images, with the top three in each category ranked by daily basket return, even when every return is negative.
2. **Closing activity comparisons, confirmed 4 October.** Include trading value alongside share volume. Use rupiah trading value as the main activity figure and volume when informative; compare both with the previous session and the preceding 20 completed sessions' average. Report net foreign in rupiah and its five-session cumulative total. Match dates, units, coverage, and market scope; exact provider selection remains unresolved.
3. **Closing material events, confirmed 4 October.** Include zero to three qualifying events, selected for meaningful market, sector, or trading impact. Omit the entire event section when no event qualifies. Company size alone does not determine eligibility, and routine corporate actions are not included by default.
4. **Closing publication target, confirmed 4 October.** Target 18:00 WIB on the same IDX trading day. Publish the available review with unavailable metrics clearly identified rather than presenting older values as today's. This target is not a guarantee of provider availability or successful delivery. Use one LLM run for the daily review. The closing evidence cutoff and handling of a failed IHSG review itself remain open; no automatic late-data enrichment loop is planned.
5. **Outlook-review format, confirmed 4 October.** Keep the review short: morning view, actual outcome, and what matched or missed. Evaluate the close and observable conditions stated in the original outlook; do not reduce a conditional scenario to a simplistic win/loss label or invent unsupported intraday observations.
6. **Closing activity visual, confirmed 4 October.** Use a single activity image combining 20 trading sessions of daily net-foreign bars with compact trading-value and volume comparisons for today, the previous session, and the preceding 20-session average. The user confirmed 20 sessions after rejecting the shorter five-session chart. The five-session cumulative foreign-flow statistic remains a separate agreed summary figure.

## One LLM run and unavailable data

- Collect and validate dated market facts and eligible session news before the review's single scheduled LLM run. The precise collection cutoff and preparation start remain open.
- Deterministic helpers calculate returns and comparisons and render charts; those operations do not require another LLM run.
- Run the LLM once to compose the review from the collected evidence and the original morning outlook, then publish its frozen text and images in the agreed sequence.
- If a metric is still unavailable at publication, identify it as unavailable rather than substituting an earlier session, inventing a value, or delaying all available content.
- There is no automatic second LLM run or late-data edit loop in the current design. The earlier update suggestion is retained below as discussion history, not a required feature.
- Retrying delivery of an already composed, frozen publication is separate from generating analysis again. Retry and recovery rules remain a future design detail and must preserve stable keys and avoid duplicates.

## Publication layout and content

1. IHSG session-review text, posted as a reply to the morning IHSG text. Compare the stated scenario and conditions with observations without retroactively changing the morning call.
2. Updated IHSG chart image.
3. Market-activity text covering relevant foreign flow and trading activity, using the agreed comparison windows below.
4. Market-activity visual.
5. Material news during the session: major macro, industry, or stock events. Routine corporate actions do not qualify by default. The user's example of GOTO dominating market trading volume illustrates market relevance; it is not a verified claim about a particular session.

**Confirmed group ranking:** show the top three sectors and the top three conglomerate groups by that day's basket return, ranked from highest to lowest, even when all returns are negative. The user's clarification replaces "rose" with strongest daily performers: for example, -0.5 percent ranks above -1.0 percent. Do not filter to positive returns or relabel a negative return as a gain. Keep the actual signed percentage, with negative values using the down/negative color even for the first-ranked group. Compare each with the same session's IHSG return as previously recommended. Use the agreed market-cap-weighted baskets, not a change in relative-rotation quadrant. Their concise text belongs alongside the activity block; exact placement is still open. Do not repeat the morning rotation graphs in the closing review. Missing or insufficiently covered baskets must not be assigned zero returns to fill the ranking.

Each text post must remain at most 2,000 characters, including headings, links, and formatting. Split at section boundaries, with intentional text/image order and a separately saved anchor for the morning IHSG text. Other publishers may interleave posts, so adjacent posts must carry enough context to remain readable. The user wants short copy, not messages filled to the limit. Exact per-section length budgets and handling of interrupted publication remain open.

**Market-activity terminology and comparisons, now confirmed:** trading volume counts shares; trading value measures rupiah. A low-priced stock can dominate volume without dominating value or index contribution. Use trading value as the main market-activity figure and volume as supporting context where informative, comparing each with the previous trading session and the preceding 20 completed sessions' average (excluding the current session). Net foreign flow is signed buying minus selling; report the rupiah amount and the cumulative total of the latest five completed trading sessions, including the current session when finalized, instead of a percentage change across zero. These comparisons require matched market scope, dates, and coverage. Do not present a sum of a few active tickers as a market total, or close multiplied by volume as actual trading value. Actual source selection and insufficient-baseline handling remain open.

**Material-news gate, confirmed:** include zero to three major events, prioritizing observed market significance or a credible, sourced change in the market outlook rather than ticker size alone. When zero events qualify, omit the entire section rather than adding a no-news message. Distinguish a news catalyst from an observed activity anomaly and do not infer causation merely because both occurred that day. The 18:00 WIB publication target and explicitly unavailable metrics are agreed; the closing evidence cutoff and handling of an unfinished IHSG assessment still need decisions. The chosen workflow uses one LLM run and no automatic late-data enrichment loop.

### Closing-review data coverage checked 4 October 2026

Public official documentation and its [OpenAPI schema](https://github.com/supertypeai/sectors_api_docs/blob/main/schema.json) were checked without authenticated API requests or credit consumption. Documentation coverage is not a successful account-level data check.

- **Direct IHSG foreign flow:** [foreign flow by symbol](https://docs.sectors.app/api-references/v2/indonesia/brokers/foreign-flow-by-symbol) supports `IHSG` as a market-wide sum. `GET /v2/foreign-flow/IHSG/` accepts up to 90 days per request at one credit and documents net foreign inflow, buying/selling values in rupiah, and foreign share. This supersedes the older note's per-ticker-only assumption. Foreign origin is investor origin; unavailable nullable data must not become zero. Verify the returned date and market scope before comparison.
- **Market volume remains unresolved:** [per-stock daily data](https://docs.sectors.app/api-references/v2/indonesia/transaction/daily) contains shares volume, but no actual rupiah turnover. The paginated full-universe close feed contains only symbol, date, and close. Gathering every ticker's daily volume individually could consume hundreds of credits; no verified cheap market-volume total was found in the checked endpoints. Prefer a verified exchange market summary or another permitted aggregate provider rather than assuming this costly route is required.
- **Trading-value candidate is not yet a verified total:** [all-broker ranking](https://docs.sectors.app/api-references/v2/indonesia/brokers/top) can return all brokers when `n_brokers` is omitted, at two credits per date. Summing documented `gross = buy + sell` across all brokers and dividing by two is a possible turnover calculation, but is an inference requiring complete broker coverage and market-scope reconciliation against IDX. Do not label it official market turnover before that check.
- **Top activity is not a market total:** [most-traded ranking](https://docs.sectors.app/api-references/v2/indonesia/ranking/most-traded) caps `n_stock` at 10. Its adjusted ranking uses volume multiplied by closing price, not actual executed trading value. It could help select a notable activity observation, but cannot establish total-market volume or exact turnover.
- **Timing requires final-session data:** [IDX trading hours](https://www.idx.co.id/en/products-services/trading-hours-and-mechanism/) place closing matching at 16:00 to 16:01:59 WIB, post-closing through 16:15, and negotiated-market trading through 16:30. A report claiming all-market daily totals cannot treat 16:00 as the final boundary. The [Sectors freshness guide](https://docs.sectors.app/recipes/sectors-for-ai-agents/00-sectors-mcp-guide) describes end-of-day updates without a precise publication-time SLA in the checked material. The user confirmed an 18:00 WIB review target, not a guarantee of provider completeness; check dates and availability and identify missing metrics explicitly.

The chart-price source boundary remains unchanged: use the separately selected provider for IHSG OHLC and basket price histories. Foreign-flow and activity evidence are analysis inputs, not a reason to replace the agreed chart sources with Sectors.

## Delivery requirements and local evidence

**Local delivery-contract evidence, 4 October, not a production claim:** the historical design worktree's client and service enforce a 2,000-character content limit and support attachment-only posts. Their create-payload allowlists accept only `content` and `allowed_mentions`, so literal replies using `message_reference` are unsupported here. A reviewed shared client/service contract extension is required if this delivery path is chosen. Delivered receipts contain `message_id`; save the morning text receipt separately from its chart receipt. Ordering keys preserve operation order but are not an atomic publication batch: rejected earlier operations permit later steps, and other publishers can interleave. A future publisher must check confirmed receipts before advancing a dependent step and resume with the same immutable operation keys and frozen payloads. References: `service-bursawatch-discord-delivery/bin/discord_delivery/models.py`, `discord_gateway.py`, `store.py`, and `lib-bursawatch-discord-delivery/bin/bursawatch_discord_delivery/models.py` and `client.py`. This documents required future work without authorizing implementation or assuming competition eligibility of existing runtime code.

## Shared presentation and references

All closing images use padding, Hanken Grotesk, and the full [BursaWatch image theme](2026-09-27-bursawatch-morning-brief-design-spec.md#image-theme-supplied-by-the-user-4-october-2026): copper as the single focal accent; warm dark surfaces and text; green/red for positive/negative market values; no pure black or white; no text glow; no background gradients except the allowed subtle radial copper glow. The review requires an updated IHSG candlestick/RSI image and one activity visual. Sector and conglomerate rankings stay text, using the morning spec's market-cap-weighted baskets and its [dated conglomerate membership reference](references/konglo_tickers_arthara_2026-09-22.csv).

See [GLOSSARY.md](../../GLOSSARY.md) for the shared domain vocabulary. Preserve source links, as-of dates, selected and excluded evidence, the frozen generated output, and delivery receipts in the future submission's own records; these documents are not execution evidence.

## Discussion history and superseded proposals

- The first closing target was **17:00 WIB**. On 4 October the user replaced it with **18:00 WIB** to allow more time for data availability. Only the latter is the current target.
- The initial activity-chart suggestion showed five daily foreign-flow bars. The user requested a longer view, then confirmed **20 trading sessions**. This changes visual history, not the separately agreed five-session cumulative statistic.
- The initial wording described sectors and conglomerates that "rose." The user clarified that the top three are ranked by daily return even if every return is negative. These are top daily performers, not necessarily gainers.
- The proposed post-publication update would have edited only the affected closing activity text/image, with a visible update time, if a missing metric arrived later. An illustrative example was a 17:00 publication followed by a 17:15 metric arrival. Such an edit could have required another analysis run if fresh narrative interpretation was needed, or only deterministic refresh if it changed numeric fields. This was never approved. The user clarified the preference for one LLM run and moved publication to 18:00; the current spec therefore has no automatic late-data enrichment loop.

The preceding clarification record is retained here for provenance:

**Closing review and visual clarification:** the user agreed to the short morning-view / actual-outcome / matched-or-missed review format and the activity visual's general layout, while requesting more than five historical observations. Confirm the chart lookback rather than silently fixing it. The user requested an explanation of late updates, so no late-update approval is recorded: the proposal concerns an unavailable closing metric arriving after the 17:00 publication and potentially updating only the affected closing activity text/image with a visible update timestamp. The morning outlook remains frozen. Whether to update, the permitted time window, and the bounded update mechanism remain undecided.

## Open choices, deferred until the morning brief is ready

- Exact closing evidence cutoff and run start time before the 18:00 target.
- Aggregate volume and trading-value providers, consistent regular/all-market scope, account-level coverage, and credit budget.
- Handling of insufficient 20-session comparison history or incomplete basket coverage.
- Exact placement of sector and conglomerate ranking text in the activity block and the activity image layout.
- Fallback when the IHSG review itself cannot finish, and interrupted-delivery recovery.
- Literal reply support if using the inspected shared delivery path; no reply contract change is implemented by this spec.

A dashboard is not required. These deferred choices do not expand the immediate morning-brief scope.
