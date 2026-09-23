# Bursawatch Discord Swing Board

This file supplements the repository root `AGENTS.md`. It is the canonical development and operations guide for this deterministic no-agent board owner.

## Ownership and boundary

The board owner alone mutates its SQLite database, private media directory, forum threads, starter cards, replies, titles, tags, legacy history records, and archival state. It accepts only validated internal watcher events after their All Swing delivery. It never imports a watcher store or writes watcher state.

The board is read-only and factual. It has no LLM, does not infer a plan or a price state, does not give trading advice, and does not place orders. Only a complete Phintraco Daily cash-equity BUY creates or replaces a Primary Plan. Only active cash-equity source events may reach the board. When a complete BUY promotes an open source-only episode, already-recorded Phintraco status or reminder context after that BUY is reconciled against the new plan before the transition completes.

Kelas Investasi GTW is a qualifying source-only cash-Swing input. It may open
or append to a `Supporting setup` episode, but it never becomes the Primary Plan
and never changes Phintraco status or market tags. X and other social/chart
sources use the weaker `Chart context` tier. A single source-only episode uses
the strongest tier present, with `Supporting setup` above `Chart context`.
The highest-tier source event owns the starter card and its first chart. A
newer higher-tier or same-tier source replaces that starter and preserves the
superseded starter card and first chart as one normal source-context history
reply. When a complete Phintraco BUY promotes an open source-only episode, the
owner edits the top card, changes the lifecycle tag to `Primary plan`, and
preserves the previous source starter once as history. The board never creates
a separate GTW resend and never replays the All Swing feed. An archived episode
receives no later source event.

Every forum topic title is the ticker only, for example `CPIN`. Descriptive
source and plan titles remain in the starter card. Source promotion, status
updates, and same-tier replacements never rename the topic. The one-time
`migrate-titles --apply` command renames existing topics to this stable form.

## Commands and safety

`submit-source-event --stdin` validates one event, copies supplied local media into the owner media root, atomically commits the immutable event plus its owner intents, then performs one best-effort drain. It may not calculate a close and does not post a heartbeat. Its JSON acknowledgement is `{"accepted":true,"board_url":"https://discord.com/channels/940285152335110204/<thread-id>"}` when the exact topic is materialized, or `board_url:null,"board_pending":true` while that topic is still retryable. A durable accepted event with no applicable topic omits `board_pending`; a durable accepted event remains accepted when Discord work is retryable.

Ordered X media URLs become separate durable attachment intents. Only public HTTPS `pbs.twimg.com` and `video.twimg.com` URLs are accepted. The owner downloads validated image/MP4 content into private atomic cache files, with an 8 MiB limit per attachment, bounded timeouts and redirects, and no inherited credentials or proxy settings. Acquisition and upload failures retain the intent; upload retries reuse the owner copy. No-post skips remote acquisition. All source replies are split losslessly into at most 2,000 UTF-16 units per message. Managed cards reserve checkpoint space; compacted source fields remain complete in ordered source replies. Type and already escaped rationale retain their source rendering.

Before a Discord create, the owner persists its operation identity, exact message/attachment identity, bot ID, and read-back boundary. After timeout or interruption, it searches subsequent own messages or active/public-archived forum threads before completing that intent. Stable nonces are only a short-window aid, not durable idempotency. An inconclusive, ambiguous, or exhausted bounded search stays pending without another create; operator investigation requires separate approval. Only a definite rejected POST clears the create snapshot. A separate delivery lock prevents overlapping HTTP workers, and 429 retries honor Discord's delay.

`drain` reports `drained`, `pending`, and `failed` counts and exits nonzero while any work remains. Pending includes retained backoff work; failed counts pending operations with a recorded delivery failure.

Only scheduled `after-close --phase initial` at 16:30 WIB and `after-close --phase retry` at 17:00 WIB evaluate a valid current IDX session close. Each phase accepts a start within the following five minutes to tolerate Hermes scheduler lateness, while later or early invocations are ignored. The zero-argument scheduler executables are `bursawatch-dc-swing-board-close.sh` and `bursawatch-dc-swing-board-retry.sh`, respectively. The retry is eligible only when that exact active plan recorded an unavailable initial attempt for the current reviewed IDX session. A second unavailable result edits only the card to `Market check unavailable`, retaining the latest valid price/time and tags, without a history reply. A valid close updates the card and factual tags on an exact market-state or terminal-lifecycle transition, with operation identity scoped to plan and session. Stop-loss or the actual final target resolves and finishes the plan; target tags clamp at TP6 without shortening the target ladder. The owner does not generate quoted history replies. An unclassifiable plan preserves its facts, increments `invalid`, and does not block other tickers. Missing calendar coverage fails closed without a board mutation, drains safely, and emits one fatal `#hermes` heartbeat. Other unexpected reconciliation failures emit a sanitized fatal heartbeat. Every covered scheduled phase drains and direct-posts one normal or degraded `#hermes` heartbeat, warning on unavailable, invalid, or pending work.

