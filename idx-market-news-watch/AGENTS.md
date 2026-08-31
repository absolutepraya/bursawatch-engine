# IDX Market News Watch instructions

This file supplements the repository root `AGENTS.md`.

The deterministic watcher limits provider intake, cursoring, candidate creation, deduplication, resilience, and delivery. Hermes receives exactly one candidate when `wakeAgent` is true and must classify only the supplied source evidence.

- Do not browse, fetch, expand scope, or process historical material from the agent boundary.
- Preserve the provider lanes, issuer-specific filters, event-class allowlist, Indonesian summary contract, and no-advice language in `SKILL.md`.
- Use the shared `POLYCOP_SESSION_STRING` resilience control plane. Never add watcher-specific Telegram sessions or reset the shared resilience state.
- Use the supported wrapper and submission command, not a direct scanner invocation that bypasses resilience or runtime imports.
- A fresh cursor creates no historical candidates. Do not reset, replay, or manually post a candidate.
- Test deterministic intake and agent submission separately, then deploy and verify with isolated no-post state and VPS checksums.
