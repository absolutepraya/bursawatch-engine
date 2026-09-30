# Bursawatch Operator Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the authenticated web-config workspace accurately describe and control the migrated Bursawatch engine, including every operator-safe setting and reviewed interval schedule.

**Architecture:** The Control Plane owns a declared component/job inventory and separate desired, reconciled, and observed states. A scoped VPS observer reports sanitized Hermes registry facts; the existing reconciler remains the only writer of supported live interval schedules. Web-config consumes versioned, authenticated reads and writes, then presents Sources, Workflows, Jobs, Overview, and History without treating legacy watcher runs as current engine health.

**Tech Stack:** Python 3, FastAPI, Psycopg/Postgres, existing Hermes reconciler CLI boundary, Next.js/TypeScript/Zod, Supabase user JWT.

**Spec:** `docs/superpowers/specs/2026-09-29-bursawatch-operator-workspace-design.md`

**Implementation status:** Complete on the feature branch. Validation passed with `bash scripts/test-all`, `npm run check` in both web packages, and a synthetic admin/viewer browser smoke. Production activation and deployment remain separately gated.

## Global Constraints

- Use Node 24 for both web packages; run `npm ci` in each package before its first web test/check command in a fresh worktree.

- Every operator-safe field needs a validator, Control Plane API, web editor, consuming owner, and stated effect boundary. Credentials, sessions, cursors, runtime state, fixed rules, and worker infrastructure remain backend-owned.
- The active Telegram source-ingest job gets a reviewed interval control. Existing X, WhatsApp, and Stockbit job identities and desired revisions are preserved; paused standalone Telegram reader jobs stay visibly paused. Fixed Board jobs remain read-only.
- The web never calls Hermes, reads VPS state, stores machine tokens, or infers live application from a saved revision. Desired, reconciled, and fresh observed states are separate.
- Missing, stale, unsupported, and failed observations are distinct. Historical bounded run samples do not become current incident counts; a completed run does not prove delivery.
- Reads use authenticated viewer/admin JWTs. Writes remain admin-only, optimistic-revision checked, and audited. The observer and reconciler use distinct scoped machine identities.
- Do not change a live Hermes job, cadence, service, or deployment without the existing explicit production approval. Never use replay, test posts, or manual cron runs for verification.
- Read each affected package's `AGENTS.md` and root contract before changing it. Update `web-config/AGENTS.md`, `DESIGN.md`, configuration coverage, package instructions, and OpenAPI with the relevant implementation.

## Review Focus

1. A desired schedule matching an old reconciler revision but mismatching the fresh Hermes registry must say `mismatch`, not active. Tasks 3, 10, and 11 test it.
2. A shared Telegram job change must show all affected sources/workflows before save and retain one exact job identity. Tasks 1, 2, and 10 test it.
3. A missing or stale observation must remain `unknown` or `stale`, even when an old run succeeded. Tasks 3, 8, 9, and 11 test it.
4. A settings save that the owner has not reported loading must say `saved, use unverified`; an ambiguous write must retain the draft. Tasks 3, 9, and 10 test it.
5. An endpoint with enabled catalog intent but no verification or adapter binding must remain ineffective, with a reason. Tasks 1 and 9 test it.
6. A Source Inbox event or completed pipeline work must never be shown as a confirmed delivery. Tasks 4, 9, and 11 test it.

---

## File map and delivery order

`service-bursawatch-control/bin/control_plane/operator_inventory.py` declares stable component IDs, types, capabilities, configuration references, and component-to-job relationships. `operator_observations.py` validates and stores timestamped job/component evidence. `operator_activity.py` projects timestamped Source Inbox events and pipeline work without implying delivery. Migration `019_operator_inventory.sql` adds nullable job ownership, relationship and observation tables, and bounded Source Inbox query indexes without rewriting historical rows. `api.py` adds global human read views and a scoped machine observation write. `platform-bursawatch-observer/` is a separate read-only host package for bounded Hermes registry observations; `platform-hermes-schedule-reconciler/` remains the only live scheduler writer. `web-config/src/lib/operator-inventory.ts` validates the new reads, while the workspace loader and focused components render them.

