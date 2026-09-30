# Bursawatch Operator Workspace After Source Migration

**Date:** 2026-09-29

**Status:** Approved; implementation and production rollout completed on 2026-09-30. See the rollout verification below and the active [workspace contract](../../../web-config/docs/CONTROL_PLANE.md).

## Intent and success criteria

Make the authenticated `web-config` workspace an accurate operator view of the migrated Bursawatch engine. Operators should see the actual source adapters, domain owners, schedules, configuration coverage, and recent outcomes without mistaking an old watcher run or a saved configuration for current source or delivery health. Every setting that the engine deliberately makes safe for an operator to change should have a supported, validated web control. Credentials, source cursors, runtime state, fixed system rules, and private infrastructure values remain backend-owned.

The workspace should also allow authorized operators to pause and change the cadence of migrated source-ingest interval jobs through Control Plane desired revisions and the trusted Hermes schedule reconciler. The web app must not call the Hermes CLI or write its registry directly. Fixed calendar jobs remain read-only unless separately designed.

Success means an operator can identify the actual source adapter, domain owner, and job for each supported path; edit every validated operator-safe setting through a working web control; and tell a saved intent from an observed effect. A shared source job must appear once, with clear links to every source and workflow it serves. Empty, paused, stale, and unknown states must remain distinguishable from current failures.

This design is distinct from the Published feed design in `2026-09-29-bursawatch-published-feed-design.md`. That feed adds records of delivered news and swing output. This design covers operational truth and configuration of the existing engine. The two share workspace navigation and authentication, with separate implementation plans and release checks.

## Evidence at design start

The authenticated workspace currently loads eight watcher catalog records, their API job rows, and up to 50 recent runs per watcher. Its Overview derives counts and latest statuses from those returned records. The Sources page separately reads the Source Catalog and effective subscription snapshot. The Control Plane and web proxy already support their respective configuration, schedule, catalog, profile, and run routes; they do not expose a complete migrated-runtime inventory or every source-ingest job as an operator-managed schedule.

The read-only production snapshot taken at 2026-09-29 18:37 WIB found 13 Hermes jobs, with 8 active and 5 paused, while seven of seven Control Plane desired interval schedules matched the live registry. The last successful release SHA was `8f23d7137ce1c5b6af6304165326bfb9e7503b53` and `origin/main` was `d88e0c196f274b41823da70a4ae96b0eecb7586a`; release CI was pending, and the released SHA did not match `origin/main`. The snapshot does not verify runtime checksums, source-to-delivery events, or the completeness of workspace health data.

The source securities registry is intentionally empty pending an authoritative supported universe. Saved Source Catalog intent can remain ineffective when an endpoint is unverified or lacks a supported adapter binding. A saved watcher revision applies to future owner work only when that owner successfully loads it; a desired schedule applies only after reconciliation confirms the exact revision. These states need distinct labels.

## Production rollout verification (2026-09-30)

The workspace implementation shipped in PR #28. PR #29 corrected the reconciler schedule response contract. PRs #30 and #31 corrected the observer's Hermes status field and made approved legacy cron observations compare correctly with desired intervals. All four PRs are merged. Production `main` is `b1297c269bd42fb7d56624c362e0e0e1fe059144`; its exact CI run passed, and the VPS release agent reports that same SHA as released.

The observer service and timer were installed and enabled through a separate manual VPS operation. A natural timer run reported all 13 Hermes jobs to the Control Plane. The authenticated Jobs page showed 8 observed active jobs, 5 observed paused jobs, no unknown observations, and no attention state. The 2026-09-30 production snapshot also confirmed that all 8 desired interval schedules matched the Hermes registry. The rollout did not change live schedules.

The Published page shares the workspace navigation and has its own forward-only contract. Its current boundary and publication evidence are recorded in the companion [Published Feed design](2026-09-29-bursawatch-published-feed-design.md). A successful job observation does not establish a natural publication or delivery.

## Decisions recorded

1. Target all operator-safe settings supported by the migrated owners, not merely the eight current editors.
2. Include bounded pause and cadence controls for migrated source-ingest interval jobs through the Control Plane and reconciler.
3. Preserve backend ownership of credentials, cursors, runtime state, fixed rules, and private infrastructure.
4. Give shared and dedicated jobs one Jobs page for live schedules and runtime status, with links to Sources and Workflows.

## Approaches considered

