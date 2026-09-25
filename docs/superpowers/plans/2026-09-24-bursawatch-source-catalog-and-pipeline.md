# Bursawatch Source Catalog and platform-pipeline implementation plan

> **Status:** Implementation in progress, approved by user on 2026-09-24.
>
> **Approved design:** [Source Catalog and platform-pipeline architecture][catalog-spec]

## Goal

Implement the approved Source Catalog, platform ingestion boundary, durable normalized
source events, and independent pipeline subscriptions. Preserve current source behavior,
private state, message content, and delivery identity while each platform moves to the
shared contracts.

## Starting point

- The branch already contains the shared Discord Delivery Owner service and Python
  client from commit 43852be. Reuse them; do not create a second Discord sender. This
  source change does not claim that the service is deployed or live.
- The Bursawatch Control Plane already owns authenticated configuration, schedule
  revisions, audit, run summaries, and structured operational events in Postgres.
- The current Sources page has curated previews, not saved catalog membership. The
  current Workflows page has fixed watcher editors.
- Stockbit has versioned live configuration for four fixed RSS lanes. Preserve its
  current lanes, routes, and effective revision.
- Phintraco Stock Information has a deterministic path in Market News. Preserve its
  parsing, output, and no-backfill behavior while making the capability explicit.
- The Swing Board owner remains canonical for episode and forum state. Its detailed
  lifecycle is defined in the [Swing Board design][swing-spec].

## Implementation choices

1. **Use the existing Control Plane deployment initially.** Add separate source-catalog
   and event-inbox modules, API routes, tables, and retention rules to the existing
   service deployment. This avoids another service deployment while keeping event
   processing and retry ownership separate from configuration code. Split the event
   service later only if measured load or isolation needs require it.
2. **Use the existing shared control-plane client.** Extend lib-bursawatch-control with
   typed source-catalog and source-event operations. Keep ControlPlaneReporter for
   structured run telemetry; source events and pipeline work must have their own durable
   state and idempotency.
3. **Keep the platform as the scheduled boundary.** Build one ingestion runtime for
   Telegram, X, Instagram, WhatsApp, and supported RSS lanes. A platform run may process
   many configured endpoints. Internal concurrency and sharding are implementation
   details.
4. **Execute pipeline subscriptions through a shared runtime.** Store one leased work
   item per event and subscription. Platform runtimes use shared work and handler
   contracts; domain-specific handlers keep writing through their current owners. A
   failure or retry in one work item never blocks another.
5. **Use Supabase Storage for durable media, behind a separate owner.** The user chose
   Supabase Storage on 2026-09-24. Keep the bucket private and place its privileged
   credential only in a dedicated Source Media Owner service. Adapters and domain
   owners use a typed shared client and opaque stable references; Control Plane stores
   only reference metadata. The Control Plane package contract explicitly excludes
   image bytes and media. Use an injected fake provider in local tests. Bucket creation,
   policies, credentials, retention, and service bootstrap remain separate deployment
   approvals.

## Work phases

### Task 1: Add the source registry and capability API

**Packages:** service-bursawatch-control, lib-bursawatch-control

- Add additive Postgres tables and API contracts for:
  - supported securities;
  - curated institution and People & Org identities;
  - canonical platform endpoints and their publisher relationships;
  - operator selections from the engine-supported securities universe;
  - engine-owned capabilities and source/platform compatibility;
  - versioned publisher defaults and endpoint overrides;
  - asset references and source configuration revisions.
- Model institution and People & Org identities separately from platform endpoints. Keep
  the securities universe engine-owned and selectable, not user-creatable.
- Seed only verified current identities and endpoint IDs, including Phintraco, Kelas
  Investasi, BRI Danareksa, Tuntun, current social sources, and the fixed Stockbit lanes.
  Resolve each identity against existing configuration before seeding; do not infer
  publisher identity from a display name.
- Keep source tiers and capability definitions engine-owned. Seed Phintraco as level 1,
  Kelas Investasi as level 2, and BRI Danareksa and all other sources as level 3.
