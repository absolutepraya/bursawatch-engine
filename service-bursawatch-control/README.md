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

Migration `021_phintas_swing_compatibility.sql` adds `trading_plans`
compatibility for the canonical Phintraco endpoint `telegram:phintasprofits`.
Compatibility alone leaves the effective subscription disabled. Enabling it
and disabling the legacy `telegram:phintraprofits` alias requires the reviewed
forward-only source-catalog transition; the compatibility migration does not
change the active subscription or any watcher configuration.

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

The Supabase Auth verifier and reconciler-only control API are implemented
and covered by local tests. The VPS schedule-reconciler systemd timer was
enabled and active in a production read at 2026-10-01 00:35 WIB. It applies
desired interval revisions through the supported Hermes CLI. For an approved
temporary pause, the authenticated admin schedule route must store
`enabled=false` while preserving the interval and timezone; verify the
reconciler's `applied_revision` and paused Hermes state. A direct Hermes pause
while desired state remains enabled can be undone by the next timer pass.
Restore the original enabled desired schedule through the same admin route and
verify natural reconciliation. The authenticated web application remains a
separate Vercel deployment unit. The watcher validator bridge is implemented,
but still requires its deployed-source directory settings.

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
PUTs are no longer blocked by a missing validator bundle. The reviewed
Stockbit bundle path is configured in the dedicated production API environment
and is present on the VPS. The API restarted with release
`b1297c269bd42fb7d56624c362e0e0e1fe059144` on 2026-09-30. Do not point the
validator at the live cron directory.

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
Discord output. Its migration `020_publications.sql` is additive. Production
activation recorded the one-time forward-only boundary as 30 September 2026,
14:15 WIB with `bin/activate_publication_feed.py`; activation is separate from
migration and service startup. It fixes the eight owner identities declared in
`publication_model.py` and refuses a second activation. It neither replays old
events nor sends a message.

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

The deployed Control Plane API release SHA was
`b1297c269bd42fb7d56624c362e0e0e1fe059144`, then-current `main` on
2026-09-30, and the Published page is live in the web workspace. At the
2026-09-30 production workspace check, the feed
showed no confirmed publications after its boundary and marked publisher
coverage incomplete or unverified. This does not prove that no delivery
occurred. Natural delivery coverage remains unverified until owners submit
receipt-backed publication records and current checkpoints.

## Source Inbox API and adapter contract

The version 1 Source Inbox API is part of the production Control Plane. The
2026-09-30 production snapshot showed the standalone Telegram intake schedule
active and the X, WhatsApp, and Stockbit adapter wrappers active through their
existing watcher schedules. This verifies the scheduler entrypoints and
Control Plane release SHA, not installed runtime checksums or a natural
source-to-delivery outcome. Accepted events and pipeline work are intake
evidence only; a Published record still requires the domain owner to report
confirmed Delivery Owner receipts and current coverage checkpoints.

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
Synthetic tests use fake providers and do not validate live object storage,
authorize a bucket or Supabase change, or authorize production replay. Operator
inspection can contain source payload and should be restricted to the
authenticated API, never copied into routine logs or heartbeats. The in-memory
inbox is for local contract testing only.

## X Swing capability and state-transition boundary

The X source adapter is active through the existing
`bursawatch-x-account-watch` schedule, and the separate X queue worker remains
active. The 2026-09-30 production snapshot confirmed those scheduler entries;
it did not verify installed runtime checksums or prove a natural delivery.
Do not add a second X polling job or resume the legacy source-polling wrapper.

The route-group and capability contracts do not themselves enable a
subscription. Do not infer that `swing_chart_context` or another capability is
enabled from adapter compatibility. Future changes to effective capabilities,
routes, state roots, Hermes schedules, or production delivery behavior still
require their applicable reviewed and approved transition. Never transfer
cursors or state, replay work, or post production messages as an implicit part
of such a change. The original cutover preflight remains historical guidance;
for a new state transition, collect its sanitized, read-only evidence before
changing the live reader or its state.

## Immutable source evidence reads

This additive API supports research from accepted Source Inbox versions. It does
not claim work or use the Published Feed as the source corpus. The dedicated
`CONTROL_PLANE_SOURCE_READER_TOKEN` (at least 32 characters, no whitespace,
distinct from every other static credential) maps to `source_reader` in both
static and Supabase/composite modes. That principal can access only these two
routes. Admins may also inspect them; general machine, viewer, source adapter,
publication owner, observer and reconciler principals are denied.