The operator inventory/backend API and web UI can ship additively. The Telegram schedule row and observer timer require separate reviewed production activation. The Published feed plan reserves migration `020_publications.sql` and can later add confirmed-delivery evidence to Overview. Until then, the delivery summary must say `not instrumented` unless a source of confirmed receipts exists. Both plans agree on the eventual navigation: Overview, Sources, Workflows, Jobs, History, Published, Account.

## Fast execution path

**Model assignment:** The primary agent uses GPT-6 Luna Max and owns shared contracts, integration decisions, and final verification. Every spawned subagent, including implementers and reviewers, must also use GPT-6 Luna.

Use one managed implementation worktree for the shared Control Plane and web-config changes. Bring both approved specs and plans into that branch before product edits, so `api.py`, OpenAPI, migration numbering, proxy routes, and navigation have one integration owner. The task numbers below remain a coverage checklist, not a sequence of 11 reviews or deployments.

1. **Engine truth:** Complete Tasks 1 to 4 together. Freeze component IDs, job relationships, activity response shapes, and migration `019` before frontend or publication work consumes them. Run the focused Control Plane tests as each contract lands; rehearse the migration once after the complete `019` change.
2. **Runtime and controls:** Complete Tasks 5 to 7 against those contracts. The observer and reconciler can be implemented independently in separate packages, with one integration review of exact Hermes identity, credential separation, and revision behavior. Inventory every editable field once in Task 6; fix only proven editor, validator, or consumer gaps.
3. **Visible workspace:** Complete Tasks 8 to 10 as one frontend pass using the frozen reads. Reuse current editors, loaders, and controls. Do not rebuild a component merely to change its status wording or navigation. The Jobs page and honest Overview/Sources/History become the first reviewable operator experience.
4. **Integration gate:** Complete Task 11 after the frontend and backend are assembled. Run focused tests during each pass, each affected package suite once when its slice stabilizes, then one `bash scripts/test-all` and one check per web package. Rerun only suites affected by subsequent fixes. Read-only production inspection can inform the final rollout record, but implementation does not install the observer or edit live jobs.

The per-task commit steps keep changes recoverable; they do not require a separate human approval or fresh reviewer for every commit. Keep the live schedule, reporter credential, service installation, and deployment approvals as distinct final rollout gates. This ordering preserves every operator-safe control and every status/evidence distinction in the spec.

### Task 1: Declared component inventory and relationships

**Focused command:** `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_operator_inventory.py`

**Files:** Create `service-bursawatch-control/bin/control_plane/operator_inventory.py`, `service-bursawatch-control/tests/test_operator_inventory.py`; modify `service-bursawatch-control/bin/control_plane/api.py`, `openapi/control-plane.v1.yaml`, `tests/test_api.py`.

**Interfaces:** `operator_inventory.py` defines immutable `ComponentDefinition(component_id, kind, display_name, capabilities, pipeline_ids, config_resource_ids, related_component_ids, job_ids)` and `list_components() -> tuple[ComponentDefinition, ...]` for Telegram, X, Instagram, WhatsApp, and RSS adapters; eight domain owners; and Discord Delivery Owner. `component_view(component_id: str) -> dict[str, Any]` serializes one declaration. `GET /v1/components` and `GET /v1/components/{component_id}` are viewer/admin only; unknown inventory versions fail closed in clients.

- [x] Write failing `test_inventory_has_all_migrated_owners` (`assert len(domain_owners) == 8`), `test_shared_telegram_job_has_three_owners` (`assert related_owner_ids == expected_ids`), and `test_machine_cannot_read_human_inventory` (`assert status_code == 403`); cover five adapters, Instagram's absent job, and stable IDs.
- [x] Run `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_operator_inventory.py`; expect failure for the missing inventory.
- [x] Implement immutable definitions and the two read routes. Derive effective source gates from the Source Catalog rather than duplicating publisher settings in the inventory. Update OpenAPI.
- [x] Run the focused inventory/API tests; expect pass.
- [x] Commit the inventory contract.

