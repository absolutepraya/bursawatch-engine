# Bursawatch control-plane service instructions

This package owns the Bursawatch control-plane API, Postgres migrations,
configuration revisions, desired schedule revisions, audit records, run
summaries, structured events, profile avatar URL metadata, and the versioned
API contract consumed by the separate web repository.
It also owns durable normalized source-event acceptance and independent leased
pipeline work. These are separate from structured run events and their retry
state is held in Postgres.
The publication read model in `publication_model.py`, `publication_store.py`,
and migration `020_publications.sql` is a separate forward-only projection of
confirmed Discord output. An owner submits only after all required Delivery
Owner receipts are confirmed. The Control Plane keeps immutable versions,
cutover, and owner checkpoints; it does not send to Discord, replay source
events, or own the durable owner outboxes. Production recorded its forward-only
cutover boundary on 2026-09-30 at 14:15 WIB. The feed may be empty after that
boundary, and missing checkpoints cannot establish completeness.
Distinct `CONTROL_PLANE_PUBLICATION_OWNER_TOKENS` scope each owner to its own
submission and checkpoint. Human viewer/admin JWTs alone may read the feed.
Activation uses the host-local `bin/activate_publication_feed.py` after separate
approval. The complete required-operation manifest and exact output snapshot
must be persisted in owner state before the owner acknowledges confirmed
delivery; projection retry never reissues a Discord operation.
It also owns the Source Catalog registry, capability compatibility, and
versioned source configuration. Source catalog revisions are separate from
watcher configuration revisions. User endpoints remain pending until a
reviewed verification path exists; pending endpoints cannot produce effective
subscriptions. The supported securities table starts empty because no
reviewed finite engine universe has been established in source.
The canonical Phintraco Sekuritas endpoint `telegram:phintasprofits` is
compatible with `trading_plans` through migration
`021_phintas_swing_compatibility.sql`. The migration adds compatibility only;
effective source-catalog configuration must still enable the subscription.
The legacy `telegram:phintraprofits` identity remains registered for accepted
work and audit compatibility.
The system-owned BRI WhatsApp endpoint supports `company_news`, `macro_news`,
and `swing_chart_context`; the channel watcher's route scope still decides
which classified items can be delivered.

It does not own watcher cursors, image bytes, media, delivery outboxes,
domain retry state, Telegram resilience, Swing Board state, secrets, or scheduler
definitions. It stores only profile avatar URLs and refresh status, never
base64 image data.
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

The long-lived API shares one process-local Psycopg pool across the watcher,
source catalog, and source inbox Postgres stores. It opens during FastAPI
startup and closes during shutdown, with one idle connection and at most four
client connections. Each store method still commits or rolls back when its
borrowed connection context exits. Source-event acceptance reads the catalog
inside its existing advisory-locked transaction. The migration, baseline seed,
and avatar refresh CLI commands keep their separate short-lived connections.
Do not create a new database connection per API request or enable prepared
statements for a Supavisor transaction-pooler DSN.

The separate web origin must be supplied through the exact
`CONTROL_PLANE_ALLOWED_ORIGINS` allowlist. Never use a wildcard origin with
credentialed browser requests.

Run the focused suite with:

```bash
uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' \
  --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests
```

## Local admin access-token helper

`tools/get_admin_access_token.py` obtains a Supabase Auth user session through
the password grant and stores its short-lived `access_token` in the ignored
control-plane `.env`. By default it reads these local entries from that file:

```dotenv
SUPABASE_AUTH_EMAIL=
SUPABASE_AUTH_PASSWORD=
SUPABASE_PUBLISHABLE_KEY=
```

The helper is noninteractive by default and never prints credential values or
the returned access token. Keep `.env` private with mode `0600`; do not commit,
copy to the VPS, or put credentials in command arguments. Use `--prompt` to
request an interactive login instead. Do not pipe the helper through
`python3 -`, since that breaks interactive input:

```bash
cd ~/Documents/Projects/Hermes
python3 service-bursawatch-control/tools/get_admin_access_token.py
```

From a managed worktree, point `--env` at the main checkout's ignored env
file. The helper never prints the access token and rejects publishable,
anonymous, and `service_role` keys:

```bash
python3 service-bursawatch-control/tools/get_admin_access_token.py \
  --env ~/Documents/Projects/Hermes/service-bursawatch-control/.env
```

`SUPABASE_PUBLISHABLE_KEY` must be the publishable/anon key for the same
Supabase project as `CONTROL_PLANE_SUPABASE_URL`. Never use a `service_role`
key for Auth login. If the Supabase account is passwordless, use
`tools/supabase_recovery_server.py` first. It binds only to
`127.0.0.1:3000`, keeps the recovery token in the browser fragment, and
updates the password through Supabase's authenticated user endpoint. Request a
fresh recovery link after starting it, since a recovery URL must not be pasted
into chat or logs:

```bash
python3 service-bursawatch-control/tools/supabase_recovery_server.py \
  --env ~/Documents/Projects/Hermes/service-bursawatch-control/.env
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

If a source-owned baseline must advance after a schema-compatible watcher
change, use a reviewed `manual` migration guarded by the prior revision,
checksum, and `actor_id`. Such a correction may promote only the untouched
`source-baseline` row and must leave any dashboard-authored revision alone.
Human configuration writes still go through the authenticated API.

The optional watcher config-validator directories are trusted deployed source,
not web input. The service invokes each configured parser in a fresh process
with a minimal environment and no service credentials, so the X, Instagram,
WhatsApp, Market News, Swing Board, Phintraco, Kelas Investasi, and Stockbit modules
cannot collide by Python module name. VPS deployment uses the self-contained
`validator-sources/` bundle, not a live watcher runtime directory. Its parity
test requires exact byte-for-byte agreement with each cron source file.
For Stockbit, the reviewed dedicated API environment must set
`CONTROL_PLANE_STOCKBIT_CONFIG_VALIDATOR_DIR=/home/praya/.hermes/bursawatch-control-plane/validator-sources/bursawatch-stockbit-snips`.
Stockbit configuration PUTs remain unavailable until that setting is deployed
and the API service is restarted. Do not point it at the live cron directory.
