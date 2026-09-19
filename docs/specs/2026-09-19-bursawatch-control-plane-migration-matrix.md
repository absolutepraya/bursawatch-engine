# Bursawatch control-plane migration matrix

This matrix records the repository exploration behind the control-plane slice.
It separates operator configuration from watcher-owned runtime state, because
moving the latter would be a different, stopped-writer migration.

| Package | Current operator configuration | Current runtime state | Control-plane status |
| --- | --- | --- | --- |
| `cron-x-account-watch` | `config/watches.json`, source/profile routing, Discord destinations, LLM and thread policy | cursor, outbox, leases, media, delivery ledger, cleanup queue in the watcher state tree | Live snapshot loader and structured run events implemented behind opt-in environment variables |
| `cron-ig-account-watch` | `config/watches.json`, OCR and delivery policy | cursor, outbox, media, OCR cache, leases and cleanup state | Live snapshot loader and lifecycle events implemented behind opt-in environment variables |
| `cron-wa-channel-watch` | `config/watches.json`, Channel identity, routing and analysis policy | bridge queue, cursor, outbox and leases | Live snapshot loader and lifecycle events implemented behind opt-in environment variables |
| `cron-tg-market-news` | Source entities, source thread rules, destination channel IDs and heartbeat identity are currently code constants | `~/.hermes/state/idx-market-news.json` plus shared Telegram resilience state | Not migrated; requires a typed control payload and a separate source-state ownership review |
| `cron-tg-phintraco-swing` | Source channel, destinations, board handoff and retry policy are currently code constants | JSON state and media under the watcher-owned state path | Not migrated; source and delivery settings must be separated from parser invariants |
| `cron-tg-kelas-investasi-gtw` | Source identity, destination and heartbeat identity are currently code constants | JSON state and media under the watcher-owned state path | Not migrated; source credentials and resilience state remain outside operator config |
| `cron-dc-swing-board` | Board operation and phase schedules are package contracts | SQLite board database, private media and forum reconciliation state | Not migrated; SQLite is domain state, not a drop-in configuration database |

## Rules for the eventual cutover

Each migrated invocation reads one validated configuration snapshot before it
opens a source or mutates watcher state. It records the returned revision on
its run record and does not reread configuration halfway through the run.

The control plane owns operator-editable values, revision history, audit actor,
run summaries and structured events. It does not own cursors, deduplication,
media, leases, outboxes, SQLite board state, the shared Telegram session, or
provider cookies.

The existing static file remains a migration fallback only while the
control-plane URL is absent. Once live mode is enabled for a watcher, a failed
config fetch fails closed and never silently falls back to a stale local copy.

Discord heartbeat writes remain in place until the corresponding structured
events are visible in the web application through the read API and the natural
production run has been observed. Removing them is a separately reviewed
cutover, not a side effect of enabling database reads.