### Task 2: Global job registry and migration-safe schedule identities

**Focused command:** `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_operator_jobs.py tests/test_migration_rehearsal.py`

**Files:** Create `service-bursawatch-control/migrations/019_operator_inventory.sql`, `service-bursawatch-control/tests/test_operator_jobs.py`; modify `bin/control_plane/store.py`, `bin/control_plane/api.py`, `tests/test_migrations.py`, `tests/test_migration_rehearsal.py`, `openapi/control-plane.v1.yaml`.

**Interfaces:** `SchedulerJobRecord` gains `watcher_id: str | None` and `component_ids: tuple[str, ...]`. `Store.list_all_jobs() -> list[SchedulerJobRecord]` returns each declared job once with related component IDs, current desired revision, and reconciliation result. `GET /v1/jobs` and `GET /v1/jobs/{job_id}` are viewer/admin only. The migration registers `bursawatch-tg-source-ingest` as a new 60-second desired interval row keyed to the exact existing Hermes name, with a pending revision until the reconciler verifies it; it also declares missing read-only fixed jobs such as the Telegram Market News watchdog and Board lifecycle job. X's existing source row and WA/Stockbit revisions remain intact. The same immutable migration creates the observation table needed by Task 3 and indexes Source Inbox endpoint and pipeline timestamps for Task 4.

- [x] Write failing `test_telegram_job_is_one_global_row` (`assert job.runtime_job_key == "bursawatch-tg-source-ingest"`), `test_existing_revisions_are_unchanged` (`assert after == before` for X/WA/Stockbit), and `test_fixed_board_job_has_no_schedule_write` (`assert status_code == 422`); cover nullable watcher, paused readers, watchdog, Board lifecycle, and no missing declared job.
- [x] Run focused job and migration tests; expect failure for missing global registry behavior.
- [x] Add a `-- bursawatch-release: manual` migration that preserves existing rows, makes `watcher_id` nullable, creates component-job links, the observation table, and `(endpoint_id, created_at desc)` / `(pipeline_id, created_at desc)` Source Inbox indexes. Guard new job registration against unexpected preexisting identities. Register missing fixed jobs as read-only after confirming the exact current Hermes identities. Do not change Hermes here. Add global read routes and keep watcher-specific routes compatible.
- [x] Run focused tests and migration rehearsal; expect pass.
- [x] Commit the schema and job API.

### Task 3: Timestamped observation contract and scoped API

**Focused command:** `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_operator_observations.py tests/test_auth.py`

**Files:** Create `service-bursawatch-control/bin/control_plane/operator_observations.py`, `service-bursawatch-control/tests/test_operator_observations.py`; modify `bin/control_plane/auth.py`, `bin/control_plane/api.py`, `openapi/control-plane.v1.yaml`, `env.example`, `tests/test_auth.py`.

**Interfaces:** `CONTROL_PLANE_OBSERVER_TOKEN` authenticates a distinct `observer` principal. `validate_observation(payload: object, observer_id: str) -> Observation` accepts a versioned allowlisted component or job ID, observed time, kind, bounded safe status, exact Hermes identity/schedule when kind is job, and optional loaded config revision where the owner has evidence. `ObservationStore.accept(observation: Observation) -> Observation` is monotonic per identity/kind and retains received time. `POST /v1/internal/observations` accepts only that principal; human reads expose freshness classification and safe summaries without raw provider data.

