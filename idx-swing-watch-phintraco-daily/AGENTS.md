# IDX Swing Watch, Phintraco Daily

This file supplements the repository root `AGENTS.md`. It is the canonical development and operations guide for this deterministic no-agent watcher.

## Identity and scope

The watcher forwards individual Phintraco IDX buy recommendations, qualifying outcome reminders, and verified active-plan status updates to Discord. It is a source-only parser and delivery pipeline. It never invokes an LLM, enriches with market data, calculates indicators, scores confidence, generates charts, or places trades.

## Runtime, scheduler, and ownership

The live registry owns active no-agent job `2b5c0a128652`, `idx-swing-watch-phintraco-daily`, on `* * * * *` (WIB). Hermes runs `idx-swing-watch-phintraco-daily.sh` and delivers raw output to `#hermes` (`1505162000420835388`).

The source is Phintraco Sekuritas Official Telegram channel `1444713822`. Alerts go directly to `#id-stocks-swing` (`1525102458253217803`); operational heartbeats and fatal notices go directly to `#hermes`. Production state, media, lock, and watchdog notices live under the deployed cron's private state directory.

## Deterministic behavior and invariants

Accept individual `Trading Buy`, `Buy on Support`, and `Speculative Buy` calls with the required source fields, qualifying source-marked outcomes and status updates, and validated same-ticker reply updates. Exclude sell calls, weekly bundles and PDFs, market reviews, media-only posts, and nearby inferred charts.

An alert keeps source values and source-post time. A qualifying same-message photo is the only permitted Source Chart; a genuine no-photo source renders `Chart: Unavailable from source`. An outbox event is identified solely by Telegram source message ID. The phases are `pending_media_capture`, `pending_text`, `pending_chart`, and `delivered`, with strict FIFO text/chart adjacency and retries that never repeat successful text.

## State, data, and credential ownership

State owns the observation cursor, outbox, cached source media, retry metadata, liveness, and rate-limited fatal fingerprints. Atomic writes and a nonblocking run lock prevent overlap. Corrupt state fails closed and must not be cleared as a recovery shortcut.

The wrapper loads only `DISCORD_BOT_TOKEN`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `POLYCOP_SESSION_STRING` from VPS `~/.hermes/.env`. Source charts, logs, and credentials stay private.

## Delivery contract and failure semantics

One text alert fits in one Discord message, followed by its source chart when available. The watcher posts at most one `idx-swing-phintraco-daily` heartbeat per WIB hour and marks degraded work with `⚠️`. Fatal notices are sanitized and rate-limited by fingerprint and hour. The watchdog detects an overdue successful poll without overwriting scanner state.

## Safety, approval, and no-post rules

This watcher shares `POLYCOP_SESSION_STRING` and the `telegram-resilience` control plane at `~/.hermes/state/telegram-resilience-polyclop.json`. It calls `acquire_probe_after_active_lease` before creating a Telegram client. A shared cooldown, active probe, transport failure, or authorization hold exits without advancing the cursor or mutating the outbox.

For no-post verification set `IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST=1`, an isolated `IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH`, and `IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT=1` if required. Never manually invoke the production schedule, backfill calls, or reset live state.

## Development commands and behavioral tests

Run from the repository root:

```bash
../.venv/bin/python -m pytest -q idx-swing-watch-phintraco-daily/tests
```

The suite covers parsing and rejections, timestamp and source-chart rules, durable media and outbox transitions, FIFO and retry safety, rate limiting, shared-resilience exits, heartbeat behavior, watchdog isolation, and wrapper setup.

## Deployment and live verification

Deploy only a clean published commit with `./deploy.sh idx-swing-watch-phintraco-daily`, synchronize the wrapper and `CRON.md` separately after approval, and compare changed VPS checksums. Use isolated no-post verification through the actual wrapper, then inspect the natural scheduler record and target delivery path. State, media, logs, and the dotfiles mirror are not source to change.

## Historical references and related projects

This is a Phintraco-specific parser. Future providers require independent source validation. Root `AGENTS.md` and `telegram-resilience/README.md` define the shared session and control-plane contract.
