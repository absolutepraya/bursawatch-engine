# IDX SSF Watch, Phintraco Weekly cron contract

See `AGENTS.md` for the parser, state, source-format, and shared-resilience details.

- **Scheduler:** active Hermes no-agent job `6889d2d13ac2`, `idx-ssf-watch-phintraco-weekly`, `*/30 * * * *` (WIB), raw output to `#hermes`.
- **Executable:** `idx-ssf-watch-phintraco-weekly.sh`, sourced from `bin/`; it runs the deterministic `scan.py` with production state at `~/.hermes/state/idx-ssf-watch-phintraco-weekly.json`.
- **Boundary:** read only Phintraco Telegram source `1444713822`, accept structurally valid four-page Weekly SSF Review PDFs, and deliver each source-faithful text and native chart pair in strict FIFO order. No LLM, generated chart, market analysis, or Telegram write is allowed.
- **Shared session:** use only `POLYCOP_SESSION_STRING` through `telegram-resilience` and `~/.hermes/state/telegram-resilience-polyclop.json`. A safe probe or hold must not advance the Telegram cursor, report jobs, or outbox.
- **Check:** set `IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST=1`, an isolated state path, and optional forced heartbeat for no-post verification. Never replay production state or manually trigger the scheduled job.
- **Deployment:** after a clean published commit and approved VPS write, deploy `bin/`, synchronize this contract and the wrapper separately, compare checksums, and verify through an isolated no-post run followed by the natural scheduler record.
