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
it must never be used as a production fallback. The local Bursawatch-specific
environment is the ignored `service-bursawatch-control/.env` in the main
worktree. WT links it into eligible feature worktrees. It is never committed.
The reviewed VPS service uses its separate mode-`0600`
`~/.hermes/bursawatch-control-plane.env`, never Hermes's shared `.env`.

The separate web origin must be supplied through the exact
`CONTROL_PLANE_ALLOWED_ORIGINS` allowlist. Never use a wildcard origin with
credentialed browser requests.

Run the focused suite with:

```bash
uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' pytest -q tests
```

Apply migrations only in an explicitly approved deployment step:

```bash
DATABASE_URL=<private-dsn> ./venv/bin/python bin/migrate.py
DATABASE_URL=<private-dsn> ./venv/bin/python bin/seed_baseline_configs.py
```

Do not manually deploy this service, change a live Hermes scheduler entry, or
point a production watcher at it without an explicit reviewed deployment step.
The separately bootstrapped VPS release agent is the sole exception for
eligible verified `main` releases within its fixed manifest boundary.

Every new SQL migration must begin with exactly one of these first-line
headers:

```sql
-- bursawatch-release: automatic
-- bursawatch-release: manual
```

Use `automatic` only for forward-compatible changes that are safe to apply in
the release agent. Destructive changes, data rewrites, backfills, and schedule
changes are `manual`. The pre-existing immutable migrations remain headerless
because production has recorded their checksums. Their fixed eligibility is
checked through `migrations/legacy-release-eligibility.json`; never add a
header to them or change their SQL.

## VPS repeat releases

After the approved release-agent bootstrap exists, the VPS-local release
agent owns ordinary eligible control-plane releases from verified `main`.
`./deploy.sh` remains a manually approved recovery helper only. An agent
should run `./deploy.sh plan`, `status`, or `verify` before requesting that
recovery approval, and must not run `release --apply` concurrently with the
release agent.

The helper synchronizes only `baseline-configs/`, `bin/`, `migrations/`,
`validator-sources/`, and `requirements.txt`; it updates the dedicated virtual
environment, applies immutable migrations, seeds missing baseline revisions,
restarts `bursawatch-control-plane.service`, and checks health. It never copies
a local `.env`, changes `~/.hermes/bursawatch-control-plane.env`, edits the
systemd unit, Nginx, DNS, TLS, the Hermes cron registry, or the schedule
reconciler. Those are separate, explicitly approved deployment changes.

## Security boundary

The web application never receives database credentials or a Supabase service
role key. Cron clients use a dedicated machine credential for read and event
write operations. Human configuration writes require an authenticated
application principal and an audit record.

Supabase Data API access to control-plane tables is deliberately disabled by
migration `004_supabase_data_api_hardening.sql`: it enables RLS and revokes
browser roles. The private backend `DATABASE_URL` is the only database path.
`bin/migrate.py` records each immutable migration checksum in the private
database before serving traffic and refuses a changed applied migration.
`bin/seed_baseline_configs.py` seeds only an absent watcher config revision
from `baseline-configs/`; it refuses inconsistent history and never replaces
an active dashboard revision.

The optional watcher config-validator directories are trusted deployed source,
not web input. The service invokes each configured parser in a fresh process
with a minimal environment and no service credentials, so the X, Instagram,
WhatsApp, Market News, Swing Board, Phintraco, and Kelas Investasi modules
cannot collide by Python module name. VPS deployment uses the self-contained
`validator-sources/` bundle, not a live watcher runtime directory. Its parity
test requires exact byte-for-byte agreement with each cron source file.
