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
- an isolated validator bridge for the migrated X, Instagram, WhatsApp,
  Market News, Swing Board, Phintraco, and Kelas Investasi schemas, including bounded
  `additional_prompt_instruction` fields where the watcher has an LLM path.
- immutable Postgres schema migrations with a checksum ledger and advisory
  lock, so a changed applied migration is refused;
- a versioned OpenAPI document for the web repository.
- opt-in live configuration support for X Account Watch, Instagram Account
  Watch, WhatsApp Channel Watch, Telegram Market News, Discord Swing Board,
  Telegram Phintraco Swing, and Telegram Kelas Investasi GTW, with one frozen
  revision per invocation.

The Supabase Auth verifier and the reconciler-only control API are implemented
and covered by local tests. A VPS reconciler service unit, real environment
values, and an authenticated web client remain separate deployment work.
The watcher validator bridge is implemented, but requires its deployed-source
directory settings. A desired schedule revision also needs a separate trusted
VPS scheduler reconciler before it changes a live Hermes job.

## Runtime environment

[`env.example`](env.example) lists every backend setting without values. It is
a field-name template only. Real local values belong in the ignored
`service-bursawatch-control/.env` in the main worktree, which WT links into
eligible feature worktrees. A reviewed VPS deployment uses its scoped
`~/.hermes/.env`. Do not add a backend secret to GitHub Actions, this
repository, or the separate web application.

When `CONTROL_PLANE_SUPABASE_URL` is set, browser requests must carry a
Supabase Auth access token. The service verifies only `RS256` or `ES256`
tokens against that project's public JWKS endpoint, requires the
`authenticated` audience and role, and maps only configured UUIDs in
`CONTROL_PLANE_ADMIN_USER_IDS` to admins. Other signed-in users are viewers.
`CONTROL_PLANE_ADMIN_TOKEN` is development-only and must be unset in Supabase
mode. Cron clients retain their distinct `CONTROL_PLANE_MACHINE_TOKEN`. The
VPS scheduler bridge has its own `CONTROL_PLANE_RECONCILER_TOKEN`: it can read
desired interval schedules and report outcomes, but cannot read cron
configuration or access dashboard routes.

This verifier intentionally accepts only Supabase asymmetric signing keys. At
deployment, confirm the Supabase project has an active RSA or elliptic-curve
JWT signing key with a non-empty JWKS endpoint. Do not provide the backend a
shared JWT secret as a fallback.
The Postgres adapter is present, but a production deployment still requires a
reviewed `DATABASE_URL`, migration run, machine credential, and authenticated
human principal configuration. `bin/migrate.py` uses an advisory lock and a
private `bursawatch_schema_migrations` ledger. It applies each SQL file exactly
once and refuses an applied file whose checksum changed.

After migrations and before a watcher enables live mode, the explicitly
approved deployment runs `bin/seed_baseline_configs.py`. Its seven reviewed
JSON snapshots are exact copies of the current source defaults and tracked
watch JSON. The seeder creates revision 1 only for a watcher with no config
history. It never replaces an active dashboard revision and refuses partial
history, so it is safe to rerun during recovery.

The VPS API validates dashboard configuration with the self-contained
`validator-sources/` bundle. It contains the exact parser source required by
each watcher, including the small model dependencies for X, Instagram, and
WhatsApp. Parity tests require it to match the canonical cron source byte for
byte. This avoids importing from or changing a live cron runtime just to serve
the web application.

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
CONTROL_PLANE_MARKET_NEWS_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-tg-market-news/bin
CONTROL_PLANE_SWING_BOARD_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-dc-swing-board/bin
CONTROL_PLANE_PHINTRACO_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-tg-phintraco-swing/bin
CONTROL_PLANE_KELAS_INVESTASI_GTW_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-tg-kelas-investasi-gtw/bin
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
interval schedule through `PUT /v1/jobs/{job_id}/schedule`. The interval
timezone remains the Bursawatch host timezone, `Asia/Jakarta`, because Hermes
has no per-job timezone setting for an interval schedule.

The response has `reconciliation.status`, `reconciliation.last_error`, and
`reconciliation.effective`. A new write is `pending` and `effective: false`:
it is durable operator intent, not an instruction that this service has applied
to Hermes. The later VPS reconciler is the only component allowed to change or
pause a live job, using the supported Hermes CLI and reporting the applied
revision back. Its private endpoints reject browser, admin, and ordinary cron
credentials. If an admin writes a new revision while the reconciler is
working, its report for the old revision is rejected rather than falsely
marking the new intent effective.

The initial catalog seeds the verified current intent for every supported
interval job: X source poller (10 minutes), Instagram source poller (one hour),
Telegram Phintraco Swing (one minute), Telegram Market News (one minute),
Telegram Kelas Investasi GTW (one hour), and WhatsApp Channel Watch (paused at
one minute). The permitted intervals are 10 minutes to 24 hours for X, one hour
to 24 hours for Instagram, one minute to one hour for Phintraco and Market
News, and five minutes to six hours for Kelas Investasi. WhatsApp is one minute
to six hours. The two Swing Board calendar jobs and the X queue worker remain
fixed and read-only.
