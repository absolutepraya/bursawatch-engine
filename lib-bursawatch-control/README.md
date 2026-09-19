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
