# Shared Chart-IMG client

This package owns provider transport, decoded image validation, immutable render
identity/cache and Chart-IMG allowance coordination. Read `README.md` before
changing the public interfaces. Root instructions still apply.

- Importing or constructing clients must not read credentials, contact a provider
  or create a database. Configuration and store initialization are explicit.
- Credentials belong only to the ignored package `.env`. Never read that file
  during tests. Test configuration uses temporary files and invented keys.
  Layout IDs and immutable profile/layout revisions belong to callers.
- `ChartImgClient.render` defaults to cache-only. Network mode requires an
  explicit `cache_only=False`, an injected transport and separate authorization
  for any live provider validation or spend.
- Coordinate one account through one shared SQLite store. Reserve before HTTP,
  retain charges for every uncertain attempt, enforce 50 attempts per rolling
  24 hours and at least one second between reservations. This accounting is
  independent of Sectors. No automatic retries or lease takeover.
- Unknown transport outcomes require explicit evidence-backed audit resolution.
  Unknown throttling additionally requires a full 24-hour cooldown. Resolution
  never refunds an attempt and must not occur while the old writer can continue.
- Decoded bytes, requested dates, a matching close and mutable layout IDs do not
  prove chart profile, visible window or last-bar date. Keep external caller
  attestations bound to both the exact image digest and full request identity.
- Do not add scheduling, TradingView session acquisition/layout edits, morning
  rendering policy, Discord REST or provider storage operations here.
- Tests use callable fake HTTP and temporary SQLite. Run focused tests, then
  `python -m pytest -q` from this package using the repository interpreter.
  Shared CI/deployment registration is owned by the integration task.

See [the architecture note](../docs/notes/2026-10-05-shared-chart-img-client-architecture.md).