- [x] Write failing `test_older_observation_cannot_replace_newer` (`assert stored == newer`), `test_stale_observation_is_not_healthy` (`assert view.status == "stale"`), and `test_viewer_cannot_post_observation` (`assert status_code == 403`); cover unknown IDs, future times, oversized fields, secrets, and mismatched schedule.
- [x] Run focused observation/auth/API tests; expect missing contract failures.
- [x] Implement the scoped observer credential, validator, store, API, and response projections. Keep the observer unable to write desired schedules, configurations, cursors, or publications.
- [x] Run focused and pool-integration tests; expect pass.
- [x] Commit the observation contract.

### Task 4: Source Inbox intake and pipeline activity reads

**Focused command:** `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_operator_activity.py tests/test_api.py`

**Files:** Create `service-bursawatch-control/bin/control_plane/operator_activity.py`, `service-bursawatch-control/tests/test_operator_activity.py`; modify `bin/control_plane/source_inbox.py`, `bin/control_plane/api.py`, `openapi/control-plane.v1.yaml`, `tests/test_api.py`. Use the Source Inbox indexes created with `019_operator_inventory.sql` in Task 2.

**Interfaces:** `get_endpoint_activity(inbox_store: InboxStore, endpoint_id: str) -> EndpointActivity` returns the most recent accepted Source Inbox event `created_at` or `None`. MemoryInboxStore records the same acceptance time for synthetic tests. `get_pipeline_activity(inbox_store: InboxStore, pipeline_id: str) -> PipelineActivity` returns the most recent work `created_at` and its current bounded status, or `None`; the existing work schema has no status-change timestamp, so the response does not invent one. `InboxStore` is the narrow common protocol for these two reads, implemented by the existing memory and Postgres stores. Add authenticated viewer/admin `GET /v1/components/{component_id}/activity` that projects these aggregates for source endpoints resolved through the Source Catalog and owner pipeline IDs declared in the inventory. Label event time `last accepted into Source Inbox` and pipeline work `last pipeline work`; neither establishes fetch attempt, owner success, or Discord delivery. Missing rows return `unknown` with null timestamps, not zero activity.

- [x] Write failing `test_endpoint_activity_uses_latest_accepted_event` (`assert result.accepted_at == newer_created_at`), `test_missing_endpoint_activity_is_unknown` (`assert view.status == "unknown"`), and `test_done_pipeline_work_is_not_delivered` (`assert view.delivery_status == "not instrumented"`); cover suppressed and dead-letter work, stale activity, invalid IDs, viewer read, and machine read denial.
- [x] Run the focused activity/API tests; expect failure for the missing aggregate and route.
- [x] Implement bounded indexed SQL projections and matching memory-store behavior, and expose only aggregate timestamps/status through the component activity route. Keep envelope payloads, provider IDs, cursor state, and raw errors out of the response.
- [x] Run the focused activity/API and migration-rehearsal tests; expect pass.
- [x] Commit the intake activity contract.

### Task 5: Read-only VPS job observer

**Focused command:** `cd platform-bursawatch-observer && ../../../.venv/bin/python -m pytest -q tests/test_observe.py`

**Files:** Create `platform-bursawatch-observer/AGENTS.md`, `README.md`, `bin/observe.py`, `bin/bursawatch-operator-observer.sh`, `deployment/systemd/bursawatch-operator-observer.service`, `deployment/systemd/bursawatch-operator-observer.timer`, `tests/test_observe.py`; modify `scripts/test-all`, `platform-bursawatch-release/release-manifest.json`, root `README.md` and `AGENTS.md` as required for the new host package.

**Interfaces:** `observe.py` defines `ObserverError` and `read_observed_jobs(path: Path, allowed_names: set[str]) -> list[dict[str, Any]]`, which reads the Hermes registry without mutation and requires one exact match per declared runtime name. `report_observations(api_origin: str, token: str, rows: list[dict[str, Any]]) -> None` submits only sanitized status, schedule, job identity, and bounded last-execution metadata. The observer has its own environment and timer; it never invokes the Hermes CLI or imports the reconciler's credential.

