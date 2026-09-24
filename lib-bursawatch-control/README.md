# Bursawatch control-plane client

This shared runtime library lets cron packages read a versioned control-plane
configuration snapshot without receiving database credentials. It is deployed
as `~/.agents/skills/lib-bursawatch-control/bin/`.

The client is intentionally standard-library-only so it can be added to the
existing watcher runtime without changing the shared Yahoo Finance tool
environment. Configuration request failure raises a sanitized control-plane
error. Callers must fail closed and must not silently fall back to static
configuration when live mode is enabled.

`ControlPlaneReporter` stores lifecycle and event requests in a bounded,
0600 local spool under `~/.hermes/state/bursawatch-control/spool/<watcher-id>`
and retries them idempotently. The spool is a transport buffer, not the log
system of record: the control-plane Postgres database stores structured run and
event records, while local wrapper stdout files remain short-lived diagnostic
copies during migration.

## Source-event handoff

`bin/source_event_client.py` provides `SourceEventClient` and `SourceEventHandoff`.
The adapter stages a bounded event in the private local spool before sending. The
handoff removes that record only after a validated durable acceptance receipt. The
adapter must persist its own cursor only after the receipt and must retry pending
handoff records on restart. If it crashes after acceptance and before cursor save,
provider rereads are safe because the server returns the original receipt. An HTTP
error, invalid receipt, or full spool must stop cursor advancement. Platform adapters
are introduced in later tasks; this library alone does not change any live cursor.

Claimed work includes a stable `effect_key`. Domain handlers must send that key to
their owner to deduplicate effects across retries, lease expiry, and audited replay.
