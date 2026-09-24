# Bursawatch Source Catalog and platform-pipeline architecture

**Date:** 2026-09-24

**Status:** Approved by user; implementation in progress under the approved plan

**Owner:** Abhip / Yanto, Hermes agent on the VPS

## Goal

Let an operator select supported securities and publishers, connect supported platform endpoints, and configure which approved Bursawatch capabilities use each source. Keep the UI model understandable while making the backend independent of individual people, channels, and cron packages. Adding another supported endpoint should be configuration work. Adding a platform adapter or a new processing capability remains reviewed engine work.

This design defines the target architecture and ownership boundaries. It does not authorize code changes, migrations, scheduler changes, production writes, or deployment. After this design is approved, a separate implementation plan will specify sequencing, state migration, compatibility, and release gates.

This document complements the [Swing Board shared architecture design](2026-09-23-swing-board-shared-architecture-design.md), which remains the domain contract for Swing episodes and Discord Board management. It also accounts for the existing [Stockbit live configuration design](2026-09-23-stockbit-live-control-plane-config-design.md) and [Phintraco Stock Information design](2026-09-24-phintraco-stock-status-forwarding-design.md).

## Agreed product model

### Source Catalog

The user-facing catalog has three distinct sections:

| Section | What it represents | User-managed boundary |
| --- | --- | --- |
| Securities | The engine-supported IDX securities universe | Users may select supported securities to watch, but cannot invent arbitrary securities. Adding a security to the supported universe is engine work because ingestion and processing support must exist. |
| Institutions | Curated Bursa Efek-certified securities firms that users recognize and trust | Users select from the maintained catalog. Institution identity and verified platform endpoints are catalog data, not free-form workflow definitions. |
| People & Org | Individual experts, groups, and communities | Users may add a person or organization and connect supported platform endpoints. An entry is not active until a supported endpoint and compatible capability are configured. |

Institution profiles have a 4:3 banner and a logo. People & Org profiles have a logo or profile picture. Store binary assets in private Supabase Storage and keep validated asset references and metadata in the Control Plane. The browser must use an authenticated upload path; it never receives a privileged Storage credential or writes database metadata directly. The catalog asset upload path remains separate follow-up work from the source-media upload API.

Securities are monitored entities, not publishers. Institutions and People & Org are publisher identities. One publisher may have several platform endpoints, and one endpoint may publish content about many securities. The UI may show their relationships together, but the backend must keep those identities separate.

### Source and workflow configuration

Selecting an item opens its source configuration view. That view manages the publisher's supported platform endpoints and the capabilities subscribed to their events. The product may present these as source configuration or workflow configuration; those page labels do not define backend ownership.

Publisher-level capability selections are defaults inherited by compatible endpoints. An endpoint may override a publisher default when its role or content differs. An explicit endpoint setting takes precedence over the inherited value. The effective configuration is resolved and shown clearly before saving.

Only compatible combinations may be enabled or presented as available. The engine owns a versioned capability catalog and a compatibility matrix for publisher type, platform, endpoint, and pipeline. The browser cannot create arbitrary capabilities, platform adapters, routes, or executable workflows.

User-facing capabilities may include Trading Plans, Company/Stock News, and Macro News. The engine maps those labels to one or more backend pipelines; they are not cron names. Phintraco Stock Information/Stock Status is also an explicit, deterministic capability because it already has a distinct source contract. Its availability is defined by the compatibility matrix rather than by a hidden special case in a cron editor.

## Terms and ownership

| Term | Meaning and owner |
| --- | --- |
| Catalog entity | A security, institution, or People & Org identity displayed by web-config. The Control Plane owns identity and asset metadata. |
| Publisher | An institution or People & Org identity that produces source material. |
| Platform endpoint | A canonical Telegram channel, X account, Instagram profile, WhatsApp channel, fixed RSS lane, or another supported platform location. The platform adapter owns provider-specific access and fetch state. |
| Capability | A validated user-facing choice such as Trading Plans or Company/Stock News. The engine owns its meaning, schema, and compatibility. |
| Pipeline | A backend processing module that consumes normalized events and owns its domain behavior. One capability may map to one or more pipelines. |
| Source event | An immutable, normalized record of one source publication, with attribution, source identity, timestamps, content references, and a stable event ID. |
| Subscription work item | Durable processing of one source event by one enabled pipeline under a frozen effective configuration. |
| Domain owner | The service that owns canonical business state, such as the Swing Board owner or a news owner. |
| Source Media Owner | The service that validates, stores, and privately serves binary media through Supabase Storage. It owns Storage credentials and object operations, not source events or domain state. |

