# IDX CA Watch instructions

This file supplements the repository root `AGENTS.md`.

IDX CA Watch is a deterministic IDX corporate-action scanner with an agent scoring boundary. The scanner owns source fetching, deduplication, disclosure extraction, hard red flags, state, charts, delivery, and heartbeat. The agent may score only the supplied evidence.

- Treat missing financial, transaction, counterparty, approval, or denominator data as missing evidence.
- Score corporate-action materiality and fundamental catalyst evidence only. Never use RSI, moving averages, ATR, volume, price momentum, liquidity, or chart patterns in the score or summary.
- Suppress routine results, ordinary dividends, vague notices, severe dilution, distress, UMA, suspension, PKPU, FCA/PPK, and other overriding adverse conditions according to `SKILL.md`.
- Verify network behavior on the VPS because IDX Cloudflare blocks reliable Mac verification.
- Use isolated no-post controls. Do not manually run the scheduled production scan as a smoke test because it can post alerts and perform chart work.
- Preserve live state and verify the heartbeat, alert path, deployment checksums, and natural scheduler record after approved deployment.
