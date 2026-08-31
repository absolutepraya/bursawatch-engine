# IDX SSF Weekly Watch instructions

This file supplements the repository root `AGENTS.md`.

This is a deterministic no-agent Telegram-to-Discord forwarder. It accepts valid Phintraco Weekly SSF Review PDFs and forwards each underlying as source-only text followed immediately by the native analyst chart.

- Preserve strict FIFO delivery and the exact Telegram PDF source footer.
- Keep source PDFs and extracted charts as private runtime artifacts.
- Use the shared `POLYCOP_SESSION_STRING` resilience profile and control-plane state. Do not add another Telegram session or reset watcher state.
- Do not override the registered state path or replay an old report.
- Use the documented `*_NO_POST=1`, isolated state, and forced-heartbeat controls for verification.
- Deploy only after focused and complete tests, then compare runtime checksums and inspect the natural scheduler record.
