# Bursawatch control-plane migration matrix

This matrix records the repository exploration behind the control-plane slice.
It separates operator configuration from watcher-owned runtime state, because
moving the latter would be a different, stopped-writer migration.

| Package | Current operator configuration | Current runtime state | Control-plane status |
| --- | --- | --- | --- |
| `cron-x-account-watch` | `config/watches.json`, source/profile routing, Discord destinations, LLM and thread policy | cursor, outbox, leases, media, delivery ledger, cleanup queue in the watcher state tree | Live snapshot loader, structured run events, and isolated web-write validator implemented behind opt-in environment variables |
| `cron-ig-account-watch` | `config/watches.json`, OCR and delivery policy | cursor, outbox, media, OCR cache, leases and cleanup state | Live snapshot loader, lifecycle events, and isolated web-write validator implemented behind opt-in environment variables |
| `cron-wa-channel-watch` | `config/watches.json`, Channel identity, routing and analysis policy | bridge queue, cursor, outbox and leases | Live snapshot loader, lifecycle events, and isolated web-write validator implemented behind opt-in environment variables |
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

## Desired schedule controls

The control plane now has an immutable desired-schedule model for explicitly
catalogued interval jobs. It stores enabled state, cadence, timezone, actor,
revision, checksum, and reconciliation state. A write is `pending`, not live:
the web app must show it as ineffective until a separately deployed VPS
reconciler applies it through the Hermes CLI. Calendar schedules and queue
workers that have source-defined cadence remain fixed and read-only.

## Proposed next watcher tranche

The remaining packages should move in the following order. Each source change
must first add a typed snapshot loader and its isolated write validator, then
use that frozen revision for one invocation's lifecycle events. This keeps a
run record attributable to the configuration that actually governed it.

| Order | Package | Candidate web-managed values | Structured run evidence | Deliberately excluded |
| --- | --- | --- | --- | --- |
| 1 | `cron-tg-phintraco-swing` | Source identity, All destination, heartbeat destination, and the existing supported interval job | Shared-Telegram hold or probe, fetched messages, accepted source calls, per-leg Discord delivery, board acknowledgement, retained pending work, heartbeat outcome | Cursor, media, outbox phases, retry/backoff, board wrapper path, parser grammar, and shared Telegram resilience state |
| 2 | `cron-tg-kelas-investasi-gtw` | Source identity, All destination, heartbeat destination, bounded additional LLM instruction, and its supported interval job | Shared-Telegram hold or probe, bundle detection, agent lease and validation outcome, text/header delivery, board acknowledgement, retained pending work, heartbeat outcome | Cursor, leases, media, outbox, retry/backoff, board wrapper path, agent output schema, and shared Telegram resilience state |
| 3 | `cron-tg-market-news` | Provider identities, route destinations, heartbeat destination, bounded additional LLM instruction, and its supported interval job | Per-provider fetch outcome, candidate and agent-claim counts, classification validation, per-item delivery outcome, retained pending work, heartbeat outcome | Provider cursors, candidate queue, delivery payloads, deduplication and ranking rules, retry/backoff, quote implementation, agent output schema, and shared Telegram resilience state |
| 4 | `cron-dc-swing-board` | Its already-catalogued fixed calendar schedules and run observability only | Scheduler phase, calendar coverage, reconciliation result, outbox health, and heartbeat outcome | SQLite episodes, source events, forum intent/outbox state, media, tags, market facts, Discord recovery identities, and all maintenance commands |

`additional_prompt_instruction` is additive and bounded. It can provide
operator context or wording preferences but cannot replace a source-controlled
agent contract, relax deterministic validators, modify tool authority, or
change the closed output schema.

The dashboard needs a watcher-wide chronological event feed in addition to a
single-run detail view. The next backend API slice should provide that read
model and permit signed-in viewers to read operational history, while keeping
config values and schedule writes restricted to machine and administrator
principals.
