# Bursawatch Control Plane

## Source Catalog phase 1

`GET /v1/source-catalog` returns the engine-owned securities allowlist,
curated publishers, canonical platform endpoints, capabilities, compatibility,
and the current independent catalog revision. Its `can_edit` flag comes from the authenticated principal and is true only for an admin. `GET /v1/source-catalog/effective`
resolves publisher defaults and endpoint overrides into a machine-readable
subscription snapshot. Each subscription includes its canonical address,
provider ID when known, and only a managed credential reference when one is
configured. WhatsApp provider IDs are channel JIDs; invitation URLs remain
addresses. A signed-in admin uses `PUT /v1/source-catalog/config`
with `expected_revision` and the complete config to save a new audited revision.
Stale writes return 409. Viewers can read the registry, and machine credentials
can read the effective snapshot. Asset metadata is an HTTPS reference only;
secrets are managed credential references. New People & Org endpoints stay
pending and cannot activate a pipeline until a reviewed identity verification
path is added.

For verified X endpoints, `company_news`, `macro_news`, and
`swing_chart_context` are compatible members of the exclusive `x_post_route`
dispatch group. Compatibility says a capability may be selected; it does not
enable it. Effective `enabled` state is still resolved from publisher defaults
and endpoint overrides, and `swing_chart_context` is disabled by default.
Catalog compatibility and effective enablement are returned separately with
the catalog revision.

Migration `013_source_catalog.sql` adds a private engine registry and independent
catalog revision/audit tables. It seeds canonical IDs from checked-in watcher
configs and the fixed Stockbit `FEEDS` definition without copying, converting,
or replacing any live watcher config.
There is currently no reviewed finite engine-owned IDX securities list, so
the supported-securities table and initial selection are empty. Add securities
only through a reviewed engine migration after establishing that allowlist.
Current curated web images remain usable without a new upload flow.

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
  Market News, Swing Board, Phintraco, Kelas Investasi, and Stockbit schemas, including bounded
  `additional_prompt_instruction` fields where the watcher has an LLM path.
- immutable Postgres schema migrations with a checksum ledger and advisory
  lock, so a changed applied migration is refused;
- a versioned OpenAPI document for the web repository.
- separate profile metadata records with automatic RSSHub avatar URL discovery,
  optional administrator overrides, and stale-avatar refresh tooling. Avatar
  URLs are stored as metadata only, never as base64 in watcher configuration.
- opt-in live configuration support for X Account Watch, Instagram Account
  Watch, WhatsApp Channel Watch, Telegram Market News, Discord Swing Board,
  Telegram Phintraco Swing, and Telegram Kelas Investasi GTW, with one frozen
  revision per invocation. Stockbit Snips requires live configuration for each
  invocation and has no static fallback.

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
`~/.hermes/bursawatch-control-plane.env`. Do not add a backend secret to
GitHub Actions, this repository, Hermes's shared `.env`, or the separate web
application.

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

The persistent API uses a shared, process-local Psycopg pool for its three
Postgres stores. Its size is one idle connection and at most four concurrent
connections; the pool starts with the API and closes on shutdown. Borrowed
connections retain each store method's transaction boundary. Source-event
acceptance reads its catalog under the same transaction and advisory lock.
Prepared statements are disabled so the same code works with a Supavisor
transaction-pooler connection string. The migration, seed, and avatar refresh
commands remain short-lived CLI database clients.

This removes the Control Plane's known per-request connection churn. It does
not establish that this service caused every Supavisor log in a billing window;
verify the change against redacted Supavisor authentication and termination
counts, service access logs, and successful watcher runs after the reviewed
production release. Previously ingested logs are not database rows to delete.

After migrations and before a watcher enables live mode, the explicitly
approved deployment runs `bin/seed_baseline_configs.py`. Its eight reviewed
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
Configure only paths to deployed, reviewed validator sources. The legacy
watcher paths below require separate migration to the isolated bundle:

```text
CONTROL_PLANE_X_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-x-account-watch/bin
CONTROL_PLANE_IG_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-ig-account-watch/bin
CONTROL_PLANE_WA_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-wa-channel-watch/bin
CONTROL_PLANE_MARKET_NEWS_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-tg-market-news/bin
CONTROL_PLANE_SWING_BOARD_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-dc-swing-board/bin
CONTROL_PLANE_PHINTRACO_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-tg-phintraco-swing/bin
CONTROL_PLANE_KELAS_INVESTASI_GTW_CONFIG_VALIDATOR_DIR=/home/praya/.agents/skills/bursawatch-tg-kelas-investasi-gtw/bin
CONTROL_PLANE_STOCKBIT_CONFIG_VALIDATOR_DIR=/home/praya/.hermes/bursawatch-control-plane/validator-sources/bursawatch-stockbit-snips
```

Each validator executes in a fresh, credential-free subprocess. This prevents
Python module collisions between watcher packages and means the same strict
schema used at cron startup guards web writes. Unconfigured watchers remain
read-only through the API until their typed validator is added. Stockbit config
PUTs remain unavailable until the reviewed Stockbit validator bundle path is
configured in the dedicated API environment and the service is restarted.

