# PolyCop Telegram Resilience Design

**Date:** 2026-08-09  
**Status:** Approved design, awaiting implementation plan  
**Scope:** Four automated Hermes market watchers that use `POLYCOP_SESSION_STRING`

## Goal

Make temporary Telegram connectivity failures a single, controlled PolyCop-session incident rather than independent retry storms across the affected watchers. Preserve every watcher cursor and delivery outbox during an outage, keep operations notifications concise, and make a genuine Telegram authorization failure distinguishable from a transport outage.

The affected watchers are:

- `idx-market-news-watch`
- `idx-swing-watch-phintraco-daily`
- `idx-ssf-watch-phintraco-weekly`
- `polymarket-signal-watch`

## Decisions

- Build a shared in-process Python module named `telegram-resilience`; do not add a Hermes cron, systemd service, daemon, database, or persistent Telegram connection.
- Limit v1 to the four watchers above. They share `POLYCOP_SESSION_STRING`.
- Do not change the Hermes gateway `telegram-mcp` or SCELE's `tg-window` helper. They use the separate personal `TELEGRAM_SESSION_STRING` profile.
- The module does not store credentials and does not create a Telegram client. Each scanner retains its existing Telethon client and supplies its normal connection attempt to the module.
- Do not advance a source cursor, mutate a watcher outbox, or send a market alert while Telegram is unavailable.
- Use a shared durable state file and a rotating, structured 30-day diagnostic log. Do not introduce a database.
- Keep existing regular heartbeat cadence unchanged. For each shared incident, post only one outage or authorization-required notice and one recovery notice to `#hermes`.
- All handled resilience failures return cleanly with `wakeAgent:false` and exit zero. In particular, `idx-market-news-watch` must not wake Hermes's agent after a deterministic Telegram collection failure.

## Architecture

```text
idx-market-news-watch -----------+
idx-swing-watch-phintraco-daily -+--> telegram-resilience --> shared state and diagnostic log
idx-ssf-watch-phintraco-weekly --+                 |
polymarket-signal-watch ---------+                 +--> each scanner's existing Discord sender
```

`telegram-resilience` is deployed to one runtime location and imported by all four scanners. The wrappers make that import location available through a controlled `PYTHONPATH` entry. The source module remains in this Hermes development directory and is deployed separately from the individual watcher `bin/` directories.

The module exposes a narrow connection guard interface:

1. A scanner asks whether it may attempt a PolyCop-session connection.
2. If granted, the scanner runs its normal Telethon `connect()` flow through the guard.
3. The scanner verifies authorization with `is_user_authorized()` and `get_me()` before reporting a healthy session.
4. The guard returns either permission to continue, a handled unavailable result, or an authorization-required result.
5. The scanner claims any pending incident notification through the guard, posts it using its existing Discord sender, then acknowledges the notification only after Discord accepts it.

The guard never calls Telegram beyond the connection function supplied by a scanner, never sends a Telegram message, and never posts Discord itself. This preserves the existing scanner ownership boundaries.

## Shared state and diagnostic log

The durable state path is:

```text
~/.hermes/state/telegram-resilience-polyclop.json
```

The diagnostic log path is:

```text
~/.logs/telegram-resilience-polyclop.jsonl
```

The state contains a versioned schema with:

- circuit status: `closed`, `probing`, `transport_open`, or `auth_required`
- consecutive failed probes, next probe time, and a crash-safe probe lease expiry
- the current incident ID, opened time, last safe error classification, and set of affected watcher names
- last authenticated success time and safe Telethon connection metadata such as DC ID and selected endpoint
- pending outage, authorization-required, and recovery notification records with claim lease and acknowledgement status

It must not contain API credentials, session strings, raw authorization headers, or source-message data. JSONL records include timestamp, watcher, state transition, safe error class, and safe timing metadata. Rotation retains 30 calendar days.

All state mutations use an advisory file lock, schema validation, atomic replace, restrictive file permissions, and explicit stale-lease recovery. A process crash must not leave a permanent probe or notification claim lock.

## Connection state machine

### Healthy state

When the circuit is `closed`, a watcher acquires the short probe lease, attempts its normal Telethon connection, verifies authorization, records success, and continues its existing poll and delivery behavior. A normal healthy run creates no resilience notification.

### Transport failure

A complete Telethon connection failure, including its own bounded retries, is classified as a transport failure when it is a timeout, socket, DNS, TLS, or other reachability failure. The first such failure:

1. opens one `transport_open` incident;
2. creates one pending outage notification;
3. records the failing watcher in the incident; and
4. schedules the next probe after a 60-second cooldown.

Later failed probes double the cooldown, add bounded jitter, and cap at 15 minutes. Other watchers that run while a live probe lease or cooldown exists do not initiate another Telegram connection. They add their name to the affected watcher set, preserve their own state, and exit successfully with `wakeAgent:false`.

### Recovery

The first successful authenticated connection after a `transport_open` or `auth_required` incident closes the circuit, clears backoff, records the recovery timestamp, and creates one pending recovery notification. The recovery notice includes the incident duration and all affected watcher names. It is not considered delivered until a scanner's Discord sender acknowledges it.

### Authorization failure

An unauthorized session, explicit Telegram authorization rejection, or failed `is_user_authorized()` check opens an `auth_required` incident. This state does not perform periodic connection retries. All four watchers skip Telegram safely until a human renews the existing PolyCop session. The first subsequent authenticated connection records recovery and emits the one recovery notice.

