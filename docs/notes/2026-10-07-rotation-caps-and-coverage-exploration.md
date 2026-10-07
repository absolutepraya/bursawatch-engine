# Rotation cap sources and coverage exploration

Date: 7 October 2026. Scope: isolated Mac exploration, no production changes.
Worktree: `rotation-cap-exploration`, branch `absolutepraya/rotation-cap-exploration`.

## User direction

- Remove the 90-percent market-cap coverage threshold as a publication gate.
- Prioritize delivering a rotation for the usable constituents.
- Use the existing shared Sectors client for market caps, including conglomerates.
- Cache cap inputs for one month. Proposed precise implementation: 30 days from collection, rather than refreshing at every calendar-month boundary.
- Explore before implementing or changing production.

## Live API checks

The exploration used `lib-sectors` with the existing canonical ignored Mac credential. The client performed eight successful, bounded requests with no retries or redirects. Provider responses and the temporary coordination ledger remain outside Git, in `/tmp/bursawatch-sectors-cap-exploration-20261007/`.

Three `/v2/company/report/{symbol}/?sections=overview` responses:

| Stock | Positive market_cap returned | Yahoo cap available in prior preview |
| --- | ---: | --- |
| BULL | 5,763,930,412,596 | Yes |
| SCPI | 104,400,000,000 | No |
| BOSS | 70,000,000,000 | No |

All three reports identify the requested `.JK` symbol and report `latest_close_date=2026-10-06`. That field dates the close, not a separately verified economic effective date for market cap. Keep collection time, report close date, source identity and cap value separately.

The existing shared library on the worktree base already supports explicitly sectioned report identities and symbol validation. There is no need for a new direct HTTP client.

The official [v2 company report documentation](https://docs.sectors.app/api-references/v2/indonesia/report/company-report) states one credit per requested section; requesting only `overview` costs one credit, while omitting sections requests eight sections. The local ledger reserved eight credits for all exploration requests; this is not an independently verified account balance or dashboard decrement.

## Cheaper full-universe cap path

Five structured `/v2/companies/` requests used:

```text
where=sector IS NOT NULL
order_by=market_cap
include_query_values=true
limit=200
offset=0,200,400,600,800
```

The retained responses contain 200/200/200/200/162 rows. Every page declares total 962, and the union contains 962 distinct symbols with finite positive `query_values.market_cap` values. All 45 symbols missing Yahoo caps in the prior preview have positive Sectors caps in this new collection.

Recommended source policy: collect the bulk Sectors cap snapshot for both sectors and konglo, share it across baskets, and retain the overview endpoint as a targeted repair path for symbols missing a completed bulk snapshot. This avoids 962 individual company-report calls. The universe size is observed, not a permanent hard-coded page count; follow validated pagination.

These results establish current cap availability, not usable Yahoo historical prices for all 962 constituents. Sector histories still require collection and validation before claiming that all sector charts render.

## Coverage experiment using retained real Yahoo prices

The previous preview contains 174 valid price histories out of 188 conglomerate stocks. All 34 conglomerate groups have at least one constituent with usable price history and cap. Six groups failed only the current 90-percent coverage threshold:

| Group | Original-cap coverage of usable prices |
| --- | ---: |
| First Resources | 16.10% |
| Haji Isam | 58.70% |
| Happy Hapsoro (Rukun Raharja) | 87.29% |
| Mayapada Group | 1.83% |
| Salim Group | 68.30% |
| Sinarmas Group | 72.29% |

These percentages use the existing Yahoo cap snapshot, to isolate the effect of removing the threshold. Switching cap providers will change weights and may change the percentages and rotation coordinates. No newly computed Sectors-weighted chart is claimed by this exploration.

Removing the threshold makes all 34 groups eligible under the previous cap snapshot, subject to the same valid 18-session price series requirement. The result for Mayapada represents a very small usable subset. Deliver it as a partial basket, displaying coverage and exclusions; do not present it as a complete-group return.

## Implementation work identified

1. Remove the 0.9 cutoff in `calculate_basket` and the matching renderer rejection. Keep finite positive-cap/price validation, verified aligned sessions, corporate-action handling, and the requirement for at least one usable constituent. Normalize weights over usable constituents. Do not zero-fill missing prices.
2. Preserve coverage as information, rather than a gate. Label partial baskets in text and image and retain excluded members. The selected highlights and closing anchors must use the same frozen calculated basket.
3. Add Sectors bulk-cap acquisition to the bounded producer using `lib-sectors`. Share the private coordination store, validate page totals and duplicate symbols, and retain immutable source references. A missing cap after acquisition should exclude that constituent and disclose it, rather than silently assign a value. Unknown-cap counts must be shown separately from coverage measured against known caps.
4. Replace weekly and one-extra-week cap freshness with a 30-day retained snapshot policy. Keep original collection times, cutoff visibility and historical provenance. The first request after expiry creates a new immutable generation. Publication/rendering must not fetch or refresh inputs.
5. Make refresh failure degrade independently of ordinary brief delivery. Show unavailable or explicitly stale cap status without inventing a current snapshot. Preserve the last successful cap artifact for recovery and review.
6. Update producer, core, renderer, package contracts and focused regression tests together. Inspect any shared-client changes separately so news company-context consumers retain their existing cache identities and behavior.

No implementation, publication, deployment, scheduler change, or production state write occurred in this exploration.

## Short design check

Confirmed direction: Sectors supplies the shared bulk cap snapshot; Yahoo remains the price source; use a 30-day cap refresh interval; remove the numerical coverage threshold and disclose partial baskets. These are changes to the proposed implementation, not claims that production already behaves this way.

Confirmed by the user: reuse the last successful cap snapshot if refresh fails,
with its original date and an explicit stale label. Implementation is authorized
in the managed worktree. Deployment and live configuration remain separate steps.

## Local implementation and validation

The managed branch now uses the shared Sectors client and coordination store for
complete bulk cap snapshots, a 30-day freshness policy, and labelled retained
snapshots on refresh failure. Yahoo remains the stock price source. Partial
baskets publish with known-cap coverage, unknown-cap counts and exclusions.
The renderer accepts low coverage and shows original cap collection dates.

Producer configuration has paired absolute Sectors credential/store paths. The
scheduler constructs this provider only during an authorized pre-cutoff producer
call. Configuration checks and frozen recovery perform no provider construction.
Missing configuration is visible as a readiness gap. The path-only template is
updated; live configuration is a separate reviewed rollout input.

Validation: 351 morning-package tests passed. The full repository suite passed,
followed by focused regressions for cutoff boundaries and the final renderer.
A local synthetic layout fixture verified label placement; it is not real market
evidence. No production deployment, provider retry or Discord post was performed
as part of implementation testing.
