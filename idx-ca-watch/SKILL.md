---
name: idx-ca-watch
description: Hermes cron support skill. Hourly scan of IDX corporate-action disclosures that posts only high-conviction, fundamental and corporate-action catalysts scoring 7 to 10, with a chart attachment for visual context.
user-invocable: false
---

# IDX CA Watch runtime contract

This is the Hermes runtime prompt. The canonical development, deployment, and verification guidance is in `AGENTS.md`. `bin/scan.py` deterministically fetches, deduplicates, extracts disclosure text, applies hard red flags, stores state, creates the chart attachment, and posts the heartbeat. When it returns `{"wakeAgent": true, "items": [...]}`, evaluate each item under this contract.

Alerts go to `1517510484025151538`. Heartbeats and operational status go to `1505162000420835388`.

## Objective

This is a high-conviction corporate-action catalyst feed for an approximately 1 to 20 trading-day horizon. It is not a general disclosure feed or a technical-analysis feed.

Score only the disclosed corporate action and fundamental evidence. Do not use, mention, or infer a score from RSI, moving averages, ATR, volume, price momentum, liquidity, or chart patterns. The chart is attached as visual context only and must not affect the score or the text.

## Inputs

Each item supplies:

- `ticker` and `company_name`
- `ca_type`, `title`, `subject`, `pdf_url`, `pdf_text`, and `fin_report_text`
- `fundamental_context` with `market_cap`, `total_revenue`, `total_assets`, and `shares_outstanding` when available
- `health` fundamental data
- `red_flags`
- `chart_path`

Use only these supplied facts. A missing price, size, counterparty, denominator, funding source, approval, or other material term is missing evidence, not permission to assume a favourable answer.

## Candidate screen

Suppress and record routine financial results, ordinary dividends, generic material-fact notices, administrative updates, vague cooperation or joint-venture announcements, and disclosures without enough detail to judge materiality and economic effect.

Do not publish an item involving severe dilution, defensive refinancing, financial distress, UMA, suspension, PKPU, FCA/PPK, or another overriding adverse condition. If `health` indicates negative trailing net income, a net-income collapse of roughly 50 percent or more, or current ratio below 1 without net cash, suppress it.

## Score, 0 to 10

Assign four integer components. The total `score` must equal their sum.

1. `materiality`, 0 to 3
   - 0: unquantified or below 5 percent of the relevant base
   - 1: 5 percent to below 10 percent
   - 2: 10 percent to below 25 percent
   - 3: at least 25 percent, or a material change in control or free float
   - Use the most relevant disclosed denominator: market capitalization, annual revenue, assets, shares outstanding, free float, or another directly relevant company base. If a relevant denominator or key transaction term is unavailable, this component is at most 1

2. `fundamental_impact`, 0 to 3
   - Score the disclosed, supportable path to revenue, earnings, cash flow, productive assets, capital structure, control, or free float
   - Broad management language without a specific economic path is 0 or 1

3. `structure_alignment`, 0 to 2
   - Score terms that protect or improve public-shareholder economics, including a credible controller commitment when disclosed
   - Pure dilution, opaque related-party economics, or an unaligned rescue financing is 0

4. `execution_certainty`, 0 to 2
   - Score disclosed price, size, parties, funding, approvals, timetable, and other material terms
   - An early plan without its key terms is 0

An item can post only if every condition holds:

- total score is 7 to 10
- materiality is at least 2
- fundamental impact is at least 2
- execution certainty is at least 1
- a usable materiality denominator exists in `fundamental_context`
- no red flag or financial-distress condition applies

Scores 0 to 6 are always suppressed. Record every evaluated item, whether posted or suppressed, so it does not re-escalate.

Interpretation:

- 7: material catalyst with one meaningful remaining uncertainty
- 8: material action with clear economic benefit, constructive terms, and credible execution
- 9 or 10: highly material or transformative action with measured impact, strong alignment, and little remaining uncertainty

Examples that may qualify are material controller accumulation, a funded and meaningful buyback, an acquisition or contract material to revenue or earnings, or a productive capital action with disclosed pricing, funding or committed buyer, use of proceeds, and transparent dilution. A label alone never qualifies.

## Summary and post command

For a qualifying item, write one or two short paragraphs in Bahasa Indonesia. Use the concise factual style of the X-post watcher: start with the core action, name parties and material numbers, then state only the supported economic implication and remaining uncertainty. Do not add headings, bullet lists, technical metrics, a disclaimer, or a conclusion outside the supplied `summary` field.

Copy `ticker`, `company_name`, `fundamental_context`, `health`, `red_flags`, `pdf_url`, and `chart_path` from the item verbatim. Write only `ca_label`, `summary`, and the four score components after evaluating the evidence.

Run this command only for a valid 7 to 10 item:

```bash
python ~/.agents/skills/idx-ca-watch/bin/scan.py post-alert --json '{
  "ticker":"ANTM",
  "company_name":"PT Aneka Tambang Tbk",
  "ca_label":"Pembelian saham oleh pengendali",
  "summary":"Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.",
  "score_components":{
    "materiality":2,
    "fundamental_impact":2,
    "structure_alignment":2,
    "execution_certainty":1
  },
  "score":7,
  "red_flags":[],
  "fundamental_context":{"market_cap":2000000000000,"total_revenue":1000000000000,"total_assets":3000000000000,"shares_outstanding":1000000000},
  "health":{"ni_ttm":1000000000,"current_ratio":2.0,"net_cash":true},
  "pdf_url":"https://www.idx.co.id/StaticData/example.pdf",
  "chart_path":"/tmp/chart.png"
}'
```

`scan.py` validates the score gates and renders the final message as:

```md
### <:idx:1531974045266874499> ANTM (PT Aneka Tambang Tbk)
Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.
┈┈┈┈┈┈┈┈┈┈┈┈┈
*Jenis aksi:* Pembelian saham oleh pengendali
*Skor katalis:* 7/10
*Sumber:* [Keterbukaan Informasi BEI](<https://www.idx.co.id/StaticData/example.pdf>)
```

The chart at `chart_path` is attached to the same Discord message.

## Recording scores

After posting a valid alert, or after suppressing an item, run:

```bash
python ~/.agents/skills/idx-ca-watch/bin/scan.py record-score <id2> <score> --ticker <TICKER> --type <ca_type> --ts <ts>
```

Pass the item values for `id2`, `ticker`, `ca_type`, and `ts`. The score must be the evaluated total, including suppressed scores. Never leave an evaluated item unrecorded.

## Dry run

- `IDX_CA_WATCH_NO_POST=1`: print instead of posting
- `IDX_CA_STATE_PATH=...`: use an isolated state path
- `IDX_CA_WATCH_BOOTSTRAP_RESET=1`: reset only an intentionally isolated state path, never production state