The Bursawatch Control Plane owns catalog records, publisher-endpoint relationships, capability definitions and compatibility, versioned subscriptions, user-managed settings, and desired schedules. It exposes the versioned API consumed by web-config and workers. The browser is an API projection and has no direct database access.

Platform adapters own authentication to their platform, endpoint polling, provider cursors, source deduplication, parsing/normalization, and durable handoff. Domain owners own plan/news state and their domain-specific projections. Shared renderers own presentation only. Shared output services own transport delivery. A shared database does not make these ownership boundaries interchangeable: each owner writes through its own module/API and schema.

## Target architecture

~~~mermaid
flowchart LR
  User[Operator] --> UI[web-config]
  UI -->|versioned catalog and configuration API| CP[Control Plane]
  CP -->|effective endpoint and subscription snapshots| Adapter[Platform adapter workers]
  Adapter -->|validated media uploads| Media[Source Media Owner]
  Media -->|private objects| Storage[(Supabase Storage)]
  Adapter -->|durable normalized events| Inbox[Source Event Inbox and dispatcher]
  Inbox -->|independent work item per subscription| Pipelines[Capability pipelines]
  Pipelines --> Domains[Domain owners<br/>Swing Board, News, other domains]
  Domains -->|private media fetch| Media
  Domains --> Renderers[Shared renderers]
  Renderers -->|canonical delivery intents| Delivery[Shared Discord Delivery Owner]
  Delivery --> Discord[Discord destinations]
  Adapter --> Telemetry[Structured runs and health]
  Inbox --> Telemetry
  Pipelines --> Telemetry
  Domains --> Telemetry
  Telemetry --> CP
  Adapter -->|heartbeat intent| Delivery
  Pipelines -->|heartbeat intent| Delivery
~~~

### Platform ingestion

The scheduled ingestion boundary is the platform, not an individual source, person, ticker, workflow, or destination. A platform adapter invocation can fetch many configured endpoints for that platform. For example, the Telegram adapter can handle supported Phintraco and Kelas Investasi endpoints without creating one cron architecture per publisher.

Hermes remains the scheduler and execution host. A platform may use one scheduled entry point or multiple bounded shards as load requires. Concurrency and worker count are internal platform-adapter decisions; changing from vertical to horizontal execution must not change the Source Catalog, subscription, event, or pipeline contracts. Provider credentials and provider-specific cursors stay with the platform adapter. One endpoint failure is recorded and isolated so it does not discard successfully fetched events from other endpoints.

Adding an endpoint for an already-supported platform is configuration work after its identity and permissions validate. Adding a new platform requires an adapter implementation and release. Platform access, polling frequency, and endpoint limits remain system-validated and cannot be bypassed by a user-entered URL or schedule.

### Durable events and subscriptions

After validation, the adapter submits each publication once to a durable Source Event Inbox. The event records stable source and endpoint identities, provider event ID, published and observed timestamps, canonical source URL when available, normalized content or a private object-storage reference, attachment/media references, parser/schema version, and a content hash. Raw secrets and unnecessary provider payloads are excluded.

The dispatcher resolves all enabled compatible subscriptions for the event and creates a separate idempotent work item for each one. An event subscribed to three pipelines produces three independently tracked deliveries. Success, retry, rejection, or dead-letter state in one pipeline does not block or rewrite another pipeline's state. The event is acknowledged upstream only after durable acceptance; transient downstream failure is retried from the stored event, not by refetching or searching the provider.

Each work item freezes the resolved publisher defaults, endpoint overrides, capability/pipeline version, and effective configuration revision when that work item is durably created. A retry uses that exact snapshot. A later configuration edit applies to new work items. Disabling a subscription stops new work from being created; already accepted work remains visible and durable until it succeeds or is explicitly suppressed through its owning management operation. Reprocessing historical events requires an explicit, audited replay operation with a new processing identity.

Stable deduplication uses platform, endpoint, and provider event identity. Each subscription work item has its own idempotency identity. Corrections preserve the original source event and append an audited corrected view; deletions use a tombstone so retries cannot recreate suppressed output. These rules align with the source and delivery provenance already established for Swing Board management.

