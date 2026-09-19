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
- an isolated validator bridge for the migrated X, Instagram, WhatsApp, and
  Phintraco schemas, including bounded `additional_prompt_instruction` fields
  where the watcher has an LLM path.
- the initial Postgres schema migration;
- a versioned OpenAPI document for the web repository.
- opt-in live configuration support for X Account Watch, Instagram Account
  Watch, WhatsApp Channel Watch, and Telegram Phintraco Swing, with one frozen
  revision per invocation.

The Supabase Auth verifier is implemented and covered by local tests. A VPS
service unit, real environment values, and an authenticated web client remain
separate deployment work.
The watcher validator bridge is implemented, but requires its deployed-source
directory settings. A desired schedule revision also needs a separate trusted
VPS scheduler reconciler before it changes a live Hermes job.

## Runtime environment

[`env.example`](env.example) lists every backend setting without values. It is
a field-name template only: real local values belong in `~/.secrets`, while a
reviewed VPS deployment uses its scoped `~/.hermes/.env`. Do not add a backend
secret to GitHub Actions, this repository, or the separate web application.

When `CONTROL_PLANE_SUPABASE_URL` is set, browser requests must carry a
Supabase Auth access token. The service verifies only `RS256` or `ES256`
tokens against that project's public JWKS endpoint, requires the
`authenticated` audience and role, and maps only configured UUIDs in
`CONTROL_PLANE_ADMIN_USER_IDS` to admins. Other signed-in users are viewers.
`CONTROL_PLANE_ADMIN_TOKEN` is development-only and must be unset in Supabase
mode. Cron clients retain their distinct `CONTROL_PLANE_MACHINE_TOKEN`.

This verifier intentionally accepts only Supabase asymmetric signing keys. At
deployment, confirm the Supabase project has an active RSA or elliptic-curve
JWT signing key with a non-empty JWKS endpoint. Do not provide the backend a
shared JWT secret as a fallback.
The Postgres adapter is present, but a production deployment still requires a
reviewed `DATABASE_URL`, migration run, machine credential, and authenticated
human principal configuration.

Migration `004_supabase_data_api_hardening.sql` enables RLS and revokes Data
API privileges for `anon` and `authenticated` on every control-plane table.
The browser never queries these tables directly, even after Supabase Auth is
enabled; it calls this API with its user token instead.

Signed-in viewers can read the watcher catalog, desired schedule state, recent
runs, a single run's event timeline, and the newest events across a watcher.
They cannot read configuration snapshots or change configuration or schedules.
Cron machine credentials can read their active configuration and append run
records, but cannot use the dashboard read routes.

## Watcher config validation

The API rejects a configuration write unless the watcher parser accepts it.
Configure only paths to deployed, reviewed watcher `bin/` directories:

```text
CONTROL_PLANE_X_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-x-account-watch/bin
CONTROL_PLANE_IG_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-ig-account-watch/bin
CONTROL_PLANE_WA_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-wa-channel-watch/bin
CONTROL_PLANE_PHINTRACO_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-tg-phintraco-swing/bin
```

Each validator executes in a fresh, credential-free subprocess. This prevents
Python module collisions between watcher packages and means the same strict
schema used at cron startup guards web writes. Unconfigured watchers remain
read-only through the API until their typed validator is added.

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
