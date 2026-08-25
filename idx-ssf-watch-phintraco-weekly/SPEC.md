# Phintraco SSF Watch Specification

**Status:** Approved specification  
**Date:** 2026-07-13  
**Runtime:** Hermes deterministic no-agent cron on the VPS  
**Signal Provider:** Phintraco Sekuritas

## 1. Purpose

Phintraco SSF Watch forwards each underlying equity in a new Phintraco Weekly SSF Review PDF from the Phintraco Sekuritas Official Telegram channel to Discord `#id-stocks-swing`.

A valid Weekly SSF Review produces five strict FIFO alert pairs. Each pair posts a concise, source-faithful SSF Review Alert first, followed immediately by the matching native analyst technical chart extracted from the source PDF.

The watcher performs deterministic source extraction and delivery only. It calls no LLM, agent, market-data service, news service, indicator calculator, OCR model, chart generator, or trade-execution service. It does not calculate missing strategies, prices, targets, support, resistance, or chart associations.

The domain vocabulary is defined in [`CONTEXT.md`](./CONTEXT.md).

## 2. Scope

### 2.1 Included source material

The watcher accepts only a new Telegram document that satisfies every validation condition in Section 6 and represents a Phintraco Weekly SSF Review.

A valid review contains exactly:

1. Four Letter-size PDF pages.
2. Five underlying IDX-equity blocks in source order.
3. Three SSF contract horizons for every underlying: one month, two month, and three month.
4. One Long or Short strategy per contract horizon.
5. One contract purchase price, potential target price, and support/resistance value per contract horizon.
6. Five native technical chart assets, arranged two on page 1, two on page 2, and one on page 3.

### 2.2 Excluded material

The watcher must not forward:

- Individual cash-equity Trading Buy, Buy on Support, or Speculative Buy messages.
- PHINTAS Weekly Swing Trading Ideas text bundles or PDFs.
- Phintraco Weekly Report PDFs.
- Weekly SSF Reviews that fail any source validation rule.
- Research reports, market reviews, corporate-action notices, economic calendars, or SSF review messages without a qualifying PDF.
- Partial review results.
- Replacement, generated, nearby, or inferred charts.

### 2.3 Provider boundary

This watcher is Phintraco-specific. A second provider requires its own verified document parser and source-validation evidence. No generic broker adapter framework is introduced before a real second provider exists.

## 3. External identifiers

| Purpose | Name | ID |
|---|---|---:|
| Telegram source | Phintraco Sekuritas Official | `1444713822` |
| Discord alerts | `#id-stocks-swing` | `1525102458253217803` |
| Discord operations | `#hermes` | `1505162000420835388` |

The watcher reuses the existing `POLYCOP_SESSION_STRING` authorization. It has no Telegram write call site.

Before it touches watcher state or opens its normal Telegram workflow, the
no-agent watcher asks `telegram-resilience` for a shared probe lease. The
control-plane state is `~/.hermes/state/telegram-resilience-polyclop.json`.
During a transport cooldown, active probe, or authorization hold, it exits
cleanly without advancing its source cursor or mutating its report and delivery
outbox. It does not authenticate through any other Telegram profile.

## 4. Runtime model

### 4.1 Execution mode

The watcher runs as a Hermes `no_agent` job:

```text
Schedule: */30 * * * *
Name: idx-ssf-watch-phintraco-weekly
Script: idx-ssf-watch-phintraco-weekly.sh
Mode: no_agent
Delivery fallback: discord:1505162000420835388
```

It polls every 30 minutes, every day. Normal runs inspect unseen Telegram metadata and make no PDF download, Discord alert, or LLM call when there is no new SSF candidate.

The registered wrapper pins its production state to `~/.hermes/state/idx-ssf-watch-phintraco-weekly.json`. State ownership must not depend on the Hermes job working directory.

### 4.2 First activation

The first successful run scans source history only far enough to identify the newest valid Weekly SSF Review. It forwards that one valid report once, then persists the newest observed Telegram message ID and processes only later source messages.

It must not replay older valid reports. If no valid report is found during bootstrap, it persists the newest source message ID and forwards nothing.

### 4.3 Single-instance execution

A non-blocking process lock covers state loading, Telegram observation, PDF capture, validation, chart extraction, outbox delivery, heartbeat handling, and state persistence.

If the lock is held, the invocation makes no state changes and no Telegram or Discord calls, prints `{"wakeAgent": false}`, and exits successfully.

### 4.4 Time zone

All runtime timestamps, source-date rendering, logs, heartbeat times, and retry schedules use `Asia/Jakarta`.

## 5. Source discovery

### 5.1 Candidate detection

The watcher reads unseen messages from the Phintraco source in ascending Telegram message-ID order. A message is a candidate only when all of the following are true:

- it has a document attachment;
- the document MIME type is `application/pdf`;
- its filename case-insensitively begins with `Weekly SSF review` and ends with `.pdf`.