- [x] Write failing `test_duplicate_runtime_name_blocks_report` (`assert raises ObserverError`), `test_observer_never_invokes_cli` (`assert cli_calls == []`), and `test_registry_read_has_no_file_writes` (`assert bytes_after == bytes_before`); cover missing names, fixed/interval jobs, parse errors, and redaction.
- [x] Run the focused observer command; expect failure before the observer exists.
- [x] Implement the read-only package and deployment assets. Add metadata/test coverage to the manifest, but keep first VPS installation and credential provisioning as a separately approved manual step.
- [x] Run the observer tests, release-manifest tests, and `bash scripts/test-all`; expect pass.
- [x] Commit the observer package and docs.

### Task 6: Field-by-field operator control coverage

**Focused command:** `cd web-config && npm test -- src/lib/operator-control-coverage.test.ts src/lib/watcher-fields.test.ts src/lib/source-catalog.test.ts`

**Files:** Modify `web-config/docs/CONFIGURATION_COVERAGE.md`, `service-bursawatch-control/tests/test_validators.py`, `web-config/src/lib/source-catalog.ts`, `src/lib/source-catalog.test.ts`, `src/lib/watcher-fields.ts`, `src/lib/watcher-fields.test.ts`, and `tests/test_config.py` in each of `cron-tg-market-news`, `cron-tg-phintraco-swing`, `cron-tg-kelas-investasi-gtw`, `cron-dc-swing-board`, `cron-x-account-watch`, `cron-ig-account-watch`, `cron-wa-channel-watch`, and `cron-stockbit-snips`; create `web-config/src/lib/operator-control-coverage.ts`, `src/lib/operator-control-coverage.test.ts`. Update package contracts only where an actual field effect changes.

**Interfaces:** `operatorFieldCoverage` maps each editable JSON field path, including Source Catalog `publisher_defaults[].enabled` and `endpoint_overrides[].enabled`, eight watcher editors, and interval job `enabled`/`interval_seconds`, to its owning component, validator, API/editor, consuming runtime, and effect boundary. Tests compare those paths with every rendered control. The coverage document mirrors that checked inventory. Source Catalog `settings` stays an empty object until a typed owner consumer is approved. A field with no migrated-path consumer is labeled legacy-only or removed from the active control surface after preserving the underlying config; never claim an editor activates unscheduled Instagram ingest or configures shared Telegram reader selection.

- [x] Write failing `operator field coverage matches all editors` (`expect(coveredPaths).toEqual(editablePaths)`) and `GTW required instruction stays validated` (`expect(result.success).toBe(false)`); cover Source Catalog enable paths, interval schedule controls, each X/WA profile gate, Stockbit feed/route, Telegram owner field, and Board heartbeat path.
- [x] Run the focused control-plane validator, owner config, and web field suites; expect failures where contracts or labels diverge.
- [x] Update only actual validator/editor/owner mismatches found by the matrix. Preserve unknown config keys and revision semantics; add typed backend controls only when a consumer exists.
- [x] Run focused suites; expect pass.
- [x] Commit the coverage matrix and contract corrections.

### Task 7: Guarded source-ingest schedule reconciliation

**Focused command:** `cd platform-hermes-schedule-reconciler && ../../../.venv/bin/python -m pytest -q tests/test_reconcile.py`

**Files:** Modify `platform-hermes-schedule-reconciler/bin/reconcile.py`, `tests/test_reconcile.py`, `AGENTS.md`, and `service-bursawatch-control/tests/test_operator_jobs.py`; create `platform-hermes-schedule-reconciler/README.md` with the supported job mapping and dry-run contract.

**Interfaces:** `reconcile_all` accepts the new Telegram desired row only when its runtime job key is the declared exact live name and its interval is within backend bounds. It preserves X's runtime name `bursawatch-x-account-watch`, WA's `bursawatch-wa-channel-watch`, and Stockbit's `cron-stockbit-snips`. A matching legacy cron expression is observed and acknowledged without an edit; a changed desired revision is applied only through the existing Hermes CLI and read-back verification.