- Add authenticated read/write routes with field-level validation, audit records,
  optimistic revision checks, and machine-readable effective configuration snapshots.
  Secrets remain references to separately managed credentials.
- Add the new migration after the current latest migration. Preserve immutable migration
  checksums and existing dashboard-authored config. A destructive rewrite or live data
  mapping must use a separately reviewed manual migration.
- Update OpenAPI, validators, API tests, migration tests, service AGENTS/README, and
  configuration coverage documentation.

**Acceptance:** the API can list the supported securities, institutions, People & Org,
  endpoints, capabilities, compatibility, and effective subscriptions. It rejects
  arbitrary securities, unsupported platform/pipeline pairs, invalid endpoint
  identities, and stale writes without changing current watcher configuration.

### Task 2: Replace source previews with the API-backed catalog

**Packages:** web-config and service-bursawatch-control

- Change Sources to three sections: Securities, Institutions, and People & Org.
- Securities lists only supported securities and lets the user enable or disable
  supported instruments.
- Institutions lists curated Bursa Efek-certified firms. People & Org supports adding
  and editing user-managed people, groups, and communities.
- Add source configuration details for platform endpoints and compatible capabilities.
  Show publisher defaults and endpoint overrides distinctly, with the effective value
  visible before save.
- Preserve main's useful source assets and layout where accurate. Do not treat
  preview/to-add cards or browser-local preferences as saved source records.
- Keep institution 4:3 banner/logo fields and People & Org logo/profile-picture fields.
  Use the chosen object storage only after its owner, access policy, upload flow, and
  retention are reviewed. Until then, preserve public curated assets and allow the
  catalog implementation to proceed without a live upload integration.
- Extend the same-origin /api/control proxy with only the specific authenticated catalog
  routes. Do not expose database or service credentials to the browser.
- Update Source Catalog and workflow configuration docs, responsive states, access/error
  handling, and component tests.

**Acceptance:** refresh and sign-in show backend truth; an admin can add a People & Org
  identity and configure a supported endpoint; unsupported capabilities cannot be
  saved; viewers cannot mutate; old illustrative states are clearly not live data.

### Task 3: Add durable source events and independent subscription work

**Packages:** service-bursawatch-control, lib-bursawatch-control,
lib-bursawatch-pipeline-runtime, service-bursawatch-source-media,
lib-bursawatch-source-media

- Define a versioned normalized event envelope with source, publisher, endpoint,
  platform, provider event identity, published/observed time, source URL, parser
  version, content hash, bounded payload, and stable opaque media references.
- Add the Source Media Owner and shared client. The service validates size, actual
  content type, digest, and attachment kind before uploading private objects to
  Supabase Storage. Start with the existing 8 MiB per-source-object acquisition bound,
  the existing 25 MiB aggregate delivery-operation bound, and at most 16 source refs.
  Keep attachment bytes out of Postgres and never persist expiring signed URLs.
- Use deterministic upload identities so a source retry reuses the same object and a
  conflicting retry cannot overwrite it. Adapters upload media before source-event
  acceptance; they advance their source cursor only after the inbox receipt. If event
  acceptance fails, upload retry remains idempotent. Do not automatically delete
  source objects until a retention policy is separately approved.
- Domain owners retrieve private bytes through the Source Media client and pass them
  to their existing output owner. The Discord Delivery Owner remains the only service
  with Discord access and receives attachment bytes through its current operation API.
- Add durable idempotent event acceptance. A platform adapter must retain its cursor and
  local handoff record until the Control Plane confirms durable acceptance.
- In one database transaction, resolve compatible active subscriptions and create one
  independent work item per event/subscription. Freeze the resolved config and
  capability revision on each item.
- Add safe work claiming with leases, per-item retry/backoff, bounded attempts,
  sanitized rejection/dead-letter state, explicit audited replay, and an inspection API.
  Work created under an older revision must retry with its original snapshot.
- Put handler dispatch, per-item error isolation, and subscription execution in
  lib-bursawatch-pipeline-runtime. Keep event acceptance and authenticated API access in
  lib-bursawatch-control.
