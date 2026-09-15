# IDX Swing Plan Board cron contract

See `AGENTS.md` for ownership and detailed safety boundaries.

- **Owner:** the board process is the sole mutator of its SQLite database, media, and Discord forum state. It accepts only validated internal watcher events after All Swing delivery.
- **Boundary:** deterministic and read-only. No LLM, inferred plan, trading advice, market order, or watcher-state write is allowed. SSF remains All-only.
- **Source submission:** may persist a validated event and drain the owner outbox, but may not calculate a close or post a heartbeat.
- **Scheduled reconciliation:** only this future scheduled command may calculate a current-session close and post a direct `#hermes` heartbeat. It must use the reviewed IDX calendar and fail closed when calendar coverage is missing.
- **Check:** set `IDX_SWING_PLAN_BOARD_NO_POST=1` and isolated state and media paths. Never reset state or create a live forum item.
- **Bootstrap:** no bootstrap command is implicit or automatic. A separately approved command is required before any externally visible backfill.
