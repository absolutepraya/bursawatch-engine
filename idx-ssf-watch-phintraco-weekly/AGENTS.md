# IDX SSF Watch, Phintraco Weekly

This file supplements the repository root `AGENTS.md`. It is the canonical development and operations guide for this deterministic no-agent watcher.

## Identity and scope

The watcher forwards qualifying Phintraco Weekly SSF Review PDFs from Phintraco Sekuritas Official to Discord as source-faithful text followed immediately by the matching native analyst chart. It performs deterministic extraction and delivery only. It never calls an LLM, market-data service, OCR model, chart generator, or Telegram write API.

## Runtime, scheduler, and ownership

The live registry owns active no-agent job `6889d2d13ac2`, `idx-ssf-watch-phintraco-weekly`, on `*/30 * * * *` (WIB). Hermes runs `idx-ssf-watch-phintraco-weekly.sh` from `/home/praya` and delivers raw output to `#hermes` (`1505162000420835388`).

The source is Telegram channel `1444713822`. Alerts go directly to Discord `#id-stocks-swing` (`1525102458253217803`); operational heartbeats and fatal notices go directly to `#hermes`. The wrapper pins the production state path to `~/.hermes/state/idx-ssf-watch-phintraco-weekly.json`, independent of its working directory.

## Deterministic behavior and invariants

Read unseen source messages in ascending Telegram message-ID order. A candidate must have a document attachment with MIME type `application/pdf` and a filename that case-insensitively begins `Weekly SSF review` and ends `.pdf`. The candidate message ID is the report identity, so two source messages remain distinct even when their contents match.

On first successful activation, scan only far enough to identify the newest valid Weekly SSF Review, forward that one report, then persist the newest observed message ID. If bootstrap finds no valid report, persist the newest observed ID and forward nothing. Do not replay older valid reports.

Accept only a qualifying Weekly SSF Review PDF. A valid report has four pages, five ordered IDX underlyings, all three 1-, 2-, and 3-month contract fields, valid Long or Short strategies, source numeric values, and exactly five native technical charts arranged two on page one, two on page two, and one on page three. Invalid reports are terminal for their Telegram message ID and never produce partial delivery.

For a valid report, parse all five underlyings and extract all charts before creating the outbox. Each event is keyed by `<source_message_id>:<ticker>` and follows `pending_text -> pending_chart -> delivered`. Delivery is strict FIFO: text, matching source chart, then the next underlying. A failed chart retries only the chart and blocks later events; successful text is never duplicated.

The canonical alert begins `### <:phintraco:1531272488645038091> [SSF] LONG|SHORT|MIXED: TICKER`. Direction is derived only from the three source contract strategies. It renders source report date and underlying price, then the 1-, 2-, and 3-month contract blocks with strategy, purchase price, target price, and support or resistance, followed by `**Source:** Phintraco Sekuritas | Weekly SSF Review`. Only the contract labels are bold; dynamic source text is Discord-Markdown escaped; each underlying fits in one text message. The native chart is a separate immediate attachment. Never add generated analysis, confidence, market enrichment, execution advice, or a chart-unavailable substitute.

## State, data, and credential ownership

The production state owns the Telegram cursor, bootstrap status, report jobs, invalid-report ledger, outbox, retry timing, heartbeat data, and private PDF/chart artifacts. Atomic writes and the nonblocking run lock protect it. Corrupt state fails closed and must never be reset to bypass pending delivery.

The wrapper loads only `DISCORD_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `POLYCOP_SESSION_STRING` from VPS `~/.hermes/.env`. Never log session strings, tokens, PDF bytes, or chart bytes.

## Delivery contract and failure semantics

Every successful run, including no-op and invalid-source runs, emits `🫀 idx-ssf · HH:MM WIB · source=... · reports=N · alerts=N`, with `⚠️` for degraded work. Fatal errors are sanitized and rate-limited. The independent watchdog reports a missing successful poll after 65 minutes without mutating scanner state outside its notice file.

## Safety, approval, and no-post rules

This watcher shares `POLYCOP_SESSION_STRING` and the `telegram-resilience` control plane at `~/.hermes/state/telegram-resilience-polyclop.json`. It must acquire `acquire_probe_after_active_lease` before normal Telegram work. A cooldown, active peer probe, transport failure, or authorization hold exits cleanly without advancing the cursor or mutating report and delivery state.

For no-post verification, set `IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST=1`, an isolated `IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH`, and `IDX_SSF_WATCH_PHINTRACO_WEEKLY_FORCE_HEARTBEAT=1` as needed. Do not manually invoke the production schedule, replay a report, or reset state.

## Development commands and behavioral tests

Run from the repository root:

```bash
../.venv/bin/python -m pytest -q idx-ssf-watch-phintraco-weekly/tests
```

The suite covers report validation, source-faithful rendering, durable FIFO text/chart delivery, retry behavior, state and lock safety, shared-resilience exits, heartbeat output, watchdog isolation, and wrapper setup.

## Deployment and live verification

Deploy only a clean published commit with `./deploy.sh idx-ssf-watch-phintraco-weekly`, synchronize the wrapper and this `CRON.md` separately after approval, and compare each changed VPS checksum. Use isolated no-post verification on the actual wrapper path, then inspect the natural scheduler record, saved output, shared control state, and target delivery path. Do not edit live state or the dotfiles mirror.

## Historical references and related projects

This cron is Phintraco-specific. A new provider needs its own verified parser and source-validation evidence. The shared Telegram resilience contract is also documented in root `AGENTS.md` and `telegram-resilience/README.md`.
