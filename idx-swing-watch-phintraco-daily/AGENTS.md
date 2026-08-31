# IDX Swing Daily Watch instructions

This file supplements the repository root `AGENTS.md`.

This is a deterministic no-agent Telegram-to-Discord forwarder for individual Phintraco BUY calls, TP/SL outcomes, and approved active-plan updates. It forwards source text followed by the chart attached to the exact Telegram message.

- Preserve strict FIFO delivery, the exact Telegram source footer, and chartless-event handling.
- The runtime performs no market analysis and must not invent trade details.
- Use the shared `POLYCOP_SESSION_STRING` resilience profile. Never add a watcher-specific session or reset the shared resilience state.
- Do not override the registered state path or manually trigger a live posting run as a smoke test.
- Use the documented no-post, isolated-state, and forced-heartbeat controls, then verify checksums and natural scheduler evidence after deployment.