## Profile avatar metadata

`GET /v1/watchers/{watcher_id}/profiles` exposes the current profile identity
and its separate avatar metadata to signed-in dashboard users. An administrator
can choose `auto` or `manual` mode through the profile avatar route. Automatic
mode first checks the VPS-local RSSHub JSON feed's profile `icon`, then author
avatar fields, and finally safe profile-page metadata. It stores only the
provider URL and source label. The previous URL remains in place when a refresh
fails.

When a validated configuration adds a profile, the API hydrates its metadata
row and queues a best-effort first refresh after returning the configuration
response. `bin/refresh_profile_avatars.py` refreshes automatic records that
have never succeeded or are older than the configured interval. The reviewed
default is one day:

```bash
DATABASE_URL=<private-dsn> \
  ./venv/bin/python bin/refresh_profile_avatars.py
```

`CONTROL_PLANE_RSSHUB_BASE_URL` defaults to `http://127.0.0.1:1200` and
`CONTROL_PLANE_AVATAR_REFRESH_STALE_SECONDS` defaults to `86400`. A live timer
or Hermes schedule for the refresh command remains a separate operations
change. Manual URLs are HTTPS-only and do not allow credentials, fragments, or
custom ports.

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
interval job: X source poller (10 minutes), Instagram source poller (paused at
one hour), Telegram Phintraco Swing (one minute), Telegram Market News (one
minute), Telegram Kelas Investasi GTW (one hour), and WhatsApp Channel Watch
(paused at one minute). The permitted intervals are 10 minutes to 24 hours for
X, one hour to 24 hours for Instagram, one minute to one hour for Phintraco and
Market News, and five minutes to six hours for Kelas Investasi. WhatsApp is one minute
to six hours. The two Swing Board calendar jobs and the X queue worker remain
fixed and read-only.

`GET /v1/jobs` returns the global job inventory once per shared job. Supplying
`component_id` filters it to jobs linked to that declared component, so a
workflow detail can load its own shared jobs without reading unrelated job
records. `GET /v1/observations` similarly accepts repeated `job_id` filters;
the unfiltered form is reserved for the global Jobs view. Unknown, duplicate,
or excessive filter values are rejected rather than returned as empty data.

## Published feed projection contract

The separate publication read model accepts only confirmed, post-cutover
Discord output. Its migration `020_publications.sql` is additive and leaves the
feed unstarted until the host records one explicit boundary with
`bin/activate_publication_feed.py --boundary <aware-ISO-time>`. Activation is a
separate reviewed production step, not part of migration or service startup.
It fixes the eight owner identities declared in `publication_model.py` and
refuses a second activation. It neither replays old events nor sends a message.

Each owner receives a distinct private credential in the
`CONTROL_PLANE_PUBLICATION_OWNER_TOKENS` JSON mapping. The service derives the
owner ID from that credential for `POST /v1/publications` and
`POST /v1/publications/checkpoints`; browser JWTs and the shared machine token
cannot submit. Viewer and admin JWTs may read the paginated list, immutable
detail, and per-owner coverage. The web proxy must allow only those GET paths.

An owner must persist its complete required-operation manifest and exact
rendered snapshot in its own durable state before acknowledging confirmed
delivery. Every required leg needs a confirmed Discord Delivery Owner receipt,
including its stable operation key, digest, operation ID, destination, and
message ID. The Control Plane validates the owner's submitted manifest and
safe output but cannot infer an omitted leg from another owner's state. On an
API outage, the owner retries that stored projection only. It must not repeat
the Discord send to repair the feed. A checkpoint attests to the owner's
comparison time, confirmed and accepted boundaries, and outstanding count.
Missing or stale checkpoints are unknown. A complete feed claim requires every
cutover owner to report a current successful comparison. A fresh checkpoint
does not override a last-known disabled owner job, which remains paused or
unverified.

This contract has synthetic tests but has not been activated or verified with
natural production deliveries. A database-backed checkpoint and list path
also requires a reviewed live verification after deployment.

## Source inbox (development contract, not yet live)

`POST /v1/source-events` accepts a bounded version 1 envelope. Its provider identity
is `(platform, endpoint_id, provider_event_id)`; repeating the same original returns
its durable receipt and a conflicting original returns 409. Acceptance validates
publisher and endpoint identity against the Source Catalog, then writes the source
version and work in one Postgres transaction. An X publication with one or more
enabled members of `x_post_route` creates exactly one route-group work item.
It freezes the complete enabled capability set, per-capability source metadata,
and catalog revision. Non-X subscriptions and existing legacy X `company_news`
or `macro_news` work remain independently claimable during migration. A later
disable prevents new work but leaves accepted items pending. Corrections and
tombstones append audited versions targeted at the original frozen subscription
set, even if those subscriptions were later disabled. Retries use the stored
dispatch context and stable effect key rather than reevaluating current settings.
Tombstones are terminal. No legacy cursor or watcher state is moved by this
migration.

