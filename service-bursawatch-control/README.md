# Bursawatch Control Plane

This service is the backend boundary between Bursawatch crons, the managed
Postgres control-plane database, and the separate Bursawatch web application.

## Current slice

This branch adds:

- a strict versioned configuration snapshot contract;
- an in-memory store for isolated API tests;
- authenticated API routes for config reads, config writes, run records, and
  structured events;
- immutable desired interval schedules for supported scheduler jobs, with an
  explicit reconciliation status so a dashboard never mistakes stored intent
  for a changed live Hermes job;
- the initial Postgres schema migration;
- a versioned OpenAPI document for the web repository.
- opt-in live configuration support for X Account Watch, Instagram Account
  Watch, and WhatsApp Channel Watch, with one frozen revision per invocation.

The Supabase Auth verifier, watcher-specific validator registry, and VPS
service unit are separate deployment work. A desired schedule revision also
needs a separate trusted VPS scheduler reconciler before it changes a live
Hermes job.
The Postgres adapter is present, but a production deployment still requires a
reviewed `DATABASE_URL`, migration run, machine credential, and authenticated
human principal configuration.

## Local development

```bash
CONTROL_PLANE_STORE=memory uv run --with 'fastapi>=0.115,<1' --with 'uvicorn>=0.30,<1' \
  uvicorn control_plane.api:create_app_from_environment --factory --app-dir bin
```

The default application uses an in-memory store only when
`CONTROL_PLANE_STORE=memory` is explicitly set. Do not use that mode for a
production deployment.

For the separate web application, set
`CONTROL_PLANE_ALLOWED_ORIGINS` to a comma-separated exact origin allowlist.
Do not use `*`, because authenticated browser requests use credentials.

## API boundary

The stable integration document is
[`openapi/control-plane.v1.yaml`](openapi/control-plane.v1.yaml). The web
repository should call the API rather than write Supabase tables directly.

Every config response carries a watcher ID, monotonically increasing revision,
config version, canonical SHA-256 checksum, update timestamp, and the typed
watcher payload. A cron freezes the returned revision for one invocation. A
migrated watcher enables this mode with a prefix-specific
`<PREFIX>_CONTROL_PLANE_URL`, `<PREFIX>_CONTROL_PLANE_WATCHER_ID`, and
`<PREFIX>_CONTROL_PLANE_TOKEN`; without the URL, its reviewed static JSON
fallback remains active during migration.

## Schedule boundary

`GET /v1/watchers/{watcher_id}/jobs` lists the scheduler jobs that the web app
may display. Interval jobs expose their approved minimum and maximum cadence;
fixed calendar jobs are intentionally read-only. An admin can write a desired
interval schedule through `PUT /v1/jobs/{job_id}/schedule`.

The response has `reconciliation.status` and `reconciliation.effective`. A new
write is `pending` and `effective: false`: it is durable operator intent, not
an instruction that this service has applied to Hermes. The later VPS
reconciler is the only component allowed to change or pause a live job, using
the supported Hermes CLI and reporting the applied revision back.
