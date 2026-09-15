# IDX Swing Plan Board cron contract

See `AGENTS.md` for ownership and detailed safety boundaries.

- **Owner:** the board process is the sole mutator of its SQLite database, media, and Discord forum state. It accepts only validated internal watcher events after All Swing delivery.
- **Boundary:** deterministic and read-only. No LLM, inferred plan, trading advice, market order, or watcher-state write is allowed. SSF remains All-only.
- **Source submission:** `submit-source-event --stdin` first copies supplied local media into the owner directory, then atomically persists the validated event and owner intents and runs one best-effort drain. It may not calculate a close or post a heartbeat.
- **Scheduled reconciliation:** `after-close --phase initial` is valid only at 16:30 WIB and `--phase retry` only at 17:00 WIB. The retry runs only for a current-session unavailable initial attempt on the same active plan. Both phases use the reviewed IDX calendar, fail closed when coverage is missing, drain the owner outbox, and direct-post exactly one `#hermes` heartbeat. A second unavailable result changes only the card to `Market check unavailable`; it preserves prior valid price/time and tags and adds no history reply.
- **Runtime wrapper:** `bin/idx-swing-plan-board.sh` reads only `DISCORD_BOT_TOKEN`, uses the shared Yahoo Finance MCP Python, defaults state to `$HOME/.hermes/state/idx-swing-board.sqlite3`, and passes board arguments unchanged. The owner CLI has no database-path option.
- **Check:** set `IDX_SWING_PLAN_BOARD_NO_POST=1` and isolated state and media paths. Never reset state or create a live forum item.
- **Bootstrap:** no bootstrap command is implicit or automatic. A separately approved command is required before any externally visible backfill.