1. **Explicit engine inventory (recommended):** The Control Plane describes source adapters, domain owners, their supported operator controls, and their jobs as distinct resources. A bounded VPS reporter supplies observed runtime and scheduler state. The web keeps focused editors for validated schemas. This requires new backend contracts but does not mislabel source intake as an old watcher run.
2. **Extend watcher rows:** Represent new source-ingest jobs through the existing eight watcher records. This reuses current web code but conflates source and domain ownership and leaves ambiguous health and schedule counts.
3. **Frontend mapping only:** Rename sections and map known jobs in web code. This can correct some labels quickly but drifts from the engine, cannot make unsupported settings effective, and cannot prove current runtime state.

The user selected the explicit engine inventory.

## Design section 1: operating model and API boundary

The engine declares a versioned inventory of operational components, with stable IDs, type (`source_adapter`, `domain_owner`, or `delivery_service`), display name, supported capabilities, configuration resource references, and related Hermes job identities. Relationships are explicit: a source adapter can supply several domain owners, a domain owner can accept several capabilities, and a job can run an adapter, queue worker, owner, or maintenance action. A configuration row is not treated as a job or proof that the component is running. The source catalog remains the authority for publisher endpoints and effective capability intent; the component inventory describes which adapter and owner can act on that intent.

The Control Plane exposes read-only component and relationship views to signed-in operators. Its existing versioned config APIs remain authoritative for supported watcher settings, with new schema-specific APIs only where a migrated owner has operator-safe controls that the current contracts lack. Job desired state remains in the Control Plane. Jobs link to component IDs rather than being forced under an unrelated legacy watcher configuration. The existing Hermes reconciler is extended only for reviewed, bounded interval jobs; it remains the sole path from desired pause/cadence revisions to the live Hermes CLI.

A trusted VPS observation path reports the live registry's job identity, enabled state, schedule, and last execution evidence, plus bounded owner health observations where those owners provide them. These reports are observations with timestamps, not edits to source state or automatic claims of delivery. The API keeps declared, desired, applied, and observed values distinct. Missing observations are `unknown`; old failed runs from paused jobs stay historical. The web reads this API rather than reading Hermes, Discord heartbeats, local state files, or service credentials directly.

The proposed versioned resource additions are `GET /v1/components`, `GET /v1/components/{component_id}`, `GET /v1/jobs`, and `GET /v1/jobs/{job_id}` for authenticated human reads, plus a narrowly authorized `POST /v1/internal/observations` for the VPS reporter. Component responses list stable relationships and configuration references, while job responses show desired, reconciled, and observed state as separate objects. The existing `GET` and `PUT /v1/jobs/{job_id}/schedule` stay the schedule contract. Existing watcher-specific job reads remain compatible while the web moves to the global inventory. The exact JSON schemas and stable ID registry are part of the implementation plan and OpenAPI change; clients must reject unsupported inventory versions rather than silently guessing relationships.

The initial declared inventory follows the repository's package roles: Telegram, X, Instagram, WhatsApp, and Stockbit RSS source adapters; Telegram Market News, Phintraco Swing, GTW, Swing Board, X Account Watch, Instagram Account Watch, WhatsApp Channel Watch, and Stockbit Snips domain owners; and the Discord Delivery Owner. The Telegram adapter has its own active source-ingest job. The X, WhatsApp, and RSS adapters run through existing jobs that may also run owner work, so those jobs appear once with several component relationships. Instagram source ingest has no registered job. The Telegram domain owners' standalone reader jobs are paused while shared intake dispatches their work. The live job list is observed separately and may contain fixed Board and worker jobs; its count is not derived from component count.

## Design section 2: controls and effective state

The engine publishes a reviewed coverage matrix for every operator-safe field: owning component, schema and validator, existing API path, web editor, consuming runtime, and when a saved revision takes effect. A field is considered web-configurable only when the API validates it, the owner consumes it on a supported path, and the UI can show the resulting saved and observed states. The frontend keeps focused, schema-specific editors. It does not expose raw JSON, credentials, cursors, fixed rules, or values with no runtime consumer.

The current Source Catalog edits publisher and endpoint capability enable intent. Its `settings` objects are intentionally required to be empty. A new per-capability control requires an explicit backend schema, owner consumption contract, and editor; an empty settings object is not a general configuration API. The Sources UI separates four gates: catalog intent, endpoint verification, adapter binding, and last observed intake. X and WhatsApp profile `enabled` or mode settings are another owner-level gate and must be shown alongside catalog intent. Telegram adapter endpoint selection comes from the Source Catalog; the Telegram domain editors' provider usernames are not presented as controls for the shared reader's source selection.

The existing X, Instagram, WhatsApp, Market News, Phintraco Swing, Kelas Investasi GTW, Swing Board, and Stockbit editors remain where their validated fields are consumed. The UI describes whether a field affects future intake, processing, delivery, or only a legacy reader. It shows saved revision separately from the last revision the owner reports loading successfully. If an owner has not reported use of a saved revision, the UI says `saved, use unverified`. The current Instagram source adapter has no registered production job, so its editor must not suggest that changing it activates migrated Instagram intake.

