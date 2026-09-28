# Swing Board Lifecycle Implementation Plan

> **For agentic workers:** Use the approved subagent-driven workflow. Steps use checkbox syntax for tracking.

**Goal:** Make the Board owner resolve inactive episodes durably and archive resolved threads after a delivered 48-hour quiet period.

**Architecture:** Keep lifecycle state in Board SQLite and all Discord writes in the existing Delivery Owner outbox. Add one daily owner reconciliation command that counts reviewed IDX sessions, resolves stale episodes, starts quiet timers only after all episode deliveries finish, and archives eligible threads. The daily job runs at 17:10 WIB so it follows close and retry jobs while keeping heartbeat traffic to one run per day.

**Tech Stack:** Python 3, SQLite, pytest, Hermes scheduler wrapper, shared Discord Delivery Owner.

**Spec:** `docs/superpowers/specs/2026-09-23-swing-board-shared-architecture-design.md`

## Global Constraints

- Only the Board owner changes canonical episode state.
- All Discord mutations use the existing durable outbox and shared Delivery Owner.
- The 20-session clock measures inactivity, counting IDX sessions strictly after the last material source-published date through the current session date.
- Primary inactivity resets only on a newer Phintraco BUY or material Phintraco status/progress; lower-tier context does not reset it.
- Source-only inactivity resets on a new qualifying source event.
- Stale and superseded episodes use `Resolved`, remove the market-state tag, and keep last known close facts in the existing card layout.
- Stop-loss and final-target closure retain the terminal market-state tag and record their resolution reason.
- A newer distinct Primary BUY supersedes the open episode and starts a dated new thread; an older BUY is a labeled history reply that cannot change the plan or timer.
- A level-2/3 event published before resolution is a labeled history reply in that resolved episode; one published after resolution may start a new source-only episode.
- New episode titles use the first accepted event's published time in WIB as `TICKER - weekday, DD Mon YYYY`.
- A 48-hour quiet timer starts only after resolution edits/tags and all existing episode outbox work are complete. New history activity resets that timer.
- No VPS, production SQLite, Hermes schedule, deployment, replay, or Discord test-post changes in this task.

## Review Focus

- Exactly 20 IDX sessions after an update resolve, while 19 do not, including weekends and reviewed holidays.
- Lower-tier context on a Primary episode does not postpone stale resolution.
- Retryable resolution edits or prior replies prevent the quiet timer from starting.
- A later historical reply restarts the quiet timer without reopening the episode.
- An older BUY or pre-resolution source event is historical, while a post-resolution source event opens a new dated source-only episode.
- Repeated lifecycle runs do not duplicate archive operations or alter an already archived episode.

---

### Task 1: Owner lifecycle reconciliation

**Files:**

- Modify: `cron-dc-swing-board/bin/calendar.py`
- Modify: `cron-dc-swing-board/bin/models.py`
- Modify: `cron-dc-swing-board/bin/store.py`
- Modify: `cron-dc-swing-board/bin/engine.py`
- Modify: `cron-dc-swing-board/bin/render.py`
- Modify: `cron-dc-swing-board/bin/tags.py`
- Modify: `cron-dc-swing-board/bin/board.py`
- Create: `cron-dc-swing-board/bin/bursawatch-dc-swing-board-lifecycle.sh`
- Modify: `cron-dc-swing-board/tests/test_calendar.py`
- Modify: `cron-dc-swing-board/tests/test_store.py`
- Modify: `cron-dc-swing-board/tests/test_engine.py`
- Modify: `cron-dc-swing-board/tests/test_final_regressions.py`
- Modify: `cron-dc-swing-board/tests/test_board_cli.py`
- Modify: `cron-tg-kelas-investasi-gtw/tests/test_discord.py`
- Modify: `cron-dc-swing-board/AGENTS.md`
- Modify: `cron-dc-swing-board/CRON.md`
- Modify: `platform-bursawatch-release/release-manifest.json`
- Create: `docs/adr/0031-swing-board-inactivity-and-archive-lifecycle.md`
- Modify: `docs/README.md`

**Interfaces:**

- Add `BoardEngine.reconcile_lifecycle(now) -> dict[str, int]` for stale resolution, quiet-period readiness, and archive scheduling.
- Add the `reconcile-lifecycle` CLI command and its zero-argument scheduler wrapper.
- Persist `resolution_reason`, quiet-period start, and archive completion in the episode row with a backward-compatible SQLite migration.

- [x] Add tests first for trading-session counting, lifecycle persistence, delivery gating, 48-hour eligibility, history timer reset, and idempotent archive receipts.
- [x] Implement the schema migration, lifecycle state transitions, render changes, and outbox completion handling.
- [x] Route all lifecycle effects through `BoardEngine.drain()` and the existing shared delivery client.
- [x] Add the daily wrapper, release allowlist entry, and package/ADR documentation for the 17:10 WIB schedule.
- [x] Run focused Swing Board tests, `bash scripts/test-all`, and `git diff --check`.
- [x] Commit the completed worktree changes.

## Rulings

- `source-only` stale cards have no valid market checkpoint. Their generated lifecycle line will say `Last checked: no Phintraco close recorded` rather than fabricate a price state. Cost if wrong: a user may prefer a source timestamp over an explicit absence of price data.
- Daily reconciliation can archive up to 24 hours after the 48-hour threshold because it runs once per day; it never archives early. Cost if wrong: resolved threads may remain visible up to one additional day.
