# Bursawatch Discord Swing Board cron contract

See `AGENTS.md` for ownership and detailed safety boundaries.

- **Owner:** the board process is the sole mutator of its SQLite database, media, and Discord forum state. It accepts only validated internal watcher events after All Swing delivery.
- **Boundary:** deterministic and read-only. No LLM, inferred plan, trading advice, market order, or watcher-state write is allowed. Only active cash-equity source events are eligible.
- **Source-only events:** Kelas Investasi GTW events use the `Supporting setup`
  lifecycle tier. X and other social/chart events use `Chart context`. A single
  source-only episode keeps the strongest tier present, with `Supporting setup`
  above `Chart context`. The highest-tier source event owns the starter card
  and its first chart. A newer higher-tier or same-tier source replaces that
  starter, and the superseded starter card and first chart become one normal
  source-context history reply. Neither tier alters a Phintraco Primary Plan
  or its market tags. A Phintraco BUY may promote an open source-only episode
  in place; it preserves the previous source starter once as history, without
  a separate GTW resend or All Swing replay.
- **Source submission:** `submit-source-event --stdin` first copies supplied local media into the owner directory, then atomically persists the validated event and owner intents and runs one best-effort drain. Its acknowledgement includes `accepted:true` plus the direct forum-topic `board_url` when the topic is materialized, or `board_url:null,"board_pending":true` while that topic is retryable. An accepted board-unavailable event omits `board_pending`. It may not calculate a close or post a heartbeat.
- **Scheduled reconciliation:** `after-close --phase initial` is valid only at 16:30 WIB and `--phase retry` only at 17:00 WIB on weekdays. The retry runs only for an unavailable initial attempt on the same active plan and weekday. There is deliberately no annual IDX-holiday file: Yahoo must return a bar dated exactly for that weekday, so a non-trading weekday cannot reuse an older close. An unavailable initial or retry result records only its owner attempt and a degraded `#hermes` heartbeat. It never edits the Board card, tags, checkpoints, or history. During each initial phase, a resolved topic whose resolved calendar date is two days old is durably queued for an explicit `archived:true` Discord patch. The patch preserves `Resolved` and the terminal outcome tag while adding `Archived` for a visible Board-list state. This gives the Board its two-calendar-day resolved lifecycle even though Discord natively offers no two-day auto-archive duration.
- **Runtime wrapper:** `bin/bursawatch-dc-swing-board.sh` reads only
  `DISCORD_BOT_TOKEN` for ordinary owner commands, uses the shared Yahoo
  Finance MCP Python, defaults state to
  `$HOME/.hermes/state/idx-swing-board.sqlite3`, and passes board arguments
  unchanged. The explicit `bootstrap` command additionally reads the
  Telegram credentials and imports only the shared resilience library and
  Phintraco parser it needs. The owner CLI has no database-path option.
- **Scheduler executables:** the no-argument `bursawatch-dc-swing-board-close.sh` invokes `after-close --phase initial`; `bursawatch-dc-swing-board-retry.sh` invokes `after-close --phase retry`. Both require the generic wrapper beside them. The approved weekday schedules are `30 16 * * 1-5` and `0 17 * * 1-5` in WIB, respectively. Register them with the supported Hermes CLI and record the live job IDs after deployment.
- **Live Hermes jobs:** `bursawatch-dc-swing-board-close` is `5c0b79e08fae`, and
  `bursawatch-dc-swing-board-retry` is `71c4f9a32acd` after cutover. Both are active no-agent
  jobs with `local` delivery and `/home/praya` as their working directory.
- **Forum defaults:** `#id-stocks-swing-board` uses List View, Latest Activity
  ordering, and Discord's three-day inactivity archive for ordinary inactive
  threads. The deterministic 16:30 initial phase explicitly archives Resolved
  topics after two calendar dates. Discord has no tag-first or nested tag/date
  sort; tags remain filters.
- **Delivery health:** `drain` returns JSON counts `drained`, `pending`, and `failed`, with a nonzero exit while work remains, including backoff. Ambiguous Discord creates use durable pre-POST read-back identity; inconclusive recovery stays pending without another POST. Nonce reuse alone is not durable idempotency.
- **Media and size:** the owner downloads ordered public direct X media into private storage and retries each attachment independently. Source text is split losslessly into ordered replies within 2,000 UTF-16 units; managed cards stay within the same limit with complete source replies when compacted. Retired quoted history is deletion-only maintenance, never new delivery. Unsupported or oversized media stays pending, never silently dropped.
- **Close outcomes:** stop-loss or the actual final target resolves the plan, including target ladders beyond TP6 whose factual tag clamps at TP6. The owner updates the card and tags without generating quoted history replies. Unclassifiable plans preserve prior facts, increment `invalid`, and do not block other tickers. Invalid, unavailable, and pending work degrade the heartbeat; unexpected failures emit a sanitized fatal heartbeat.
- **One-time maintenance:** `migrate-tags --apply` converts legacy `Source plan`
  episodes and rewrites their forum tag applications. `migrate-format --apply`
  rewrites existing starter cards and completed source replies through the
  shared cash-Swing renderer, moving recoverable legacy source starters and
  first charts into the starter card. `cleanup-history --apply` deletes the retired
  quoted history replies recorded by the owner. `migrate-titles --apply` makes
  every existing forum topic title ticker-only. Future source replacements keep
  that topic title stable; descriptive titles remain in starter cards.
- **Check:** set `IDX_SWING_PLAN_BOARD_NO_POST=1` and isolated state and media paths. Never reset state or create a live forum item.
- **Bootstrap:** `bootstrap --dry-run --lookback-sessions 20` reads
  Phintraco Telegram history through its resilience lease and reports candidate
  BUY/status chains without opening Board state or Discord. `bootstrap --apply
  --lookback-sessions 20` accepts only reviewed complete unresolved
  Primary-plan candidates and routes each through the ordinary immutable
  source-event and outbox path. It is never implicit, automatic, or scheduled.
  A separate explicit approval of the dry-run report is required before any
  externally visible backfill. A reviewed JSON manifest may instead select
  exact source message IDs with `--manifest <path>`; this preserves individual
  same-ticker events and can represent a status/reminder without its complete
  original BUY as source-only context. Manifest dry-run remains read-only.
  Manifest apply creates only Board owner work. Capturing each direct topic URL
  and editing the separately reviewed Yanto-owned All Swing messages are
  distinct, explicitly approved operations.