Jobs have their own inventory and schedule controls. The active Telegram source-ingest job needs a new desired interval row; the active X source job needs an exact runtime identity and guarded transition from its legacy watcher mapping. Existing WhatsApp and Stockbit rows already point at their adapter-running jobs and should preserve their revisions. Paused Telegram Market News, Phintraco, and Kelas standalone reader rows remain visible as legacy, paused schedules and do not stand in for shared intake cadence. Fixed Board jobs and other system-owned worker cadence remain read-only unless their package contract separately declares a safe interval control. A save changes desired state only; the UI waits for the exact reconciled revision and compares it with an observed Hermes job before saying the live cadence or pause is applied.

The existing field list in `web-config/docs/CONFIGURATION_COVERAGE.md` is the baseline inventory, not proof that every field now affects the migrated path. The implementation must update that list with the owner and effect boundary for each field. The migration-specific review begins with these groups:

| Control group | Current editor/API | Required migration check |
| --- | --- | --- |
| Source publisher, endpoint, and capability enable intent | Sources and Source Catalog revision | Show verification, adapter support, and effective subscription separately; add a typed field only when an owner actually consumes it |
| X, Instagram, and WhatsApp profile identity, mode, filtering, media, routing, and additive instruction | Existing profile editors and watcher config revisions | Confirm which adapter and domain owner loads each field; show unscheduled Instagram intake and separate X/WhatsApp owner gates |
| Stockbit feed switches, two routes, and additive instruction | Existing Stockbit editor and watcher config revision | Confirm the RSS adapter and owner load the revision; preserve four fixed feed identities and two distinct destinations |
| Telegram Market News, Phintraco, and GTW source and destination fields | Existing domain editors and watcher config revisions | Distinguish future domain processing controls from paused standalone Telegram reader selection; keep the shared reader's Source Catalog selection explicit |
| Swing Board heartbeat destination | Existing Board editor and watcher config revision | Keep fixed Board jobs separate; do not imply the heartbeat setting configures Board publication routes |
| Interval enabled state and cadence | Existing job schedule API, extended for the migrated jobs | Link the exact active job, enforce its bounds, and require desired, applied, and observed agreement before saying live |

Credentials, provider sessions, cursors, source event state, parser rules, delivery retry mechanics, fixed job timing, and private worker infrastructure have no operator editor. A new operator-safe engine field discovered during implementation must be added to this inventory with its validator, API, owner consumer, and UI behavior before claiming complete coverage.

## Design section 3: workspace surfaces and status language

The navigation is Overview, Sources, Workflows, Jobs, History, Published, and Account. Published is specified in the separate feed design. Jobs is a single home for scheduler identity, live observation, and safe schedule controls, because one shared source-ingest job can feed several workflows. Sources and Workflows link to relevant job details and show a compact schedule summary, without duplicating an editable schedule control or claiming exclusive ownership of a shared job.

Overview leads with current, timestamped evidence: source intake, domain processing, confirmed delivery, and schedule reconciliation are distinct summaries. The existing `Watchers` count becomes an explicitly labeled count of configured workflows if retained. `Runs needing attention` becomes a historical count within the bounded returned sample, with its time range and coverage limit beside it; old failed runs of paused readers do not become active incidents. A component is healthy only against its own declared evidence contract and freshness threshold. Missing reports and unsupported telemetry appear as `unknown` or `not instrumented`, never as green. The page shows when the Control Plane last received each observation, not just the browser refresh time.

Sources shows publisher endpoints, capability intent, endpoint verification, effective adapter binding, and the most recent observed intake for each source path. An empty Securities list explicitly says no supported securities have been registered; it does not imply an API loading failure. A source with saved enabled intent but an unverified endpoint or absent adapter is labeled inactive with the reason. Clicking a source reveals its adapter and downstream owners, then links to the relevant Jobs and Workflows records.

Workflows represents domain owners and their validated configuration editors. Each detail page names its input paths and current owner evidence. It separates saved configuration revision, last owner-loaded revision, and recent processing results. Legacy standalone schedules remain visible as paused historical job records through Jobs, but the workflow detail does not present one as the cadence of shared Telegram intake. Instagram's unscheduled migrated adapter is shown as unscheduled rather than active because an editor exists.

