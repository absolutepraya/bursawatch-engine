---
name: guess-stock
description: Identify an anonymized IDX ticker from incomplete chart, key-stats, clue, HSC/KSEI, or mixed evidence. Use when the user asks to guess a hidden Indonesian stock or find stocks matching a supplied setup.
---

# Guess Stock

Treat the request as an evidence-bound fingerprinting puzzle. A chart shape,
keyword, or single financial number is never proof and the result is never a
buy recommendation.

## 1. Classify the evidence

Build one evidence manifest for every supplied image and text item. Classify
each item as `chart`, `keystats`, `clue`, `transaction`, `social`, or
`official-source`. Record only visible facts, their source, screenshot time,
as-of date, timeframe, and whether the value is intraday. Keep unknown fields
unknown. Mixed inputs use one combined manifest.

Use these modes automatically:

- chart: identify the exchange, calendar, path, price, volume, and visible
  indicators;
- keystats: match multiple balance-sheet or income-statement fields in the
  same reporting period;
- clue: read `references/name-clues.md`, resolve the underlying brand or
  reference, then map it to an active IDX company;
- transaction or social: identify the issuer and action from the source, then
  verify it with an official or primary page.

## 2. Anchor time before scanning

For Abhip, a chart is current or near-current unless he explicitly says it is
historical. “Current” means the rightmost populated candle visible in the
screenshot, not the latest candle when the answer is generated. For an
explicitly dated image, use that date. If the date or timeframe is decisive
and unavailable, ask at most one targeted clarification, then fail closed.

## 3. Use sources by role

- Yahoo Finance: paced OHLCV, history, financial statements, and freshness
  checks; use `.JK` tickers.
- TradingView Indonesia scanner: coarse full-universe screening for the
  requested visible columns; use `IDX:TICKER` for chart rendering.
- Serper: primary web discovery. Brave: fallback when Serper is unavailable.
  Search results nominate sources only; official IDX, KSEI, issuer, or filing
  pages support final claims.
- `chart-img`: render at most three finalists for visual comparison. It is a
  renderer, not evidence that a ticker is correct.

## 4. Rank and reject

Use exact values first, in this order: MACD, current and average volume, price,
ordered pivot chronology, then RSI. When labels are hidden, transcribe 15 to
20 date-anchored normalized pivots and compare affine-normalized MAE plus
correlation. Pixel or shape similarity is shortlist evidence only.

Reject a candidate for a wrong as-of date, calendar-shifted event, wrong major
high or low, V reversal, flat base, later spike, wrong volume event, or
indicator direction. A user correction adds a hard rejection for this puzzle.

Use `bin/idx_chart_fingerprint.py` for the deterministic first pass. Omit
unknown flags instead of fabricating them:

```bash
python3 bin/idx_chart_fingerprint.py --price 192 --volume 189.01M \
  --volume-average 21.2M --as-of 2026-08-19 --candidate-file candidates.json
```

Render and compare at least the top two finalists when the ticker is hidden.
The final report must show the decisive matches, mismatches, source freshness,
as-of status, and no more than three alternatives.

## 5. Confidence contract

- `Confirmed`: exact as-of, at least two material evidence categories, matching
  chronology or indicators where shown, and an independent market or primary
  source. A single keystat or clue cannot confirm a ticker.
- `Strong lead`: several categories match but one material uncertainty remains.
- `Lookalike`: partial geometry or numeric similarity without confirmation.
- `Insufficient evidence`: too little visible information to rank honestly.
- `Rejected`: a material mismatch or current-puzzle user correction.

Say “insufficient evidence” instead of forcing a winner. State data delays,
rounded screenshots, missing periods, and provider failures explicitly.
