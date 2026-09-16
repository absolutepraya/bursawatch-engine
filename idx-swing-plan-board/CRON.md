# IDX Swing Plan Board cron contract

See `AGENTS.md` for ownership and detailed safety boundaries.

- **Owner:** the board process is the sole mutator of its SQLite database, media, and Discord forum state. It accepts only validated internal watcher events after All Swing delivery.
- **Boundary:** deterministic and read-only. No LLM, inferred plan, trading advice, market order, or watcher-state write is allowed. Only active cash-equity source events are eligible.
- **Source-only events:** Kelas Investasi GTW events use the `Supporting setup`
  lifecycle tier. X and other social/chart events use `Chart context`. A single
  source-only episode keeps the strongest tier present, with `Supporting setup`
  above `Chart context`. Neither tier alters a Phintraco Primary Plan or its
  market tags. A Phintraco BUY may promote an open source-only episode in
  place; the owner keeps original replies and queues exactly one fresh latest-
  GTW reply below the new starter with a durable promotion dedupe key. This
  handoff is board only and does not replay the All Swing feed.
- **Source submission:** `submit-source-event --stdin` first copies supplied local media into the owner directory, then atomically persists the validated event and owner intents and runs one best-effort drain. It may not calculate a close or post a heartbeat.
- **Scheduled reconciliation:** `after-close --phase initial` is valid only at 16:30 WIB and `--phase retry` only at 17:00 WIB. The retry runs only for a current-session unavailable initial attempt on the same active plan. Both phases use the reviewed IDX calendar. Missing coverage makes no board mutation, drains safely, and direct-posts one fatal `#hermes` heartbeat; covered phases direct-post exactly one normal or degraded heartbeat. A second unavailable result changes only the card to `Market check unavailable`; it preserves prior valid price/time and tags and adds no history reply.
- **Runtime wrapper:** `bin/idx-swing-plan-board.sh` reads only `DISCORD_BOT_TOKEN`, uses the shared Yahoo Finance MCP Python, defaults state to `$HOME/.hermes/state/idx-swing-board.sqlite3`, and passes board arguments unchanged. The owner CLI has no database-path option.
- **Scheduler executables:** the no-argument `idx-swing-plan-board-close.sh` invokes `after-close --phase initial`; `idx-swing-plan-board-retry.sh` invokes `after-close --phase retry`. Both require the generic wrapper beside them. The approved weekday schedules are `30 16 * * 1-5` and `0 17 * * 1-5` in WIB, respectively. Register them with the supported Hermes CLI and record the live job IDs after deployment.
- **Delivery health:** `drain` returns JSON counts `drained`, `pending`, and `failed`, with a nonzero exit while work remains, including backoff. Ambiguous Discord creates use durable pre-POST read-back identity; inconclusive recovery stays pending without another POST. Nonce reuse alone is not durable idempotency.
- **Media and size:** the owner downloads ordered public direct X media into private storage and retries each attachment independently. Source text is split losslessly into ordered replies within 2,000 UTF-16 units; managed cards stay within the same limit with complete source replies when compacted. Retired quoted history is deletion-only maintenance, never new delivery. Unsupported or oversized media stays pending, never silently dropped.
- **Close outcomes:** stop-loss or the actual final target resolves the plan, including target ladders beyond TP6 whose factual tag clamps at TP6. The owner updates the card and tags without generating quoted history replies. Unclassifiable plans preserve prior facts, increment `invalid`, and do not block other tickers. Invalid, unavailable, and pending work degrade the heartbeat; unexpected failures emit a sanitized fatal heartbeat.
- **One-time maintenance:** `migrate-tags --apply` converts legacy `Source plan`
  episodes and rewrites their forum tag applications. `migrate-format --apply`
  rewrites existing starter cards and completed source replies through the
  shared cash-Swing renderer. `cleanup-history --apply` deletes the retired
  quoted history replies recorded by the owner.
- **Check:** set `IDX_SWING_PLAN_BOARD_NO_POST=1` and isolated state and media paths. Never reset state or create a live forum item.
- **Bootstrap:** no bootstrap command is implicit or automatic. A separately approved command is required before any externally visible backfill.