Jobs lists every declared job, including active source-ingest intervals, adapter-running watcher jobs, paused legacy readers, and fixed jobs. Each row shows its component relationships, schedule kind, desired revision, reconciled revision, observed Hermes enabled state and cadence, observation timestamp, and last execution evidence if reported. A shared job change shows affected sources and workflows before an administrator saves it. Editable interval controls enforce backend bounds; fixed or otherwise system-owned cadence is read-only. A pending, mismatched, stale, or missing observation is shown distinctly from an applied schedule. A successful reconciliation without a matching fresh Hermes observation is not labeled live.

History keeps the existing bounded run/event view with explicit coverage by owner and time window. A missing source-adapter run stream is an instrumentation gap, not a zero-run result. The UI can link a run to a Published record when a confirmed publication exists, but a `completed` run alone does not prove delivery. Account stays focused on user access and sessions.

## Design section 4: trust, failures, and rollout

Human reads of component inventory and observations use the existing authenticated viewer/admin boundary. Configuration and desired schedule writes remain admin-only, revision-checked, audited Control Plane operations. The web proxy adds only explicit allowlisted routes and validates inputs; it stays same-origin, authenticated, and `no-store`. A dedicated VPS reporter may submit narrowly typed observations for allowlisted component and job IDs under a scoped machine identity. It cannot edit configuration, desired schedules, source cursors, or deliveries. The existing reconciler retains its separate authority to apply reviewed interval schedules and report exact reconciliation revisions.

Observations carry a source identity, observed time, receipt time, job or component ID, and bounded status evidence. A stale, duplicate, out-of-order, unknown-ID, or malformed report cannot overwrite a newer accepted observation or turn an unknown state green. The API returns a freshness classification based on each component's declared expectation. Raw provider errors, paths, credentials, post bodies, and private state never enter the observation API or the web response. The UI distinguishes `not instrumented`, `unknown`, `stale`, `paused`, `pending application`, `mismatch`, `degraded`, and `healthy` only when evidence warrants each label.

Failed or ambiguous configuration and schedule saves preserve the draft, do not silently retry, and require a fresh authoritative read before another attempt. A save success confirms only the Control Plane revision. Reconciler errors and live-registry mismatches stay visible with safe summaries and timestamps. Partial inventory or observation reads show an incomplete-data notice and preserve the distinction between an unavailable record and a true empty list. Viewer sessions never render disabled admin controls as if they could save.

The implementation sequence is additive: define and test the inventory and observation contracts; add trusted reporting and exact source-ingest job registration; verify the reconciler's bounded mapping without changing live schedules; then update web routes, editors, and workspace pages. Legacy watcher APIs and URLs stay compatible during the transition. Any production registration or retargeting of a Hermes job, schedule, service, reporter credential, or release artifact follows its existing separate approval boundary. Web publication follows the repository's independent Vercel release path. No backfill, synthetic delivery, manual run, or source replay is part of the verification.

The current `web-config/AGENTS.md` and `web-config/DESIGN.md` still specify five destinations and schedule controls inside each workflow. The implementation updates those files, `web-config/docs/CONFIGURATION_COVERAGE.md`, the public API contract, and relevant package instructions in the same changes as the new Jobs and Published navigation. Existing visual, accessibility, authentication, and data-minimization rules remain applicable.

Verification uses synthetic backend contract tests for role separation, revision conflicts, observation ordering and freshness, shared-job relationships, and fixed versus editable schedules. Web tests cover loading, partial failure, status wording, form bounds, and viewer/admin permissions. The read-only production snapshot checks exact deployed SHA and desired-to-live interval parity before production claims. After an approved rollout, verify a real naturally occurring source intake, domain processing, and confirmed delivery separately, plus owner-loaded config revisions and observed Hermes job state. A passing build, service health check, scheduler heartbeat, or run completion is insufficient evidence for the entire path.

## Acceptance checks

- Every declared source adapter, domain owner, and job has a stable identity, explicit relationship, and honest coverage state. The UI never treats the eight watcher configuration records as the whole engine.
- Every operator-safe field has a backend validator, owner consumer, authenticated API, web control, and stated effect boundary. A saved setting without owner-load evidence is labeled unverified.
- Every editable interval schedule has a reviewed bound and exact Hermes identity. The UI separates saved desired state, reconciler application, and a fresh matching live observation. Shared jobs show affected sources and workflows before a save.
- Overview and History label bounded historical run samples as history. Current intake, owner processing, delivery, and job state use timestamped evidence and show unknown or unavailable coverage honestly.
- Viewer sessions have read-only access; admin writes are revision-checked and audited. The VPS reporter and reconciler retain separate, scoped identities. Failed or ambiguous writes preserve drafts and require a fresh read.
- Production checks use natural runs and confirmed delivery receipts, without replay, synthetic posts, or unapproved scheduler or service mutations.