### Pipelines and domain owners

Pipelines consume normalized events through a versioned contract. They may validate, classify, extract, or transform content within their owned domain, then persist canonical outcomes before requesting output. User-selected capabilities map to engine-owned pipelines through explicit configuration, not cron-name conventions or code scattered across watchers.

Examples of the target mapping include:

| Source / endpoint | Capability or pipeline | Domain outcome |
| --- | --- | --- |
| Phintraco Telegram | Trading Plans / Swing Plan | Level 1 source event submitted to the Swing Board owner. |
| Phintraco Telegram | Company/Stock News and Macro News | Source event enters the appropriate news pipeline. |
| Phintraco Telegram | Stock Information / Stock Status | Deterministic grouped status processing under its explicit capability. |
| Kelas Investasi Telegram | Swing Supporting Setup | Level 2 source context submitted to the Swing Board owner. |
| BRI Danareksa endpoint | Swing Chart Context | Level 3 context submitted to the Swing Board owner. |
| Stockbit RSS | Fixed supported lanes | Versioned live configuration selects among the four existing lanes; it does not accept arbitrary RSS URLs. |

The Swing Board owner remains authoritative for ticker-to-forum routing, episode identity, source tiers, lifecycle, message projections, and management operations. The shared renderer formats source and Board content without sending it. The shared Discord Delivery Owner is the only Bursawatch component that accesses the Discord API for messages, forum threads, channels, and health delivery. These boundaries are detailed in the Swing Board design.

## Configuration and data ownership

| Data | Logical owner | Notes |
| --- | --- | --- |
| Catalog entities, publisher identity, endpoint registry, compatibility matrix, subscriptions, and effective revisions | Bursawatch Control Plane | Mutated through its authenticated, versioned API. The source catalog is not duplicated in cron-local config. |
| Platform credentials, cursors, leases, fetch state, and adapter-specific checkpoints | Platform adapter | Durable and concurrency-safe for the chosen worker strategy. Existing production state is migrated only through a separately reviewed procedure. |
| Immutable source events and per-subscription work/retry records | Source Event Inbox and dispatcher | Durable acknowledgement, replay, deduplication, retention, and audit contract. It may initially run within the existing control-plane deployment, but remains a distinct module and schema owner. |
| Canonical plan, news, and Board state | Corresponding domain owner | No watcher writes another owner's state directly. |
| Discord operations, remote IDs, receipts, retries, and reconciliation | Shared Discord Delivery Owner | One delivery authority for all Bursawatch Discord destinations. |
| Institution banners, logos, profile pictures, and source media | Supabase Storage, mediated by the Source Media Owner | Private objects; the Control Plane and source events store validated stable references and metadata, not bytes or expiring signed URLs. |
| Run summaries, config revisions, event/work-item correlation IDs, sanitized errors | Control Plane observability API/database | Raw source content and secrets are excluded. Hermes process logs remain available for execution diagnostics. |

The current Control Plane uses Postgres for versioned watcher configuration and schedule records. The user selected Supabase Storage for binary source media. A separate Source Media Owner holds the privileged Storage credential, validates and stores bounded uploads, and serves private bytes to authorized platform/domain clients. It exposes opaque stable references rather than public object URLs or expiring signed URLs. The Control Plane remains metadata-only for media, consistent with its package contract. A future catalog asset upload flow for web-config must use an authenticated server-side path and must not expose a service credential to the browser.

Schedule configuration retains separate desired and applied revisions. The trusted schedule reconciler remains the only authority that applies approved Hermes schedule changes. Source subscription settings must not silently rewrite scheduler state.

## Observability and health

Every adapter run, source event, subscription work item, pipeline run, domain operation, and delivery intent carries correlation IDs and relevant config revisions. Operational records include bounded counts, outcomes, timing, and sanitized failure codes. They do not include credentials, raw private source text, complete attachments, or untrusted provider error bodies.

Hermes process logs remain execution diagnostics. Structured run and delivery records provide queryable state. Required cron heartbeats use one shared format and route through the Shared Discord Delivery Owner to #hermes. Heartbeat delivery success is reported separately from source-fetch, processing, and destination-delivery success; a heartbeat alone is not proof that a source event reached its destination.

## Verified current state and target gap