- [x] Write failing `test_telegram_existing_cron_matches_without_edit` (`assert commands == [] and outcome.status == "applied"`) and `test_unexpected_runtime_key_refuses_edit` (`assert commands == []`); cover pause/cadence change, stale revision, and fixed-job refusal.
- [x] Run the reconciler suite; expect failure for the new Telegram mapping.
- [x] Extend only the reviewed allowlist/mapping, preserving revision and dry-run behavior. Do not install or invoke against production.
- [x] Run the reconciler and Control Plane job suites; expect pass.
- [x] Commit the reconciler contract.

### Task 8: Web schemas, proxy allowlist, and view loader

**Focused command:** `cd web-config && npm test -- src/lib/operator-inventory.test.ts src/lib/workspace-loader.test.ts src/server/control-route.test.ts`

**Files:** Create `web-config/src/lib/operator-inventory.ts`, `src/lib/operator-inventory.test.ts`; modify `src/server/control-plane.ts`, `src/server/control-route.ts`, `src/server/control-plane.test.ts`, `src/server/control-route.test.ts`, `src/lib/workspace-loader.ts`, `src/lib/workspace-loader.test.ts`.

**Interfaces:** Zod `component`, `componentActivity`, `operatorJob`, and `observation` schemas reject unsupported inventory versions and unsafe/unknown fields. The server reader adds `listComponents()`, `getComponent(id)`, `getComponentActivity(id)`, `listOperatorJobs()`, and `getOperatorJob(id)`; same-origin `/api/control` allowlists only these GET paths, using the user's JWT and `no-store`. The loader fetches only each view's required resources, cancels obsolete reads, and reports partial failures without converting them to empty lists.

- [x] Write failing `global job accepts null watcher` (`expect(parsed.watcher_id).toBeNull()`), `auth loss clears partial records` (`expect(records).toEqual([])`), and `proxy rejects internal observation POST` (`expect(status).toBe(404)`); cover component activity with unknown/null timestamps, shared links, stale/malformed response, and JWT/no-store behavior.
- [x] Run `cd web-config && npm run check`; expect failing tests for absent schemas/read methods.
- [x] Implement schemas, server reader, proxy allowlist, and bounded view loader. Keep the existing per-watcher run/event paths compatible.
- [x] Run `npm run check`; expect pass.
- [x] Commit the web API boundary.

### Task 9: Honest Overview, Sources, Workflows, and History

**Focused command:** `cd web-config && npm test -- src/lib/control-analytics.test.ts src/components/source-catalog.test.tsx`

**Files:** Modify `web-config/src/components/control-dashboard.tsx`, `src/lib/control-analytics.ts`, `src/components/source-catalog.tsx`, `src/components/source-hub.tsx`, `src/components/workspace-app.tsx`, `src/components/connected-workflow-summary.tsx`, `src/components/workspace-list-filters.tsx`, related CSS/tests.

**Interfaces:** Overview separates last accepted Source Inbox input, pipeline work, confirmed delivery where available, job status, and historical bounded run activity. Sources shows catalog intent, endpoint verification, effective adapter binding, last accepted input, and a truthful empty Securities state. These timestamps come from Task 4 and carry their coverage limits. Workflows show owner inputs, saved revision, last observed owner-loaded revision or `saved, use unverified`, and links to shared jobs. History labels missing source-adapter telemetry as unavailable rather than zero.

- [x] Write failing `old paused failure is historical` (`expect(currentIncidents).toBe(0)`), `enabled unverified endpoint is ineffective` (`expect(source.status).toBe("inactive")`), `unloaded config is unverified` (`expect(label).toBe("saved, use unverified")`), and `inbox input does not imply publication` (`expect(deliveryStatus).toBe("not instrumented")`); cover bounded samples, unscheduled Instagram, and missing delivery evidence.
- [x] Run focused web analytics/component tests; expect current labels or counts to fail.
- [x] Update presentation and selectors without changing the sample-only `/app` experience. Show evidence timestamps and coverage reasons next to status labels.
- [x] Run the focused web tests; expect pass.
- [x] Commit these workspace views.

