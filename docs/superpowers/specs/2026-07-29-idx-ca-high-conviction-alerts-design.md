# IDX CA high-conviction alerts design

## Purpose

Refocus `idx-ca-watch` into a high-conviction corporate-action catalyst feed for trades held roughly 1 to 20 trading days. The alert channel posts only disclosures with a score of 7 to 10 out of 10. The score is based solely on corporate-action and fundamental evidence, never on technical indicators.

## Scope

This change affects candidate evaluation, scoring instructions, alert rendering, and regression coverage for `idx-ca-watch`.

It does not change the cron schedule, channels, heartbeat behavior, state ownership, or historical Discord messages. It does not replay, backfill, or reset production state.

## Decision rules

### Candidate screen

A disclosure can proceed to scoring only when it supplies enough evidence to assess both its materiality and economic effect. The evaluator must suppress routine financial reports, ordinary dividends, generic material-fact notices, administrative updates, vague cooperation or joint-venture announcements, and actions whose material terms are absent.

Hard red flags remain disqualifiers. A disclosure involving severe dilution, defensive refinancing, financial distress, UMA, suspension, PKPU, or a comparable overriding risk cannot qualify for a published alert.

### Scoring

The score has four components and totals 10 points.

| Component | Points | Evidence required |
| --- | ---: | --- |
| Materiality | 0 to 3 | Scale relative to the relevant company base: market capitalization, annual revenue, assets, shares outstanding, free float, or another directly relevant denominator |
| Fundamental impact | 0 to 3 | A specific, supportable path to revenue, earnings, cash flow, productive assets, capital structure, control, or free float |
| Structure and alignment | 0 to 2 | Terms that align controllers or counterparties with public shareholders, or otherwise protect and improve shareholder economics |
| Execution certainty | 0 to 2 | Disclosed price, size, parties, funding, approvals, timetable, and other material terms |

Materiality is scored as follows unless the corporate action requires a more directly relevant basis:

- 0: unquantified or below 5 percent of the relevant base
- 1: 5 percent to below 10 percent
- 2: 10 percent to below 25 percent
- 3: 25 percent or more, or a material change in control or free float

If a relevant denominator or key transaction term is unavailable, materiality must score at most 1. Narrative quality cannot substitute for missing evidence.

### Publication gate

An item is published only when all of the following are true:

- Total score is 7 to 10
- Materiality is at least 2
- Fundamental impact is at least 2
- Execution certainty is at least 1
- No hard red flag or overriding adverse economic condition applies

Scores below 7 are persisted as processed and suppressed. They must not be posted as watchlist alerts.

Score interpretation:

- 7: a material and real catalyst with one meaningful remaining uncertainty
- 8: a material action with clear economic benefit, constructive terms, and credible execution
- 9 to 10: a highly material or transformative action with measured impact, strong alignment, and little remaining uncertainty

Examples that can qualify include a material controller accumulation, a funded and meaningful buyback, an acquisition or contract that is material to earnings or revenue, or a productive capital action with disclosed pricing, committed buyer or funding, use of proceeds, and transparent dilution.

## Technical-indicator boundary

RSI, moving averages, ATR, volume, price momentum, and other technical indicators must not influence candidate selection, score, publication, or alert text.

The chart remains attached to each published alert as visual context only. The body must not include technical metrics or make a technical claim.

## Alert format

Published alerts use Bahasa Indonesia and the concise factual style of the X-post watcher: one or two short paragraphs, core facts first, material numbers and parties named, then only supportable implications.

```md
### <:idx:1531974045266874499> BIRD (PT Blue Bird Tbk)
Chandra Investama, pengendali BIRD, membeli 39,2 juta saham BIRD di pasar sekunder pada harga Rp1.500 per saham. Kepemilikannya naik dari 4,71% menjadi 6,28%, tanpa penerbitan saham baru atau dilusi bagi pemegang saham publik.

Pembelian ini hanya masuk alert bila nilainya terbukti material terhadap market cap atau free float BIRD, dan kenaikan kepemilikan tersebut punya bobot yang cukup. Jika tidak, aksi seperti ini akan dicatat lalu disuppress.
┈┈┈┈┈┈┈┈┈┈┈┈┈
*Jenis aksi:* Pembelian saham oleh pengendali
*Skor katalis:* 7/10
*Sumber:* [Keterbukaan Informasi BEI](<https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/>)
```

The chart is attached to the same Discord alert. The header is H3 and uses the configured `:idx:` custom emoji. The company name is included after the ticker. The body contains no technical block, fundamental-statistics block, advisory disclaimer, or unsupported inference.

## Data flow and failure handling

1. The deterministic scanner fetches disclosures, deduplicates them, and applies hard red-flag checks.
2. A candidate includes disclosure text, fundamental context, the information necessary to establish materiality, company name, source URL, and a chart attachment path.
3. The scoring step assigns the four component scores and either suppresses or posts the alert.
4. Every evaluated candidate is recorded as processed, including suppressed candidates, so it is not re-escalated.
5. A candidate missing material evidence cannot pass the publication gate. It is suppressed rather than promoted on an assumption.
6. The existing heartbeat continues to report scanner health independently of whether an alert is published.

## Verification

Regression coverage will prove:

- routine dividends, periodic results, vague joint ventures, and generic filings are suppressed
- an action below the materiality threshold is suppressed
- score 7, 8, and 9 cases pass only when each mandatory gate is satisfied
- missing denominators or key terms cannot produce a score of 7 or higher
- technical inputs do not appear in scoring or rendered text
- the rendered alert has the approved Indonesian H3 `:idx:` format, company name, source link, action label, and score
- no-post smoke exercises rendering and chart attachment without posting to Discord

## Deployment constraints

Development occurs in `idx-ca-watch/bin/` and tests in `idx-ca-watch/tests/`. Production state is not edited. Executable deployment uses `./deploy.sh idx-ca-watch`, while any `SKILL.md` update is checksum-compared and synced separately. A live claim requires focused and full test results, matching local and VPS checksums, and an isolated no-post smoke test.