- The current Control Plane already stores versioned watcher configuration and desired/applied schedule revisions. Stockbit Snips now uses live versioned configuration for its four fixed RSS lanes.
- The current web-config Sources view shows Securities and People reference previews. Its added/to-add states are presentation only, not saved source memberships or enabled subscriptions.
- The current Workflows view has a fixed watcher catalog and schema-specific editors. There is no general publisher registry, arbitrary People & Org endpoint onboarding, capability compatibility matrix, or source-to-pipeline subscription model yet.
- A separate deterministic design covers Phintraco Stock Information forwarding through cron-tg-market-news, but it is not yet represented as a general selectable source capability.
- Watchers currently contain different fetch, processing, output, retry, and state implementations. The shared platform/event/pipeline architecture and shared Discord Delivery Owner are target work, not claims about current runtime behavior.

The current Sources UI is a useful visual starting point, but it does not yet implement the agreed catalog taxonomy or backend semantics. The target must not treat a static card, preview image, or locally saved browser preference as a configured source.

## Required invariants

1. A security can be selected only from the engine-supported securities catalog; user input cannot create an unsupported instrument.
2. Institution and People & Org identities remain distinct from their platform endpoints. A publisher may have multiple endpoints.
3. People & Org additions, platform endpoints, and pipeline subscriptions are persisted through the Control Plane API with validation and revision history.
4. Publisher defaults are inherited by compatible endpoints; an explicit endpoint override wins. Unsupported combinations cannot be enabled.
5. A platform adapter can serve many endpoints and does not contain a publisher-specific cron architecture for each source.
6. A normalized source event is durably accepted and deduplicated before upstream progress is committed.
7. Every subscribed pipeline gets an independently durable work item and retry state; one pipeline failure cannot block another subscription.
8. Retries use a frozen effective configuration snapshot and do not silently reroute, change content, or duplicate domain effects.
9. Domain state is written only by its owning service. Shared physical storage does not permit cross-owner direct writes.
10. Shared formatters do not send. All Bursawatch Discord API access, including reads required for management or reconciliation, goes through the Shared Discord Delivery Owner.
11. Binary images and media live in private Supabase Storage behind the Source Media Owner; relational records hold references, provenance, and metadata. The owner validates type, digest, and size and returns stable opaque refs; source adapters never call Storage directly.
12. Adding a compatible endpoint is configuration. Adding a platform adapter or pipeline requires reviewed engine code, validation, and release.
13. Existing cursors, queues, and delivery history are preserved through separately reviewed, integrity-checked migrations; no implicit replay or state reset occurs.
14. UI status distinguishes configured, enabled, pending, degraded, and applied state based on backend records; it does not infer health from static metadata or a successful cron invocation alone.

## Non-goals

- Letting users create securities, platform adapters, arbitrary pipelines, unrestricted feed URLs, or executable workflow code.
- Making every capability available on every platform or source.
- Rewriting every cron in one release or moving all existing cursors without separate migration review.
- Changing Swing episode lifecycle or forum behavior defined in the Swing Board design.
- Giving web-config direct database, provider-credential, Discord-token, or Hermes-scheduler access.
- Provisioning the selected Supabase Storage bucket, policies, credentials, retention, and backup controls.

## Implementation decisions to settle in the approved plan

- Whether the Source Event Inbox is first hosted as isolated modules and tables inside service-bursawatch-control or as a separately deployed worker/API, using expected throughput and recovery needs.
- Supabase Storage bucket provisioning, source media retention and backup/restore policy, and the authenticated catalog asset upload flow.
- Endpoint verification and approval flows per platform, including how private or authenticated sources are authorized.
- Versioned contracts for normalized event types, capability compatibility, and explicit historical replay.
- Per-platform polling limits, leases, sharding, and backpressure thresholds.
- How individual existing cron state schemas map to adapter, event, pipeline, domain, and delivery ownership during phased migration.
- UI navigation, copy, and exact settings fields after API contracts are defined; presentation wording does not change the backend domain model.

## Design review checklist

- Does the three-part catalog correctly distinguish securities, trusted institutions, and user-added People & Org?
- Does publisher-level inheritance with explicit endpoint overrides match source configuration needs?
- Does the platform adapter plus durable event fan-out model capture the desired scaling boundary?
- Are independent pipeline retries and frozen subscription snapshots the expected failure and configuration behavior?
- Are ownership, asset storage, observability, and deployment boundaries clear enough to write the separate implementation plan?