### Task 10: Global Jobs page and safe controls

**Focused command:** `cd web-config && npm test -- src/components/operator-jobs.test.tsx`

**Files:** Create `web-config/src/components/operator-jobs.tsx`, `src/components/operator-jobs.test.tsx`; modify `src/components/workspace-navigation.tsx`, `src/components/workspace-app.tsx`, `src/app/workspace/[[...view]]/page.tsx`, `src/app/workspace-navigation.css`, `src/app/workspace.css`, `src/components/schedule-editor.tsx`, relevant tests, `AGENTS.md`, `DESIGN.md`.

**Interfaces:** `/workspace/jobs` lists all declared jobs once, their component relationships, desired/applied/observed schedule, last execution evidence and timestamp. Admin interval controls use existing revisioned `PUT /v1/jobs/{job_id}/schedule` and backend bounds. Before a shared-job save, the UI names affected sources/workflows. Fixed jobs and viewer sessions have no save action. Existing `/workspace/schedules` remains a compatibility redirect to Jobs.

- [x] Write failing `shared job save lists affected workflows` (`expect(impact).toEqual(expectedOwners)`), `mismatched live schedule is not active` (`expect(label).toBe("mismatch")`), and `ambiguous save retains draft` (`expect(draft).toEqual(original)`); cover stale/unknown, fixed/viewer controls, 375px navigation, and keyboard focus.
- [x] Run focused Jobs and navigation tests; expect missing page failures.
- [x] Implement the Jobs page and route, move active controls out of Workflow details, preserve links back to Sources and Workflows, and update web contracts.
- [x] Run `npm run check` in `web-config` and `web-landing`; expect pass.
- [x] Commit the Jobs page.

### Task 11: Integration, documentation, and release evidence

**Focused command:** `cd web-config && npm test -- src/lib/operator-workspace-contract.test.ts`

**Files:** Create `web-config/src/lib/operator-workspace-contract.test.ts`; modify `web-config/docs/CONTROL_PLANE.md`, `docs/CONFIGURATION_COVERAGE.md`, `service-bursawatch-control/README.md`, `openapi/control-plane.v1.yaml`, root `DEPLOYMENT.md`.

**Interfaces:** Every operator-visible state has a declared evidence source and freshness rule. An API save confirms a revision, not runtime use. Release notes enumerate separately approved observer service/credential, Control Plane migration, Telegram desired job enrollment, reconciler change, and web deployment.

- [x] Write failing `operator workspace never invents delivery` (`expect(deliveryStatus).toBe("not instrumented")`) and `stale observer overrides old successful run` (`expect(jobStatus).toBe("stale")`); use fixtures with one shared job, paused reader, unsupported endpoint, and confirmed config-load revision.
- [x] Run the integration tests; expect failure until coverage gaps are resolved.
- [x] Complete docs and synthetic fixtures. Record the exact order: additive API and migration, observer credentials/service, read-only observation, reviewed schedule enrollment and reconciler dry run, web release, then natural-run verification. Keep production writes out of this plan's execution without separate approval.
- [x] Run focused suites, `bash scripts/test-all`, and `npm run check` in both web packages. Run `python3 scripts/production_snapshot.py --production` only before making current-production claims; this implementation adds none and makes no deployment claim.
- [x] Commit final docs and contract corrections.

## Execution handoff

This plan does not authorize a VPS service install/restart, live scheduler edit, release-agent manifest bootstrap, production credential change, or web deployment. Those are distinct reviewed steps after implementation. Production verification must compare the deployed SHA and runtime artifacts, exact Hermes registry observations, owner-loaded config where reported, and natural source-to-delivery evidence; any missing link remains unverified.