### Control-plane state failure

If shared resilience state is unreadable or fails schema validation, preserve the file for inspection and do not silently overwrite it. Treat it as a control-plane incident: no watcher initiates an uncontrolled Telegram connection, no watcher advances a cursor, and one safe `#hermes` notice is retried through the durable notification protocol. Repair is deliberate and must not reset watcher state.

## Notification behavior

Incident notifications target the existing `#hermes` channel (`1505162000420835388`) through the scanner that owns the valid Discord sender. They use a stable event key derived from `<incident-id>:<event-type>`.

Examples:

```text
❌ telegram-polycop · 15:16 WIB · transport unavailable; affected=idx-market-news-watch,idx-swing-watch-phintraco-daily
🫀 telegram-polycop · 15:17 WIB · recovered after 1m; affected=idx-market-news-watch,idx-swing-watch-phintraco-daily,polymarket-signal-watch
❌ telegram-polycop · 15:16 WIB · authorization required; manual PolyCop session login needed
```

If Discord is unavailable, the notice remains pending with a claim lease. A later watcher retries it using the same event key. The normal heartbeat behavior for each watcher stays as it is today; no per-minute resilience spam is added.

## Watcher integration

All four scanners must use the same module contract before their first Telegram read or Telegram bot interaction.

| Watcher | On unavailable PolyCop session | Existing watcher state |
| --- | --- | --- |
| `idx-market-news-watch` | Return `wakeAgent:false`, exit zero, do not invoke the agent | Provider cursors, candidates, retries, and delivery outbox unchanged |
| `idx-swing-watch-phintraco-daily` | Return `wakeAgent:false`, exit zero | Source cursor and alert outbox unchanged |
| `idx-ssf-watch-phintraco-weekly` | Return `wakeAgent:false`, exit zero | Source cursor and alert outbox unchanged |
| `polymarket-signal-watch` | Return `wakeAgent:false`, exit zero, do not message PolyCop analysis bots | Signal cursor, processing state, and AI cache unchanged |

The integration must not change source parsing, market policy, Discord destination channels, existing cron schedules, durable watcher-state schemas, or the Telegram permissions of the PolyCop session.

## Correctness requirements

The implementation must prove these invariants:

1. At most one live PolyCop connection probe exists across the four watchers.
2. A single transport incident creates at most one outage notification and one recovery notification, even when several watchers run concurrently.
3. A failed or skipped Telegram poll cannot advance a watcher cursor or discard queued Discord delivery.
4. A failed Discord incident-notification post remains retryable and cannot create duplicate messages after acknowledgement.
5. A stale process lease eventually expires, allowing a later watcher to probe.
6. A genuine authorization failure stops automatic retries and requires manual re-login.
7. State and logs never expose Telegram credentials or session strings.
8. Existing successful watcher behavior remains unchanged when the circuit is closed.

## Tests

Create a focused `telegram-resilience` test suite with an injected clock, temporary state path, fake Telethon clients, and fake Discord acknowledgement callbacks. It must cover:

- first transport failure and shared incident creation;
- four concurrent callers, with one lease owner and three safe skips;
- exponential backoff, jitter bounds, capped delay, and stale lease takeover;
- successful authenticated recovery after a transport outage;
- unauthorized session and manual-relogin recovery;
- malformed state preservation and safe control-plane failure;
- notification claim, Discord failure, lease expiry, retry, acknowledgement, and idempotency;
- redaction of credential-shaped values from state and log records.

Add integration tests for each watcher adapter using its real scanner boundary and fake Telegram/Discord dependencies. They must prove that unavailable, skipped, and authorization-required outcomes preserve the relevant cursor and outbox and produce `wakeAgent:false` with exit zero. Add a regression test for Market News that proves a collector failure cannot wake the Hermes agent.

Run every affected watcher suite separately with the shared project environment to avoid cross-project test-module collisions.

## Safe live verification

Provide a `telegram-resilience probe` command for the existing PolyCop profile. It only performs `connect()`, authorization verification, and `get_me()`. It accepts an isolated state path and never reads a market channel, sends a Telegram message, posts Discord, changes watcher state, or runs a Hermes schedule.

After focused and complete tests pass:

1. Deploy the common runtime module first.
2. Deploy the four changed scanner and wrapper integrations through the existing checked source-to-VPS flow.
3. Compare local and VPS SHA-256 checksums for every changed runtime file.
4. Run the safe probe with an isolated resilience state path.
5. Run isolated no-post checks for the three read-only source watchers only.
6. Do not run Polymarket's scanner as a smoke test, because it may message an analysis bot.
7. Do not manually trigger a Hermes schedule. Observe natural scheduled executions, inspect state and diagnostic log transitions, then verify Discord history for the expected absence of unwanted notices.

## Out of scope

- Changing the gateway `telegram-mcp` session or SCELE's `tg-window` helper.
- Creating a new Hermes job, systemd service, daemon, database, or persistent Telegram connection.
- Re-authenticating the PolyCop session automatically.
- Resetting, migrating, replaying, or manually editing any live watcher state.
- Changing source parsing, trading policy, Discord alert channels, schedules, or notification cadence unrelated to resilience incidents.
- Posting, deleting, replaying, or backfilling external messages during tests or verification.