The candidate PDF message ID is the report identity. Two different Telegram document messages are two different source reports even if their underlying equities and fields match.

### 5.2 Candidate capture

Before parsing, the watcher atomically records a pending report-capture job keyed by candidate Telegram message ID. It downloads the original PDF to private runtime storage. A download failure remains pending and retries with bounded exponential backoff. It is never treated as an invalid report and never converted into a chartless alert.

## 6. Deterministic PDF validation and extraction

### 6.1 Tools

The VPS uses installed Poppler utilities:

- `pdfinfo` for PDF page metadata.
- `pdftotext -layout` for the selectable text layer.
- `pdfimages -list` for per-page image metadata.
- `pdfimages -png` for lossless chart-pixel extraction.

The parser must not fingerprint a PDF producer, file size, chart encoding, or fixed chart dimensions. From April through July 2026, Phintraco changed its PDF producer and native chart dimensions while retaining the same report schema.

### 6.2 Required structural guards

A captured candidate is valid only when all of these deterministic guards succeed:

1. `pdfinfo` reports exactly four pages.
2. `pdftotext -layout` produces nonempty selectable text.
3. The text contains exactly five ordered underlying blocks. Each block starts with an uppercase IDX ticker and issuer name followed by `Shares Statistics as of`.
4. Every underlying block contains all three contract columns: `1 Month Contract`, `2 Month Contract`, and `3 Month Contract`.
5. Every contract horizon has exactly one source strategy, `Long` or `Short`.
6. Every contract horizon has a numeric `Contract Purchase Price (IDR)`, `Potential Target Price (IDR)`, and `Support / Resistance` value.
7. `pdfimages -list` identifies exactly five technical-chart images with a minimum width of 1000 pixels and a minimum height of 500 pixels.
8. The technical-chart images occur in source order as two on page 1, two on page 2, and one on page 3. The fourth page contributes no technical chart.

A source variation such as `MA20`, `MA50`, `MA60`, or `MA100` is source text, not a validation failure. The concise Discord message does not include these MA labels.

### 6.3 Underlying and chart association

The five parsed underlying blocks and five accepted technical-chart images are associated by stable report order:

```text
underlying 1 -> page 1 chart 1
underlying 2 -> page 1 chart 2
underlying 3 -> page 2 chart 1
underlying 4 -> page 2 chart 2
underlying 5 -> page 3 chart 1
```

The association is rejected if the source does not satisfy this layout. The watcher does not inspect chart pixels with a vision model and does not infer a chart from text, filename, timestamp, or nearby Telegram media.

### 6.4 Invalid source behavior

A PDF that fails validation is terminally invalid for that source message ID:

1. Persist the source ID and sanitized validation reason in the invalid-report ledger.
2. Advance the Telegram observation cursor past it.
3. Forward no underlying, text, or chart.
4. Include `source=invalid` and the bounded reason in the next operational heartbeat.
5. Do not retry the same invalid document, invoke an LLM, or accept a partial parse.

A later corrected PDF is a new Telegram message ID and is independently eligible.

## 7. Parsed model

Each accepted report contains:

```text
WeeklySsfReview
  source_message_id: integer
  report_date: Asia/Jakarta calendar date
  provider: "Phintraco"
  underlyings: five UnderlyingSsfReview records in source order

UnderlyingSsfReview
  ticker: uppercase IDX ticker
  issuer_name: source issuer text
  share_price: source value
  contracts: exactly three ContractRecommendation records in 1-, 2-, 3-month order
  chart_path: durable extracted chart path

ContractRecommendation
  horizon_months: 1 | 2 | 3
  strategy: Long | Short
  purchase_price: source value
  target_price: source value
  support_resistance: source value
```

The report date, source fields, and all numeric display values remain source strings after whitespace normalization. The watcher does not calculate percentages, price deltas, profitability, or risk.

## 8. Discord alert format

### 8.1 Heading direction

The heading direction is computed only from the three source strategies for that underlying:

- all Long: `LONG`
- all Short: `SHORT`
- otherwise: `MIXED`

### 8.2 Canonical alert

```md
### <:phintraco:1531272488645038091> [SSF] MIXED: INDF

Report date: Mon, Jul 13 2026
Underlying price: 6750

**1-month contract**
Strategy: Short<:down:1531285063986053200>
Purchase price: 6825
Target price: 6675
Support / resistance: 6575 / 6825

**2-month contract**
Strategy: Long<:up:1531285100346740766>
Purchase price: 6800
Target price: 7000
Support / resistance: 6575 / 7050

**3-month contract**
Strategy: Long<:up:1531285100346740766>
Purchase price: 6800
Target price: 7200
Support / resistance: 6575 / 7300

**Source:** Phintraco Sekuritas | Weekly SSF Review
```

The values in this example are illustrative. Runtime values must come only from the accepted source PDF.

### 8.3 Formatting rules