The route group is consumed by the existing X watcher, which runs its
X-specific classifier once and retains existing route precedence and output.
Accepted thread images are Vision context and ordered delivery inputs. X Swing
events deliver All text and media in the same queue invocation before one
source-only handoff to the existing Board owner; transient legs retain their
stable effect identity for retry, while confirmed missing media is a terminal
skip for that item. The X route's `omit_last` profile setting does not remove
accepted Swing images from All or Board delivery; non-Swing routes retain the
profile policy. Source catalog support does not itself schedule or cut over the
X adapter.

Worker machine clients may claim work, settle a current lease, and inspect events or work.
Claims require a nonempty list of supported pipeline IDs and use
`FOR UPDATE SKIP LOCKED`, a 120-second lease, and at most five attempts.
Kelas Telegram `swing_support` work is ordered by numeric source message ID.
A later Kelas message cannot be claimed while an earlier current-version item
is pending, leased, executing, or dead-lettered. This preserves bundle and
cursor order through retry; an audited admin suppression or replay is required
to clear a blocked predecessor.
Failed attempts back off up to one hour and store only a sanitized error code. Human
admins may explicitly suppress idle work or replay suppressed and dead-letter items
with a bounded reason; both actions are audited. The stable `effect_key` must be used
as the idempotency key at each domain owner. A lease expiry can run a handler again,
so the domain owner must deduplicate the effect before claiming exactly-once output.
An endpoint-scoped source credential (configured privately with
`CONTROL_PLANE_SOURCE_ENDPOINT_TOKENS` as an endpoint-ID to token JSON map) may
accept and revise only its own endpoint. The shared worker machine credential
cannot revise events. Corrections and tombstones require a stable `revision_id`;
retrying the same revision returns its receipt even when `observed_at` changes.
Reusing that ID for changed content is a conflict. Correction and tombstone
acceptance returns 409 without appending a version while any older work remains
`leased` or `executing`, including an expired lease. The source adapter must keep its durable
handoff and retry after the old work settles. Claim and revision transactions
lock the same event row; begin-execution locks it too. A worker must call
`POST /v1/source-work/{work_key}/begin` with its lease token immediately before
invoking a handler. A failed begin forbids handler invocation. `executing` work
is never automatically reclaimed, even after the original lease deadline.
If its worker crashes, an admin must first verify the process has stopped,
then call the audited `/recover` endpoint with `worker_stopped: true` and a
bounded reason. Recovery moves work to dead-letter for explicit inspection
or replay; it does not silently retry an uncertain effect.
Once committed, the new version supersedes prior pending, dead-letter, and
suppressed work; claim queries also fence by the latest version. The `/fence`
endpoint offers a read-only check, while `/begin` is the required atomic gate.
A handler already running may finish its domain effect before its execution settles
and before the revision is accepted; the adapter waits for that settlement. Domain owners must still
deduplicate `(event_key, version, effect_key)` across retry and crash recovery.
Run summaries remain in `ControlPlaneReporter` and do not contain source payloads.

Media bytes never enter Postgres. Source-event media references must be opaque stable
identities minted by the private Source Media Owner, with bounded digest, kind, MIME,
size, and filename metadata. The inbox validates those fields and the per-object and
per-event byte limits, but does not resolve refs or access Storage. The media service
owns Storage credentials and provides authenticated upload and download operations.
This code path uses fake providers in tests; it does not authorize a bucket, Supabase
change, or production replay. Operator inspection can contain source payload and should
be restricted to the authenticated API, never copied into routine logs or heartbeats.
The in-memory inbox is for local contract testing only.

## X Swing migration and release evidence

The route-group and capability changes are compatibility contracts, not a live
source cutover. Before any separately approved cutover, collect a read-only,
sanitized preflight: Control Plane catalog and watcher-config revisions;
configured endpoint IDs matched to reviewed publisher bindings; effective X
routes; X cursor, pending work, thread/media and All-outbox counts and hashes;
Board routes, open episodes and receipt summaries; pending Delivery Owner
effects; package revisions and health; and confirmation of owner-driven
20-trading-session inactivity resolution plus 48-hour quiet archival.
Never include credentials, source text, attachment bytes, or private media
paths. Ambiguous identity, route, pending effect, or absent Board lifecycle
scheduling is a cutover blocker.

The release sequence is: release the reviewed Control Plane schema/API,
verify migration state and health, release the approved X packages through the
exact-current-`main` release process, and verify installed package parity.
Check `web-config` separately using `DEPLOYMENT.md`'s build, alias/domain,
and live HTTP evidence; Vercel deployment is not proven by the backend release.
Until a separate cutover approval, keep the X adapter unscheduled and the
current X reader authoritative. Enabling capabilities, pausing the old writer,
transferring cursors or state, replaying work, changing Hermes schedules,
deploying, or posting production messages are separate approved actions.
