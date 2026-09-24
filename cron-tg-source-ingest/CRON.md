# Telegram source ingest pilot contract

- **Scheduler:** none. No production job or wrapper is registered.
- **Entry point:** `bin/runner.py`, for isolated synthetic integration only.
- **Catalog:** use one effective snapshot; accept only verified canonical pilot
  endpoints and compatible capabilities. Validate Tuntun's exact canonical
  publisher and identity, then leave it on its current reader.
- **Source state:** private endpoint-local cursor and `SourceEventHandoff` spool.
  Bootstrap at newest ID, use bounded ascending reads, and advance only after
  an authenticated inbox receipt. Never replay production history.
- **Media:** stop before acceptance or cursor advancement when a source message
  contains photo or document. Provider message URLs are not durable media refs.
- **Work:** only text-only Phintraco Swing and deterministic Stock Information
  handlers are registered. Agent News and Kelas work stay pending for a future
  reviewed classifier/media integration. Existing domain ledgers, the Board
  owner, and the Discord Delivery Owner retain authority.
- **Release:** metadata only. No runtime sync, schedule change, or production
  smoke run is authorized by this package.