- The first line is a Discord level-three Markdown heading: `###` followed by one space.
- The prefix is `:phintraco: [SSF]`.
- The heading direction is uppercase `LONG`, `SHORT`, or `MIXED`, with no direction emoji.
- Only the `**1/2/3-month contract**` labels are bold. All other labels and values are plain text.
- Dynamic source text is Discord-Markdown escaped.
- One underlying must fit in one Discord text message and must not be split.
- The native analyst technical chart is uploaded as a separate Discord attachment immediately after its text.
- The watcher posts no disclaimer, generated summary, confidence, score, market-data enrichment, execution instruction, or chart-unavailable substitute.

## 9. Durable delivery outbox

### 9.1 Report preparation

A downloaded valid PDF is fully parsed and all five charts are extracted into durable private media storage before any Discord text post is attempted. Only then does the watcher atomically create five ordered outbox events, one per underlying.

This avoids a partial Discord report if later chart extraction fails.

### 9.2 Event identity and phases

An outbox event key is `<source_message_id>:<ticker>`. The phases are:

```text
pending_text -> pending_chart -> delivered
```

The report PDF source message ID prevents duplicate report ingestion. The full event key prevents one underlying from suppressing another.

### 9.3 Strict FIFO delivery

Delivery is strict FIFO across all SSF outbox events:

```text
text for underlying 1
chart for underlying 1
text for underlying 2
chart for underlying 2
...
```

Text success is persisted before chart upload begins. A chart upload failure leaves the event at `pending_chart`, retries only that chart with bounded exponential backoff, and blocks later events. Text is never repeated after a successful text post.

Extracted chart media is deleted only after its event reaches durable `delivered` state. The captured source PDF is deleted only after all five outbox events are delivered.

## 10. State and storage

Runtime state is private and excluded from deployment synchronization:

```text
~/.agents/skills/idx-ssf-watch-phintraco-weekly/state/
  state.json
  reports/
  media/
  run.lock
  watchdog-notices.json
```

The state contains the observed Telegram cursor, bootstrap completion, pending report jobs, invalid-report ledger, ordered outbox, last successful poll, last successful delivery, last heartbeat run, retry metadata, and bounded stats.

State writes use atomic replacement plus directory fsync. A corrupt, unsupported, or semantically invalid state blocks the watcher, sends a rate-limited fatal notice to `#hermes`, and never resets the cursor or outbox.

## 11. Heartbeats and failures

Every successful 30-minute run posts one SSF-specific heartbeat to `#hermes`, including no-op runs:

```text
🫀 idx-ssf · HH:MM WIB · source=ok|missing|invalid · reports=N · alerts=N[ ⚠️]
```

`source=missing` means no accepted current candidate was observed. `source=invalid` means an observed candidate failed deterministic validation. `⚠️` marks a degraded run, including pending download or delivery retries.

A fatal failure posts:

```text
❌ idx-ssf · HH:MM WIB · failed: <sanitized reason>
```

Fatal notices are rate-limited by bounded fingerprint state. The watchdog runs every five minutes and posts a fatal notice if no successful Telegram poll has occurred within 65 minutes.

## 12. Deployment and operations

Mac source of truth:

```text
~/Documents/Projects/Hermes/idx-ssf-watch-phintraco-weekly/
```

VPS runtime:

```text
~/.agents/skills/idx-ssf-watch-phintraco-weekly/
~/.hermes/scripts/idx-ssf-watch-phintraco-weekly.sh
```

The implementation uses the shared VPS Python runtime:

```text
~/.local/share/uv/tools/yahoo-finance-mcp/bin/python
```

The wrapper loads only `DISCORD_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `POLYCOP_SESSION_STRING` from `~/.hermes/.env`. It must not print secrets, source-PDF bytes, or chart bytes.

## 13. Acceptance criteria

1. The watcher runs as `idx-ssf-watch-phintraco-weekly` in Hermes `no_agent` mode every 30 minutes.
2. It makes no LLM, OCR-model, market-data, or Telegram write call.
3. It forwards the newest valid review once on first activation and does not replay older reports.
4. It accepts all verified April through July 2026 SSF report variants despite producer, chart-size, and image-encoding changes.
5. It rejects a wrong page count, wrong underlying count, missing contract field, wrong chart count, wrong chart distribution, or malformed strategy without forwarding partial results.
6. It produces five FIFO text-and-chart pairs for a valid report.
7. Every alert uses a `### :phintraco: [SSF] LONG|SHORT|MIXED: TICKER` heading.
8. A uniform Long or Short report heading reflects all three horizons. A mixed report heading is `MIXED`.
9. Each alert contains only source-provided report date, underlying price, strategy, purchase price, target price, and support/resistance fields.
10. Each alert chart is the matched native source chart extracted from the PDF.
11. Text delivery and chart delivery are independently durable and retry safely without duplicate text.
12. Every 30-minute no-op, accepted, invalid, and degraded run posts an `idx-ssf` heartbeat to `#hermes`.
13. A dry run validates a real source candidate without posting to Discord or mutating live state.
