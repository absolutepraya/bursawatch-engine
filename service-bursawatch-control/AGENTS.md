# Bursawatch control-plane service instructions

This package owns the Bursawatch control-plane API, Postgres migrations,
configuration revisions, desired schedule revisions, audit records, run
summaries, structured events, and the versioned API contract consumed by the
separate web repository.

It does not own watcher cursors, deduplication, media, outboxes, retry state,
Telegram resilience, Swing Board state, secrets, or scheduler definitions.
Those remain under their existing package or VPS ownership boundaries.
It records a scheduler job's desired enabled state and interval, but never
edits the live Hermes registry itself. A separate trusted VPS reconciler must
report an applied revision before a desired schedule is effective.

## Development

Run the service locally with a development store only:

```bash
CONTROL_PLANE_STORE=memory uv run --with 'fastapi>=0.115,<1' --with 'uvicorn>=0.30,<1' \
  uvicorn control_plane.api:create_app_from_environment --factory --app-dir bin --reload
```

Production must use a configured Postgres connection and authenticated
principals. The in-memory store is for tests and local contract exploration;
it must never be used as a production fallback.

The separate web origin must be supplied through the exact
`CONTROL_PLANE_ALLOWED_ORIGINS` allowlist. Never use a wildcard origin with
credentialed browser requests.

Run the focused suite with:

```bash
uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests
```

Do not deploy this service, change a live Hermes scheduler entry, or point a
production watcher at it without an explicit reviewed deployment step.

## Security boundary

The web application never receives database credentials or a Supabase service
role key. Cron clients use a dedicated machine credential for read and event
write operations. Human configuration writes require an authenticated
application principal and an audit record.

Supabase Data API access to control-plane tables is deliberately disabled by
migration `004_supabase_data_api_hardening.sql`: it enables RLS and revokes
browser roles. The private backend `DATABASE_URL` is the only database path.

The optional watcher config-validator directories are trusted deployed source,
not web input. The service invokes each configured parser in a fresh process
with a minimal environment and no service credentials, so the X, Instagram,
WhatsApp, Phintraco, and Kelas Investasi modules cannot collide by Python
module name.
