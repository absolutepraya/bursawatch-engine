# Telegram source ingest pilot contract

- **Scheduler:** none. No production job or wrapper is registered.
- **Entry point:** `bin/runner.py`, for isolated synthetic integration only.
- **Catalog:** use one effective snapshot; accept only verified canonical pilot
  endpoints and compatible capabilities. Validate Tuntun's exact canonical
  publisher and identity, then leave it on its current reader.
- **Source state:** private endpoint-local cursor and `SourceEventHandoff` spool.
  Bootstrap at newest ID, use bounded ascending reads, and advance only after
  an authenticated inbox receipt. Never replay production history.
- **Media:** upload bounded source attachments through
  `lib-bursawatch-source-media` to the private Source Media Owner before source
  event acceptance. Events store stable opaque refs, never provider/public/signed
  URLs or bytes. The local event spool retains refs across inbox retries; the
  endpoint cursor advances only after durable inbox receipt. Missing service or
  rejected media blocks only that endpoint.
- **Work:** Phintraco Swing and deterministic Stock Information use their existing
  owner ledgers; the Swing owner retrieves source JPEG refs through the shared
  client and preserves the existing text-then-chart flow. Agent News and Kelas
  work stay pending for a future reviewed classifier/domain handoff. Existing
  domain ledgers, the Board owner, and the Discord Delivery Owner retain authority.
- **Release:** metadata only. No runtime sync, schedule change, or production
  smoke run is authorized by this package.
