# Bursawatch Discord Swing Board cron contract

See `AGENTS.md` for ownership and detailed safety boundaries.

- **Owner:** Board Engine is the sole writer of canonical SQLite episode/domain state, intent outboxes, and private media. The Delivery Owner service is the only Discord API writer. Board sends reads and writes through the typed shared client, persists each intent and stable key first, then applies accepted receipts and Discord IDs once. It accepts only validated internal watcher events after All Swing delivery.
- **Boundary:** deterministic and read-only. No LLM, inferred plan, trading advice, market order, or watcher-state write is allowed. Only active cash-equity source events are eligible.
- **Phintraco setup linkage:** weekly PDF plan events use one immutable source event per ticker and the PDF Telegram publication time. A matched Phintraco reminder carries the exact immutable setup event key; the Board accepts it only for that active plan. Explicit numbered target amendments update the current plan projection and rerender the card, while the original setup source event remains immutable. The watcher labels unmatched updates as `context`; context is retained as an episode reply without changing plan, lifecycle, tags, milestones, or staleness. Context with no applicable episode is stored and processed without opening a thread.
- **Source-only events:** Kelas Investasi GTW events use the `Supporting setup`
  lifecycle tier. X and other social/chart events use `Chart context`. A single
  source-only episode keeps the strongest tier present, with `Supporting setup`
  above `Chart context`. The highest-tier source event owns the starter card
  and its first chart. A newer higher-tier or same-tier source replaces that
  starter, and the superseded starter card and first chart become one normal
  source-context history reply. Neither tier alters a Phintraco Primary Plan
  or its market tags. A Phintraco BUY newer than the latest source-only
  material may promote that episode in place; it preserves the previous
  source starter once as history, without a separate GTW resend or All Swing
  replay. An older BUY is a labeled historical reply and does not promote.
- **Topic identity:** a new episode title uses its first accepted source
  timestamp in WIB, for example `CPIN - Wed, 23 Sep 2026`. Its weekday follows
  the actual date, including weekends. Promotion and source updates keep that
  opening title. `migrate-titles --apply` repairs an existing title from its
  stored ticker and opening timestamp.
- **Source submission:** `submit-source-event --stdin` first copies supplied local media into the owner directory, then atomically persists the validated event and owner intents and runs one best-effort drain. Its acknowledgement includes `accepted:true` plus the direct forum-topic `board_url` when the topic is materialized, or `board_url:null,"board_pending":true` while that topic is retryable. An accepted board-unavailable event omits `board_pending`. It may not calculate a close or post a heartbeat.
- **Scheduled reconciliation:** `after-close --phase initial` is scheduled for 16:30 WIB and `--phase retry` for 17:00 WIB. Each phase accepts a start within the following five minutes to tolerate Hermes scheduler lateness, while earlier or later invocations are ignored. The retry runs only for a current-session unavailable initial attempt on the same active plan. Both phases use the reviewed IDX calendar. Missing coverage makes no board mutation, drains safely, and persists one fatal `#hermes` heartbeat intent; covered phases persist exactly one normal or degraded heartbeat intent. All heartbeat intents use the typed Delivery Owner channel operation and remain durable for retry. A second unavailable result changes only the card to `Market check unavailable`; it preserves prior valid price/time and tags and adds no history reply.
- **Daily lifecycle:** `reconcile-lifecycle` runs at 17:10 WIB daily, including
  non-trading days. It resolves open episodes at 20 reviewed IDX trading
  sessions after their last material source date. Only a Phintraco BUY or
  material Phintraco status resets a Primary timer; qualifying source events
  reset a source-only timer. It states `stale` or `superseded` in the card,
  removes the market tag for those reasons, and retains the last valid close
  price, check time, and state or explicitly reports that none exists. Terminal stop-loss and
  final-target resolutions retain their factual market tag. Once resolution
  changes and all earlier episode messages are delivered or tombstoned, a
  48-hour quiet timer starts. Late historical replies restart it on delivery.
  The pass then queues an archive intent and records the accepted receipt.
  Calendar coverage fails closed. Every pass, including no-op and degraded
  runs, queues a durable `#hermes` heartbeat through Delivery Owner.