## Control-plane boundary

The optional live control-plane snapshot is limited to the operational
heartbeat destination:

```json
{
  "version": 1,
  "destinations": {
    "heartbeat_discord_channel_id": "1505162000420835388"
  }
}
```

With no `IDX_SWING_PLAN_BOARD_CONTROL_PLANE_URL`, the reviewed value above is
used. With that URL configured, a missing or invalid snapshot stops the
command before the SQLite store opens. Scheduled close runs and accepted source
events record structured control-plane lifecycle and delivery events when a
live revision is active. Each event is attempted immediately; failed requests
remain in the control-plane client's durable local spool for a later retry.
Control-plane delivery is observability, so a temporary API failure does not
block the board's own SQLite reconciliation and Discord delivery. The control
plane stores the accepted records in Postgres tables `bursawatch_runs` and
`bursawatch_events`; the board SQLite database remains domain and outbox state,
not a duplicate run-log store.

The forum and guild identities, calendar, SQLite/media paths, lifecycle/tag
rules, and thread topology deliberately remain code or durable-state owned.
Existing outbox and episode records reference their current Discord topics, so
changing the forum through the web would need a separately reviewed state and
forum migration. The close and retry schedules are fixed market-calendar jobs,
not web-editable interval schedules.

Set `IDX_SWING_PLAN_BOARD_NO_POST=1` with isolated `IDX_SWING_PLAN_BOARD_STATE_PATH` and `IDX_SWING_PLAN_BOARD_MEDIA_ROOT` paths for every smoke test. Never reset, hand-edit, initialize, or replay production state.

`bootstrap --dry-run --lookback-sessions 20` is a Telegram-history
reconstruction report only. It reads the Phintraco source through the shared
resilience lease and deliberately does not open Board state or Discord.
`bootstrap --dry-run --lookback-sessions 30 --manifest <path>` validates a
reviewed JSON list of exact source message IDs, preserves every listed event
even when tickers match, and reports the parsed event identity without opening
Board state or Discord. A manifest may label an orphan Phintraco
status/reminder as `social` context, which explicitly avoids inventing a
Primary Plan.
`bootstrap --apply --lookback-sessions 20` is an externally visible
backfill. It accepts only reviewed, unresolved, complete Primary-plan
candidates, reuses the normal immutable source-event and outbox contracts, and
may run only after separate explicit approval of the dry-run report. It is
never scheduled or automatic. The generic wrapper obtains Telegram credentials
and imports the Phintraco parser only for this explicit command.
`bootstrap --apply --lookback-sessions 30 --manifest <path>` applies only
the listed message-level events through that same owner contract. It does not
send an All Swing alert or edit an existing All message. Capture each resulting
forum-topic URL, then separately patch only the reviewed Yanto-owned All
message IDs to the raw direct Discord URL.

The one-time tag migration is `migrate-tags --apply`; it converts legacy
`Source plan` episodes to their source-specific tier and rewrites existing
forum tag applications. The one-time presentation migration is
`migrate-format --apply`; it rewrites existing starter cards and completed
source replies, including completed history replies, through the shared cash-Swing renderer, moves recoverable legacy
source starters and first charts into the starter card, and removes only the
duplicated legacy source replies. The Phintraco legacy
rewriter also promotes source-footer analyst names, normalizes ticker-first
titles, dates, field spacing, source status, and footer links. The approved retirement of legacy quoted history is
`cleanup-history --apply`; it deletes only message IDs recorded in
`history_events` and must run against live Discord, never with the no-post
control.

The one-time `migrate-titles --apply` command renames existing forum topics to
their ticker-only names without changing starter content or tags.

`repair-starter-media --event-key <key> --expected-thread-id <id>` previews a
single open source starter whose image lost its filename type extension. It
requires the exact current starter event and thread, an unarchived unlocked
forum topic, the original single attachment, and matching image bytes. Add
`--apply` to queue an in-place edit through the durable owner outbox. The
command refuses resolved, archived, changed, or ambiguous topics and never
creates a replacement thread.

The live forum defaults to List View, Latest Activity ordering, and a
three-day inactivity archive. Discord does not support tag-first or nested
tag-then-date ordering; tags remain user-selectable filters.

## Development and deployment

Run the focused suite from the repository root with the shared virtual environment:

```bash
../../.venv/bin/python -m pytest -q cron-dc-swing-board/tests
```

Deploy only a clean published commit after an approved VPS write, then compare changed checksums and use isolated no-post verification. Copy the generic wrapper plus both phase wrappers to the same Hermes scripts directory after approval. The two cutover target Hermes jobs are `bursawatch-dc-swing-board-close` at 16:30 WIB and `bursawatch-dc-swing-board-retry` at 17:00 WIB on weekdays. Never hand-edit the Hermes registry; use the supported CLI and verify the returned job records. Bootstrap has no scheduler entry.
