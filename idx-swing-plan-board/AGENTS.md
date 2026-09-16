# IDX Swing Plan Board

This file supplements the repository root `AGENTS.md`. It is the canonical development and operations guide for this deterministic no-agent board owner.

## Ownership and boundary

The board owner alone mutates its SQLite database, private media directory, forum threads, starter cards, replies, titles, tags, history, and archival state. It accepts only validated internal watcher events after their All Swing delivery. It never imports a watcher store or writes watcher state.

The board is read-only and factual. It has no LLM, does not infer a plan or a price state, does not give trading advice, and does not place orders. Only a complete Phintraco Daily cash-equity BUY creates or replaces a Primary Plan. SSF never submits a board event.

## Commands and safety

`submit-source-event --stdin` validates one event, copies supplied local media into the owner media root, atomically commits the immutable event plus its owner intents, then performs one best-effort drain. It may not calculate a close and does not post a heartbeat. A durable accepted event remains accepted when Discord work is retryable.

Ordered X media URLs become separate durable attachment intents. Only public HTTPS `pbs.twimg.com` and `video.twimg.com` URLs are accepted. The owner downloads validated image/MP4 content into private atomic cache files, with an 8 MiB limit per attachment, bounded timeouts and redirects, and no inherited credentials or proxy settings. Acquisition and upload failures retain the intent; upload retries reuse the owner copy. No-post skips remote acquisition. All source replies are split losslessly into at most 2,000 UTF-16 units per message. Managed cards reserve checkpoint space; compacted source fields remain complete in ordered source replies. Type and already escaped rationale retain their source rendering.

Before a Discord create, the owner persists its operation identity, exact message/attachment identity, bot ID, and read-back boundary. After timeout or interruption, it searches subsequent own messages or active/public-archived forum threads before completing that intent. Stable nonces are only a short-window aid, not durable idempotency. An inconclusive, ambiguous, or exhausted bounded search stays pending without another create; operator investigation requires separate approval. Only a definite rejected POST clears the create snapshot. A separate delivery lock prevents overlapping HTTP workers, and 429 retries honor Discord's delay.

`drain` reports `drained`, `pending`, and `failed` counts and exits nonzero while any work remains. Pending includes retained backoff work; failed counts pending operations with a recorded delivery failure.

Only scheduled `after-close --phase initial` at 16:30 WIB and `after-close --phase retry` at 17:00 WIB evaluate a valid current IDX session close. The zero-argument scheduler executables are `idx-swing-plan-board-close.sh` and `idx-swing-plan-board-retry.sh`, respectively. The retry is eligible only when that exact active plan recorded an unavailable initial attempt for the current reviewed IDX session. A second unavailable result edits only the card to `Market check unavailable`, retaining the latest valid price/time and tags, without a history reply. A valid close writes history on an exact market-state or terminal-lifecycle transition, with operation identity scoped to plan and session. Stop-loss or the actual final target resolves and finishes the plan; target tags clamp at TP6 without shortening the target ladder. History replies are losslessly split into ordered, quoted messages within Discord's 2,000 UTF-16-unit limit. An unclassifiable plan preserves its facts, increments `invalid`, and does not block other tickers. Missing calendar coverage fails closed without a board mutation, drains safely, and emits one fatal `#hermes` heartbeat. Other unexpected reconciliation failures emit a sanitized fatal heartbeat. Every covered scheduled phase drains and direct-posts one normal or degraded `#hermes` heartbeat, warning on unavailable, invalid, or pending work.

Set `IDX_SWING_PLAN_BOARD_NO_POST=1` with isolated `IDX_SWING_PLAN_BOARD_STATE_PATH` and `IDX_SWING_PLAN_BOARD_MEDIA_ROOT` paths for every smoke test. Never reset, hand-edit, initialize, replay, or bootstrap production state. Bootstrap is an externally visible backfill and requires a separately approved command.

## Development and deployment

Run the focused suite from the repository root with the shared virtual environment:

```bash
../../.venv/bin/python -m pytest -q idx-swing-plan-board/tests
```

Deploy only a clean published commit after an approved VPS write, then compare changed checksums and use isolated no-post verification. Copy the generic wrapper plus both phase wrappers to the same Hermes scripts directory after approval. Neither scheduler registration is authorized by this source change. This task creates source only and does not deploy, schedule, bootstrap, or change production state.