- Ensure disabling a subscription blocks new work but does not silently drop already
  accepted items. Provide an explicit, audited suppression path.
- Preserve immutable source events. Corrections append audited versions; message
  deletion uses a tombstone. Idempotency keys must prevent repeated provider reads, API
  retries, or handler retries from duplicating a domain effect.
- Keep media bytes out of Postgres. Control Plane validates only the stable reference
  and bounded metadata; the Source Media Owner alone resolves references to bytes.
- Keep run summaries in ControlPlaneReporter. Do not copy raw source text, credentials,
  images, or provider errors into heartbeats or routine logs.
- Add contract tests for acceptance/ack ordering, duplicate events, default/override
  resolution, independent pipeline failures, snapshot retries, lease expiry,
  suppression, correction, and replay authorization.

**Acceptance:** every accepted source event is durable before cursor advancement, and
  each enabled subscription has its own observable state and retry lifecycle.

### Task 4: Pilot the Telegram platform with current Swing and News behavior

**Packages:** add cron-tg-source-ingest; adapt cron-tg-market-news,
cron-tg-phintraco-swing, cron-tg-kelas-investasi-gtw, cron-dc-swing-board; use existing
Discord Delivery Owner

- Build the Telegram adapter to read all configured Telegram endpoints in bounded
  batches and maintain an independent cursor per endpoint.
- Migrate Phintraco and Kelas Investasi first. Classify other existing Telegram
  publishers from canonical IDs before onboarding them.
- Add pipeline handlers that preserve the existing domain owners:
  - Phintraco BUY and status events submit to the Swing Board owner under its existing
    event contract.
  - Kelas events submit as level 2 supporting context.
  - Phintraco Market News and deterministic Stock Information retain their existing
    classification, validation, and rendering contracts.
- Keep the existing Board owner and Delivery Owner authoritative. Do not copy episode
  state, route assignments, Discord IDs, or Board retry state into the adapter or
  Control Plane.
- Preserve current message text, tier, media order, source attribution, event keys, and
  source timestamps. Use the shared renderer where the existing contract requires it.
- Replace the current Telegram media block with Source Media Owner uploads. Persist only
  returned opaque refs in source events; retrieve bytes through the shared client when
  the existing domain owner needs to forward an attachment. Keep the current event
  ordering and never use a Telegram URL as durable media storage.
- Add golden output and no-post integration coverage for events that fan out to multiple
  subscriptions. Prove that a failing news pipeline does not block a Swing Board work
  item and vice versa.
- Add the Telegram package and dependencies to release-manifest metadata without
  enabling or changing a live Hermes job.

**Acceptance:** replaying fixtures yields the existing user-visible messages and Board
  events once, while event and pipeline receipts demonstrate independent delivery. No
  production source history is replayed.

### Task 5: Migrate remaining platform adapters

**Packages:** add cron-x-source-ingest, cron-ig-source-ingest, cron-wa-source-ingest,
and cron-rss-source-ingest; adapt the corresponding existing watcher packages

- Move X, Instagram, WhatsApp, and supported RSS endpoint polling behind one runtime
  boundary per platform. Keep platform-specific authentication, cursors, limits, and
  fetch behavior in that adapter.
- Where a source publishes attachments, use the shared Source Media client and the same
  validated opaque-reference contract. Each adapter must persist the source handoff and
  advance its cursor only after event acceptance; no adapter may write Supabase Storage
  directly or expose source media through public/signed locators.
- Convert each current configured source into a catalog endpoint and attach only
  compatible capabilities. People & Org endpoint additions use the same validation and
  revision model.
- Map Stockbit's four existing fixed lanes to system-owned RSS endpoints. Preserve its
  live config revision, article queue, frozen settings, routes, and future-only
  behavior. Do not permit arbitrary RSS URLs or replay old articles.
- Use independent source cursor and event idempotency for each endpoint. Preserve
  pending delivery and handoff receipts through the shared Delivery Owner.
- Retain existing parser/classifier behavior and output layouts during the first
  migration. Extract provider-independent processing only where a stable pipeline
  contract is already proven.