- **Runtime wrapper:** `bin/bursawatch-dc-swing-board.sh` reads only
  `BURSAWATCH_DISCORD_DELIVERY_URL` and
  `BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE`, plus its optional
  `IDX_SWING_PLAN_BOARD_CONTROL_PLANE_*` settings for ordinary owner commands,
  uses the shared Yahoo Finance MCP
  Python, defaults state to
  `$HOME/.hermes/state/idx-swing-board.sqlite3`, and passes board arguments
  unchanged. The live control-plane config can change only the heartbeat
  Discord destination and records structured run events. Each event is
  attempted immediately; failed requests remain in the durable local request
  spool for a later retry. A temporary control-plane outage does not block
  board reconciliation or Delivery Owner submission. Accepted records are stored by the
  control plane in Postgres tables `bursawatch_runs` and `bursawatch_events`.
  The forum/guild
  topology is durable-state owned and not web-editable. The explicit `bootstrap` command additionally reads the
  Telegram credentials and imports only the shared resilience library and
  Phintraco parser it needs. The owner CLI has no database-path option.
- **Scheduler executables:** the no-argument `bursawatch-dc-swing-board-close.sh` invokes `after-close --phase initial`; `bursawatch-dc-swing-board-retry.sh` invokes `after-close --phase retry`; `bursawatch-dc-swing-board-lifecycle.sh` invokes `reconcile-lifecycle`. All require the generic wrapper beside them. The close and retry weekday schedules are `30 16 * * 1-5` and `0 17 * * 1-5` in WIB. The lifecycle schedule is `10 17 * * *` in WIB. The lifecycle registration remains a separate reviewed Hermes operation; record its live job ID after approval and deployment.
- **Live Hermes jobs:** `bursawatch-dc-swing-board-close` is `5c0b79e08fae`, and
  `bursawatch-dc-swing-board-retry` is `71c4f9a32acd` after cutover. Both are active no-agent
  jobs with `local` delivery and `/home/praya` as their working directory.
- **Forum defaults:** `#id-stocks-swing-board` uses List View, Latest Activity
  ordering, and Discord's three-day inactivity archive. Discord has no
  tag-first or nested tag/date sort; tags remain filters.
- **Delivery health:** `drain` returns JSON counts `drained`, `pending`, and `failed`, with a nonzero exit while work remains, including backoff. Board persists each desired operation and stable key before submission. The Delivery Owner stores create snapshots and does bounded read-back; Board retries status lookup by the same key and never submits a new create for an ambiguous outcome. Accepted receipts and IDs apply once to Board state. Nonce reuse alone is not durable idempotency.
- **Media and size:** the owner downloads ordered public direct X media into private storage and retries each attachment independently. Source text is split losslessly into ordered replies within 2,000 UTF-16 units; managed cards stay within the same limit with complete source replies when compacted. Retired quoted history is deletion-only maintenance, never new delivery. Unsupported or oversized media stays pending, never silently dropped.
- **Close outcomes:** stop-loss or the actual final target resolves the plan, including target ladders beyond TP6 whose factual tag clamps at TP6. The owner updates the card and tags without generating quoted history replies. Unclassifiable plans preserve prior facts, increment `invalid`, and do not block other tickers. Invalid, unavailable, and pending work degrade the heartbeat; unexpected failures emit a sanitized fatal heartbeat.
- **One-time maintenance:** `migrate-tags --apply` converts legacy `Source plan`
  episodes and rewrites their forum tag applications. `migrate-format --apply`
  rewrites existing starter cards and completed source replies through the
  shared cash-Swing renderer, moving recoverable legacy source starters and
  first charts into the starter card. `cleanup-history --apply` deletes the retired
  quoted history replies recorded by the owner. `migrate-titles --apply` repairs
  each existing forum topic title from the ticker and stored opening date.
  Future source replacements keep that title stable; descriptive titles remain
  in starter cards.
- **Image filename repair:** `repair-starter-media --event-key <key>
  --expected-thread-id <id>` previews one active source card repair. Add
  `--apply` to replace its attachment in place through the durable owner outbox;
  it never creates a new forum thread.
- **Handoff:** `bin/delivery_handoff.py --plan <private-plan-path>` writes a payload-free, read-only plan preserving known forum/thread/starter/reply IDs and persisted create snapshots. Historical `Source plan` tag names are translated from canonical episode state and source records before resolving current Discord tag IDs. `--apply <private-plan-path>` also requires `BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY=1` and a Delivery Owner admin token file; it imports through the service and writes only a private acknowledgment sidecar, preserving the Board SQLite source.
- **Check:** set `IDX_SWING_PLAN_BOARD_NO_POST=1` and isolated state and media paths. The local fake is selected before Delivery Owner client settings are read, so no-post tests never reach a live service. Never reset state or create a live forum item.
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
