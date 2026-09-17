# Bursawatch Telegram Phintraco Swing cron contract

See `AGENTS.md` for the source policy, state transitions, and shared-resilience details.

- **Scheduler:** cutover renames active Hermes no-agent job `2b5c0a128652` to `bursawatch-tg-phintraco-swing`, retaining `* * * * *` (WIB) and raw output to `#hermes`.
- **Executable:** `bursawatch-tg-phintraco-swing.sh`, sourced from `bin/`, runs deterministic `scan.py` against its established private production state and media directory.
- **Boundary:** read only Phintraco Telegram source `1444713822`, parse only qualifying individual source calls, and post source-faithful alert text followed by the same-message source chart. After All delivery, submit a normalized source event through the board wrapper. Separate ordered board retries never block later All pairs. Every normal run requests one owner drain regardless of earlier degradation; pending, failed, malformed health, or nonzero exit degrades the heartbeat. This watcher never reads the board database, updates forum tags, posts forum content, calculates prices, uses an LLM, infers a chart, or writes to Telegram.
- **Shared session:** use only `POLYCOP_SESSION_STRING` through `lib-telegram-resilience` and `~/.hermes/state/telegram-resilience-polyclop.json`. A safe probe or hold must not advance the Telegram cursor or mutate the outbox.
- **Check:** set `IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST=1`, an isolated state path, and optional forced heartbeat for no-post verification. The scanner retains a cached source chart and its `pending_board` event until the owner acknowledges exactly `{"accepted": true}`; a board retry must never repeat an All text or chart. Do not replay state or manually trigger the scheduled job.
- **Deployment:** after a clean published commit and approved VPS write, deploy `bin/`, synchronize this contract and the wrapper separately, compare checksums, and verify through an isolated no-post run followed by the natural scheduler record.