- Add package entry points and release-manifest dependency metadata. Retire old
  source-owned scheduled entries only in a separately approved scheduler transition
  after the replacement platform entry is verified.

**Acceptance:** every existing active endpoint has exactly one platform adapter owner,
  each event is accepted once, pipeline failures remain isolated, and no source-specific
  job is removed before its cursor and pending work are accounted for.

### Task 6: Cut over, document, and retire duplicate paths

**Packages:** all migrated adapter and pipeline packages; service-bursawatch-control;
web-config; docs and platform-bursawatch-release metadata

- Produce a read-only migration inventory for each platform: configured endpoint IDs,
  cursor boundaries, queued source items, accepted event IDs, pipeline work, delivery
  receipts, and current Hermes job identities.
- Build migrations from the inventory using package-owned snapshots and checksums. Never
  move production databases, media, or live state through this worktree. Never
  initialize a fresh cursor over an existing one.
- Test migration and rollback against synthetic copies. A cutover must preserve known
  delivered IDs and pending exact payloads, must not replay history, and must leave
  ambiguous output pending rather than recreate it.
- Roll out platform by platform. For each one, separately approve the production state
  cutover and any Hermes schedule change. Verify source fetch, durable acceptance,
  pipeline completion, Discord receipt, and #hermes heartbeat as separate signals.
- Keep the previous source path available until the new adapter has stable unattended
  evidence. Then remove duplicate source polling and stale configuration only in a
  reviewed follow-up.
- Update root and package contracts, docs/README, web-config docs, release manifest, and
  test-all. State clearly which platform owns each endpoint, which pipelines subscribe,
  and who owns each durable state store.

**Acceptance:** there is one active source reader per endpoint, one canonical source
  catalog, no direct Discord API callers outside the Delivery Owner, preserved
  history/cursors, and separately visible source, pipeline, output, and heartbeat
  health.

## Review checkpoints

1. Review Telegram pilot parity and failure isolation after the shared media path and
   domain-owner handoff are exercised with synthetic fixtures.
2. Review the complete platform migration evidence before any live schedule or state
   cutover.

These are architecture-wide checkpoints, not a separate review for every cron package.

## Verification to run during implementation

- Focused Control Plane, shared-client, pipeline-runtime, adapter, domain-owner, and web
  tests for each changed phase.
- Package suites for changed watchers, followed by the repository-wide test script.
- Web Config checks and the Web Landing validation required by its package contract.
- Isolated no-post source and pipeline runs with synthetic events, temporary
  cursor/state paths, fake object storage, and fake Discord responses.
- Release-manifest path/dependency validation and byte parity for deployed validator
  sources.
- A read-only production plan and post-release evidence only during a separately
  approved deployment step.

## Global constraints

- Reuse the Delivery Owner and its stable operation keys. Do not introduce direct
  Discord clients or a second delivery ledger.
- Do not let web-config, platform adapters, or pipeline handlers write another owner's
  domain tables directly.
- Do not change source tier, Swing lifecycle, message layout, or source classification
  rules while migrating transports.
- Do not silently fall back from invalid live config or unknown capabilities to
  hardcoded routes.
- Do not backfill, reset cursors, replay source history, post test messages, manually
  trigger live jobs, alter schedules, deploy, or mutate production storage under this
  plan alone.
- Run future code work through the reviewed release path. Production migration, service
  configuration, Supabase/object-storage provisioning, and Hermes scheduler edits need
  their own explicit current-session approval.
- Preserve package AGENTS, CRON/SKILL contracts, root AGENTS, and docs in the same
  change.

## Implementation approval boundary

The user approved this implementation plan on 2026-09-24. Code changes, tests, and
commits may proceed in the existing managed worktree. Production data migration,
Hermes job changes, release/deploy, and live storage provisioning remain separate
approval gates.

[catalog-spec]: ../specs/2026-09-24-bursawatch-source-catalog-and-pipeline-architecture-design.md
[swing-spec]: ../specs/2026-09-23-swing-board-shared-architecture-design.md
