# IDX Swing Plan Board

This file supplements the repository root `AGENTS.md`. It is the canonical development and operations guide for this deterministic no-agent board owner.

## Ownership and boundary

The board owner alone mutates its SQLite database, private media directory, forum threads, starter cards, replies, titles, tags, history, and archival state. It accepts only validated internal watcher events after their All Swing delivery. It never imports a watcher store or writes watcher state.

The board is read-only and factual. It has no LLM, does not infer a plan or a price state, does not give trading advice, and does not place orders. Only a complete Phintraco Daily cash-equity BUY creates or replaces a Primary Plan. SSF never submits a board event.

## Commands and safety

`submit-source-event --stdin` validates one event, copies supplied local media into the owner media root, atomically commits the immutable event plus its owner intents, then performs one best-effort drain. It may not calculate a close and does not post a heartbeat. A durable accepted event remains accepted when Discord work is retryable.

Only scheduled `after-close --phase initial` at 16:30 WIB and `after-close --phase retry` at 17:00 WIB evaluate a valid current IDX session close. The retry is eligible only when that exact active plan recorded an unavailable initial attempt for the current reviewed IDX session. A second unavailable result edits only the card to `Market check unavailable`, retaining the latest valid price/time and tags, without a history reply. A valid close writes a history reply only on an exact market-state transition. Every scheduled phase drains and direct-posts one `#hermes` heartbeat.

Set `IDX_SWING_PLAN_BOARD_NO_POST=1` with isolated `IDX_SWING_PLAN_BOARD_STATE_PATH` and `IDX_SWING_PLAN_BOARD_MEDIA_ROOT` paths for every smoke test. Never reset, hand-edit, initialize, replay, or bootstrap production state. Bootstrap is an externally visible backfill and requires a separately approved command.

## Development and deployment

Run the focused suite from the repository root with the shared virtual environment:

```bash
../../.venv/bin/python -m pytest -q idx-swing-plan-board/tests
```

Deploy only a clean published commit after an approved VPS write, then compare changed checksums and use isolated no-post verification. This task creates source only and does not deploy, schedule, bootstrap, or change production state.