`POST /v1/source-evidence/capture` accepts exactly `previous_cutoff`, `cutoff`
(timezone-aware ISO timestamps) and optional `limit` (default 1000, range 1 to
1000). Under one repeatable-read, read-only transaction borrowed from the existing
shared pool, it selects each event's highest version accepted and observed at or
before cutoff, suppresses selected tombstones, then applies the publication
window `(previous_cutoff, cutoff]`. Corrections published outside the window do
not resurrect earlier versions. Order is publication time, event key, version.
The memory test store mirrors acceptance timestamps per version under its lock.

The response includes `api_version=1`, normalized window timestamps,
`captured_at`, `capture_status` (`early`, `on_time`, `late`), signed
`capture_gap_seconds` (capture minus cutoff), `candidate_limit`, `overflow`,
`history_available_from`, `history_status`, `complete`, `items`, and
`manifest_hash`. Any capture later than cutoff is explicitly late, including a
subsecond gap. It cannot reproduce the earlier committed-state snapshot because
an acceptance timestamp may precede commit. An early capture is also incomplete.
`overflow=true` means more candidates existed than the bound; there is no moving
query continuation. The morning owner must persist this exact manifest in its
private run state before reading or selecting evidence. Recovery must reuse its
references rather than recapture and claim to recover the original snapshot.

Each manifest item includes `event_key`, `version`, `kind`, `accepted_at`,
`published_at`, `observed_at`, `endpoint_id`, `publisher_id`, `platform`,
`source_url`, `parser_version`, `content_hash`, `payload_hash`,
`original_publisher_id`, `origin_status`, `text_truncated`,
`content_unavailable`, `evidence_hash`, and opaque `version_ref`. Current strict
source envelopes carry collecting publisher identity but no verified original
publisher field, so `original_publisher_id=null` and `origin_status=unknown`.
Consumers must preserve this uncertainty. Selection, copied-story deduplication,
and the 30-item/three-per-publisher cross-route cap belong to the morning owner.

`POST /v1/source-evidence/versions` accepts exactly `version_refs`, containing
1 to 100 unique opaque references from the persisted manifest. The response is
`{"api_version":1,"items":[...]}` in requested order. Each item adds only `text`
and `media_refs` to the manifest fields. References bind event identity, version
and a canonical SHA-256 of the exact accepted envelope, independent of the
adapter's `content_hash`. The full safe evidence view has its own SHA-256.
Consumers also compare `evidence_hash` against the persisted manifest item.
An unavailable version fails the entire batch with 410; malformed references,
duplicate identities or a changed envelope fail with 422. No partial success or
fallback to the latest event is allowed. Later corrections and tombstones leave
previously captured immutable versions readable.

Only known Telegram/WhatsApp text, Stockbit article title/text and X visible
post/thread/quoted text are returned, bounded to 12,000 characters. HTML attributes,
script/style content, private configuration snapshots, provider media URLs and
unrelated payload fields are omitted. Durable media metadata remains opaque.
`text_truncated` also flags Stockbit text already at its upstream 12,000-character
ceiling. Missing supported text is `content_unavailable=true`, never fabricated.
These flags describe content availability; `complete` describes window capture,
not proof of provider intake coverage or untruncated source content.

The existing version store has no purge path; this change adds none and retains
versions for lookback and run recovery. Minimum historical availability is not
inferred from the first or last event, which cannot prove an empty interval.
Only a separately verified, deployment-owned
`CONTROL_PLANE_SOURCE_HISTORY_AVAILABLE_FROM` ISO timestamp can assert a retained
history boundary. Unset means `history_status=unknown`; a boundary after the
requested lower cutoff means `unavailable`. Both make `complete=false`, as do
late/early capture and overflow. The timestamp is an operator assertion about
retained history, not a guarantee that every upstream post was collected. Any
future retention policy must preserve the full verified session lookback plus
owner recovery and surface missing versions as incomplete evidence. Never
backfill or replay source intake through this read API.

Hashes use UTF-8 JSON with sorted keys, compact separators, literal Unicode and
finite numbers. `payload_hash` hashes the normalized stored envelope;
`evidence_hash` hashes the full safe item excluding `evidence_hash` and
`version_ref`; `manifest_hash` hashes the complete manifest excluding itself.
These are integrity checks, not authorization credentials. Keep opaque refs
unchanged; their encoding is an implementation detail. Both POST routes only
read existing source tables and never persist work, manifests, audits, schedules,
publications or intake. No database migration or second source database is added.
