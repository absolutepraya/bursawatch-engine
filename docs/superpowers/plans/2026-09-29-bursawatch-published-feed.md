# BursaWatch Published Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every eligible new, confirmed BursaWatch news and swing publication in the authenticated operator workspace, with per-owner coverage and no delivery replay.

**Architecture:** Domain owners keep their durable publication and delivery state. A new Control Plane publication read model accepts owner-scoped, idempotent snapshots only after required Discord Delivery Owner receipts are confirmed. The web reads sanitized, cursor-paginated records and coverage through its existing authenticated proxy.

**Tech Stack:** Python 3, FastAPI, Pydantic, Psycopg/Postgres, existing owner state stores and `lib-bursawatch-control`, Next.js/TypeScript/Zod, Supabase user JWT.

**Spec:** `docs/superpowers/specs/2026-09-29-bursawatch-published-feed-design.md`

## Global Constraints

- Use Node 24 for both web packages; run `npm ci` in each package before its first web test/check command in a fresh worktree.

- Feed scope is all eligible publications whose required delivery is confirmed after one recorded forward-only cutover boundary, from Telegram Market News, Stockbit Snips, X, Instagram, WhatsApp, Phintraco Swing, Kelas Investasi GTW, and Discord Swing Board. Source publication time does not decide eligibility. There is no historical backfill.
- Integrate the operator-workspace plan first, reserving `019_operator_inventory.sql`; this plan uses `020_publications.sql` and adds Published to the same navigation. Resolve branch overlap before implementing its web task.
- A publication becomes visible only after every required delivery leg is confirmed by the Discord Delivery Owner. A Control Plane projection retry must never create a Discord operation.
- Distinguish `broker_swing_plan`, `swing_context`, `swing_bundle`, `swing_board_update`, `stock_status`, IDX and US company news, industry news, and macro news. Retain the validated route and source attribution.
- Owner machine writes are scoped to their own namespace. Human viewer/admin JWTs may read but cannot write publications. The web never receives machine credentials, raw source payloads, or private media bytes.
- Preserve current source cursors, existing owner state, delivery destinations, schedules, and paused jobs. Production deployment and cutover need their existing separate approvals. No synthetic production posts or manual cron runs.
- Read each affected package's `AGENTS.md` and root `CRON.md` or `SKILL.md` before editing it. Update those contracts and OpenAPI in the same change. Run focused package tests, then `bash scripts/test-all` and both web package checks before handoff.

## Review Focus

1. A receipt confirmed just before a crash must yield one projection intent on recovery and no second Discord post. Tasks 4 to 11 test this at each owner boundary.
2. A multi-leg act with one pending or failed leg must not appear as published. Tasks 1 and 4 to 11 test the required-leg rule.
3. A same-key retry must be idempotent, while a changed digest or version conflict must fail without replacing accepted content. Tasks 1 and 2 test both paths.
4. A paused or silent owner with a stale checkpoint must display `unknown` coverage, never a complete empty feed. Tasks 3 and 13 test this.
5. A cursor or filter change must neither skip nor duplicate results with identical delivery timestamps. Tasks 2 and 13 test stable ordering.

---

## File map and delivery order

`service-bursawatch-control/bin/control_plane/publication_model.py` owns validation, public types, safe URL and text bounds, and canonical digest. `publication_store.py` owns in-memory/Postgres persistence, cutover, checkpoints, and cursor queries; migration `020_publications.sql` adds only separate read-model tables after the operator-workspace plan's reserved `019_operator_inventory.sql`. `api.py` exposes explicit routes and `auth.py` adds owner-scoped credentials. `lib-bursawatch-control/bin/publication_client.py` is the common bounded machine client; each domain owner persists its own projection intent and exact confirmed output snapshot. `web-config/src/lib/publications.ts` validates browser-visible records, `src/server/control-plane.ts` fetches them, `src/server/control-route.ts` allowlists GETs, and `src/components/published-*` renders the page. Do not put publication state in run events or the Discord Delivery Owner.

The backend read contract lands before owner writers. Owner writers may be deployed before the explicit cutover with projection disabled. The web can then display an empty forward-only state, and coverage becomes complete only as each required owner reports a successful checkpoint. The operator-workspace plan updates shared navigation separately, so the Published page must coexist with its eventual Jobs page.

## Fast execution path

Implement this plan in the same managed integration branch as the operator-workspace plan, after its migration `019` and shared component/job API shapes are fixed. The task numbers below are a coverage checklist, not 14 serial agent handoffs or deployments. The primary implementer owns Control Plane, shared client, API security, and final integration; any subagents work in isolated package scopes and use GPT-6 Luna as requested.

1. **Freeze the shared contract:** Complete Tasks 1 to 4 first. One record schema, receipt rule, idempotent store, owner credential contract, cutover/checkpoint model, and projection client support all eight owners. Run focused Control Plane and library tests. Do not start owner edits until the record and client interfaces are stable.
2. **Integrate owners in parallel:** Split Tasks 5 to 12 into three independent package groups: Telegram Market News, Stockbit, X; Instagram, WhatsApp; Phintraco, Kelas, Swing Board. Each group adds durable receipt-bound projection intents and checkpoints only within its packages. Use separate managed worktrees or nonoverlapping file scopes, merge each group into the integration branch, and have the primary implementer review receipt recovery, no repost, exact output, and checkpoint behavior. Do not ask for a separate human decision between owners.
3. **Finish the operator experience:** Complete Task 13 against the final API and the operator plan's navigation. Complete Task 14 after all owner groups land. Run focused tests during each group, each affected owner package suite once when its group stabilizes, then one `bash scripts/test-all` and one check per web package after integration. Rerun only suites affected by fixes.

The per-task commit steps preserve rollback points without creating a review gate per commit. Keep all eight owners, every approved publication type, multi-leg receipt proof, authorization, forward-only eligibility, coverage checkpoints, and exact delivered snapshots. Production activation and deployment remain separate reviewed gates; faster implementation never substitutes a replay or test post for natural delivery evidence.

### Task 1: Validated record and durable read model

**Focused command:** `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_publication_model.py tests/test_publication_store.py tests/test_migrations.py`

**Files:** Create `service-bursawatch-control/bin/control_plane/publication_model.py`, `publication_store.py`, `service-bursawatch-control/migrations/020_publications.sql`, `service-bursawatch-control/tests/test_publication_model.py`, `tests/test_publication_store.py`; modify `tests/test_migrations.py`.

**Interfaces:** `validate_publication(payload: object, owner_id: str) -> dict[str, Any]` returns a sanitized v1 snapshot containing type, validated route, source identity/key and safe URL, bounded title, nullable source time and market-data as-of time, delivery-confirmation time, config/renderer/schema versions, optional parent/Board link, and exact required delivery legs with receipt identity, destination, rendered text, and safe attachment metadata. Broker levels are present only for validated Phintraco plans. The public `publication_id` is a globally unique opaque ID derived from owner ID plus owner-local act key, so `GET /v1/publications/{publication_id}` is unambiguous. `publication_store.py` defines `PublicationConflict`, `MemoryPublicationStore`, and `PostgresPublicationStore`; both stores implement `accept(owner_id: str, snapshot: dict[str, Any]) -> dict[str, Any]`, inserting one immutable `(owner_id, publication_id, version)` or returning the same acknowledgment. `activate(boundary: str, owner_ids: tuple[str, ...]) -> None` records one immutable cutover; Postgres uses the existing process-local pool.

- [ ] Write failing `test_partial_leg_is_not_published` (`assert accept(partial) raises ValueError`), `test_same_key_same_digest_is_idempotent` (`assert accept(twice) == first_ack`), and `test_same_key_changed_digest_conflicts` (`assert accept(changed) raises PublicationConflict`); cover all public types and routes, broker-only levels, distinct nullable times, unsafe URLs/text/media, and pre-cutover delivery time.
- [ ] Run `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_publication_model.py tests/test_publication_store.py`; expect failure for missing model/store.
- [ ] Implement the model and store. Give migration `020_publications.sql` the required `-- bursawatch-release: automatic` first line, immutable unique keys and indexes, and separate cutover/checkpoint tables. Do not modify old inbox/run tables.
- [ ] Run the focused tests and migration tests; expect pass.
- [ ] Commit the model, migration, and tests.

### Task 2: Owner authorization and paginated publication API

**Focused command:** `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_publication_api.py tests/test_auth.py`

**Files:** Modify `service-bursawatch-control/bin/control_plane/auth.py`, `api.py`, `openapi/control-plane.v1.yaml`, `env.example`, `tests/test_auth.py`, `tests/test_api.py`; create `tests/test_publication_api.py`.

**Interfaces:** `CONTROL_PLANE_PUBLICATION_OWNER_TOKENS` is a private owner-ID-to-token map; `Principal(kind="publication_owner", subject=<owner_id>)` comes only from a distinct configured owner token. `POST /v1/publications` derives `owner_id` from that principal. `GET /v1/publications` accepts bounded `limit`, opaque `cursor`, and type/route/date/source/ticker filters; `GET /v1/publications/{publication_id}` returns versions and links. Read queries order by `(delivery_confirmed_at, publication_id, version)` descending, with filters applied before cursor advance.

- [ ] Write failing `test_owner_cannot_claim_other_namespace` (`assert status_code == 403`), `test_viewer_cannot_submit` (`assert status_code == 403`), and `test_cursor_keeps_tied_timestamps` (`assert page1_ids + page2_ids == expected_ids`); cover reader roles, version conflict, malformed evidence, query bounds, filters, and safe errors.
- [ ] Run the new API tests; expect missing routes and auth failure.
- [ ] Add owner token parsing with duplicate-token rejection, wire the publication store into `create_app` using the existing pool, implement the three routes, and update OpenAPI with exact schemas and response codes. Keep `/api/control` out of the machine submission path.
- [ ] Run focused auth/API tests and `tests/test_postgres_pool_integration.py`; expect pass.
- [ ] Commit the API, auth, contract, and tests.

### Task 3: Cutover and coverage checkpoints

**Focused command:** `cd service-bursawatch-control && uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests/test_publication_coverage.py tests/test_publication_activation.py`

**Files:** Modify `publication_store.py`, `api.py`, `openapi/control-plane.v1.yaml`; create `service-bursawatch-control/bin/activate_publication_feed.py`, `tests/test_publication_coverage.py`, `tests/test_publication_activation.py`.

**Interfaces:** The host-local activation CLI accepts one explicit aware boundary and fixed in-scope owner set, refuses second activation, and prints no credentials. `POST /v1/publications/checkpoints` accepts only the caller owner's bounded comparison time, confirmed boundary, accepted boundary, and outstanding count. `GET /v1/publications/coverage` returns cutover plus per-owner `complete`, `lagging`, `unknown`, or `paused/unverified` with timestamps; a missing or stale checkpoint is `unknown`.

- [ ] Write failing `test_activation_is_immutable` (`assert second_activation raises Conflict`), `test_pre_cutover_delivery_rejected` (`assert status_code == 422`), and `test_stale_checkpoint_is_unknown` (`assert coverage[owner].status == "unknown"`); cover owner scope, outstanding count, and paused owners.
- [ ] Run the focused tests; expect failure for missing activation/coverage behavior.
- [ ] Implement the CLI and endpoints. Persist checkpoints separately from publications; never infer complete coverage from a zero-row list or successful scheduler run.
- [ ] Run focused tests and migration rehearsal tests; expect pass.
- [ ] Commit the cutover and coverage contract.

### Task 4: Shared projection client and owner integration contract

**Focused command:** `cd lib-bursawatch-control && ../../../.venv/bin/python -m pytest -q tests/test_publication_client.py`

**Files:** Create `lib-bursawatch-control/bin/publication_client.py`, `lib-bursawatch-control/tests/test_publication_client.py`; modify `lib-bursawatch-control/README.md`, `service-bursawatch-control/openapi/control-plane.v1.yaml` if contract corrections are needed.

**Interfaces:** `PublicationClient.submit(snapshot: Mapping[str, Any]) -> dict[str, Any]` retries only the same publication key and digest, with bounded timeouts; `checkpoint(comparison: Mapping[str, Any]) -> dict[str, Any]` reports one owner ledger comparison. The caller supplies a scoped owner credential through its existing private runtime environment. Each owner must persist the exact rendered snapshot and pending projection status at its confirmed-receipt boundary, retain it until acknowledged, and advance a durable contiguous accepted boundary. The client cannot call the Discord Delivery Owner.

- [ ] Write failing `test_timeout_retries_same_identity` (`assert second_request.body == first_request.body`), `test_conflict_is_not_retried` (`assert request_count == 1`), and `test_error_redacts_token` (`assert token not in str(error)`); cover malformed acknowledgment and no Discord transport dependency.
- [ ] Run the focused library command; expect failure for the missing client.
- [ ] Implement the narrow HTTP client and document the owner persistence protocol. Do not create a generic cross-owner state file or derive an intent from a run summary.
- [ ] Run the library suite; expect pass.
- [ ] Commit the client and tests.

### Task 5: Telegram Market News and stock-status publications

**Focused command:** `cd cron-tg-market-news && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-tg-market-news/bin/delivery_handoff.py`, `bin/state.py`, `bin/scan.py`, `bin/pipeline_owner.py`, `AGENTS.md`, `SKILL.md`; create `cron-tg-market-news/tests/test_publication_projection.py`.

**Interfaces:** The owner stores one pending publication snapshot for each confirmed news or grouped stock-status act, with stable owner key, route, exact rendered legs and receipts. It drains projection pending independently of Discord delivery and checkpoints its contiguous accepted boundary. Company, industry, macro news, and `stock_status` retain distinct public types.

- [ ] Write failing `test_confirmed_stock_status_creates_one_intent` (`assert pending_count == 1`), `test_missing_leg_creates_none` (`assert pending_count == 0`), and `test_projection_outage_does_not_repost` (`assert discord_operation_count == 1`); cover news route, crash recovery, and checkpoint advance.
- [ ] Run the focused Telegram command; expect failure for absent projection behavior.
- [ ] Add the receipt-boundary intent and retry drain without changing parser, destination, source cursor, or Discord operation key. Update package contracts.
- [ ] Run the focused and full package suite; expect pass.
- [ ] Commit this owner.

### Task 6: Stockbit news publications

**Focused command:** `cd cron-stockbit-snips && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-stockbit-snips/bin/delivery_handoff.py`, `bin/state.py`, `bin/scan.py`, `bin/pipeline_owner.py`, `AGENTS.md`, `SKILL.md`; create `cron-stockbit-snips/tests/test_publication_projection.py`.

**Interfaces:** Stockbit reports confirmed `idx_company_news` and `macro_news` through its existing fixed feed routes, retaining the source article identity and exact output. A paused feed or excluded article produces no publication. Accepted records advance its own contiguous checkpoint.

- [ ] Write failing `test_paused_or_excluded_article_has_no_publication` (`assert pending_count == 0`) and `test_confirmed_stockbit_article_retries_projection_only` (`assert discord_operation_count == 1`); cover both news routes, incomplete leg, receipt recovery, and checkpoint.
- [ ] Run focused Stockbit state, delivery, and owner tests; expect failure for missing projection.
- [ ] Persist and retry the owner projection at the confirmed-receipt boundary, preserving feed cursors and frozen config.
- [ ] Run the Stockbit suite; expect pass.
- [ ] Commit this owner.

### Task 7: X publications and swing context

**Focused command:** `cd cron-x-account-watch && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-x-account-watch/bin/delivery_handoff.py`, `bin/state.py`, `bin/scan.py`, `bin/pipeline_owner.py`, `AGENTS.md`, `SKILL.md`; create `cron-x-account-watch/tests/test_publication_projection.py`.

**Interfaces:** X route decisions produce distinct IDX news, US news, macro news, and `swing_context` types. Thread edits create explicit later versions only after the edit receipt confirms. Existing pruning cannot discard a projection-pending record or the contiguous checkpoint boundary.

- [ ] Write failing `test_swing_route_is_context` (`assert publication.type == "swing_context"`), `test_confirmed_edit_adds_version` (`assert versions == [1, 2]`), and `test_pruning_keeps_pending_projection` (`assert pending_count == 1`); cover IDX/US news, quote/thread output, crash recovery, and no repost.
- [ ] Run focused X delivery/state/owner tests; expect missing projection failures.
- [ ] Add durable pending intents and version links at the receipt boundary, with exact rendered text and safe attachment metadata.
- [ ] Run the X suite; expect pass.
- [ ] Commit this owner.

### Task 8: Instagram publications

**Focused command:** `cd cron-ig-account-watch && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-ig-account-watch/bin/delivery_handoff.py`, `bin/state.py`, `bin/scan.py`, `bin/pipeline_owner.py`, `AGENTS.md`, `SKILL.md`; create `cron-ig-account-watch/tests/test_publication_projection.py`.

**Interfaces:** Instagram reports only confirmed news routes, preserves post identity and public source link, and retains pending projection and checkpoint through delivery pruning. Its currently unscheduled source adapter does not become an active schedule through this change.

- [ ] Write failing `test_irrelevant_instagram_post_has_no_publication` (`assert pending_count == 0`) and `test_media_leg_pending_is_not_visible` (`assert pending_count == 0`); cover confirmed news, pruning/recovery, API outage, and no active-schedule claim.
- [ ] Run focused Instagram delivery/state/owner tests; expect missing projection failures.
- [ ] Persist the exact confirmed output and drain it independently of Discord delivery.
- [ ] Run the Instagram suite; expect pass.
- [ ] Commit this owner.

### Task 9: WhatsApp news and swing-context publications

**Focused command:** `cd cron-wa-channel-watch && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-wa-channel-watch/bin/delivery_handoff.py`, `bin/state.py`, `bin/scan.py`, `bin/discord.py`, `bin/pipeline_owner.py`, `AGENTS.md`, `SKILL.md`; create `cron-wa-channel-watch/tests/test_publication_projection.py`.

**Interfaces:** WhatsApp route decisions retain IDX company, industry, macro, and `swing_context` labels. Observe mode and nonforwarded candidates produce no publication. Existing bridge cursor and route settings remain untouched; accepted records advance the owner checkpoint.

- [ ] Write failing `test_observe_mode_has_no_publication` (`assert pending_count == 0`) and `test_whatsapp_swing_is_context` (`assert publication.type == "swing_context"`); cover news routes, pending media, receipt recovery, API outage, and no resend.
- [ ] Run focused WhatsApp delivery/queue/owner tests; expect missing projection failures.
- [ ] Add owner-scoped projection intent and drain at confirmed delivery, without modifying source bridge or destination semantics.
- [ ] Run the WhatsApp Python and JavaScript sink suites; expect pass.
- [ ] Commit this owner.

### Task 10: Phintraco broker plans and source updates

**Focused command:** `cd cron-tg-phintraco-swing && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-tg-phintraco-swing/bin/delivery_handoff.py`, `bin/scan.py`, `bin/pipeline_owner.py`, `AGENTS.md`, `CRON.md`; create `cron-tg-phintraco-swing/tests/test_publication_projection.py`.

**Interfaces:** Only a validated complete Phintraco setup becomes `broker_swing_plan`; published corrections or source updates link to the original publication. Preserve entry, stop, target, units, attribution, and Board episode link when present. An unmatched update must not be invented as a complete plan. Its receipt-backed ledger advances a contiguous checkpoint.

- [ ] Write failing `test_complete_setup_is_broker_plan` (`assert publication.type == "broker_swing_plan"`), `test_partial_chart_leg_is_not_published` (`assert pending_count == 0`), and `test_crash_after_intent_does_not_repost` (`assert discord_operation_count == 1`); cover update linkage and projection outage.
- [ ] Run focused Phintraco delivery/owner/weekly PDF tests; expect missing projection failures.
- [ ] Persist confirmed snapshots before effect acknowledgment, then submit/retry separately; reuse stable Discord keys on recovery.
- [ ] Run the Phintraco suite; expect pass.
- [ ] Commit this owner.

### Task 11: Kelas swing bundles

**Focused command:** `cd cron-tg-kelas-investasi-gtw && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-tg-kelas-investasi-gtw/bin/delivery_handoff.py`, `bin/state.py`, `bin/discord.py`, `bin/pipeline_owner.py`, `AGENTS.md`, `SKILL.md`; create `cron-tg-kelas-investasi-gtw/tests/test_publication_projection.py`.

**Interfaces:** Kelas emits `swing_bundle` using validated source fields only, with exact confirmed rendered legs, source attribution, and a durable contiguous checkpoint. It does not manufacture broker plan levels.

- [ ] Write failing `test_gtw_bundle_has_no_invented_broker_levels` (`assert publication.type == "swing_bundle" and publication.broker_levels is None`) and `test_gtw_api_outage_does_not_repost` (`assert discord_operation_count == 1`); cover missing fields, incomplete leg, and recovery.
- [ ] Run focused Kelas delivery/state/owner tests; expect missing projection failures.
- [ ] Persist owner projection intent at receipt acknowledgment and drain it separately, preserving the existing source and delivery rules.
- [ ] Run the Kelas suite; expect pass.
- [ ] Commit this owner.

### Task 12: Swing Board published actions

**Focused command:** `cd cron-dc-swing-board && ../../../.venv/bin/python -m pytest -q tests/test_publication_projection.py`

**Files:** Modify `cron-dc-swing-board/bin/engine.py`, `bin/store.py`, `bin/board.py`, `bin/delivery_handoff.py`, `AGENTS.md`, `CRON.md`; create `cron-dc-swing-board/tests/test_publication_projection.py`.

**Interfaces:** Board emits its own `swing_board_update` acts for confirmed starters, replies, and lifecycle changes, preserving episode and parent-publication links. Its SQLite projection intent is transactional with completed outbox state; accepted records advance a contiguous Board checkpoint.

- [ ] Write failing `test_board_reply_links_parent` (`assert reply.parent_publication_id == starter.publication_id`) and `test_board_projection_failure_does_not_repost` (`assert discord_operation_count == 1`); cover starter, lifecycle, incomplete operation, and SQLite recovery.
- [ ] Run focused Board delivery/store/engine tests; expect missing projection failures.
- [ ] Add transactional projection intents and a separate drain, preserving Board authority and fixed job schedules.
- [ ] Run the Board suite; expect pass.
- [ ] Commit this owner.

### Task 13: Published workspace read path and UI

**Focused command:** `cd web-config && npm test -- src/lib/publications.test.ts src/components/published-list.test.tsx src/components/published-detail.test.tsx src/server/control-route.test.ts`

**Files:** Create `web-config/src/lib/publications.ts`, `src/lib/publications.test.ts`, `src/components/published-list.tsx`, `src/components/published-list.test.tsx`, `src/components/published-detail.tsx`, `src/components/published-detail.test.tsx`; modify `src/server/control-plane.ts`, `src/server/control-route.ts`, `src/server/control-route.test.ts`, `src/components/workspace-app.tsx`, `src/components/workspace-navigation.tsx`, `src/app/workspace/[[...view]]/page.tsx`, `src/app/workspace.css`, `AGENTS.md`, `DESIGN.md`, `docs/CONTROL_PLANE.md`.

**Interfaces:** `publicationPage` and `publicationCoverage` Zod schemas reject malformed/private fields. The server reader adds `listPublications(filters, cursor)`, `getPublication(id)`, and `getPublicationCoverage()`; the same-origin proxy allowlists only their GET routes. `/workspace/published` renders forward-only, cursor-paginated News/Swing lists and a detail with exact delivered legs, source link, Board links, and coverage state.

- [ ] Write failing `published list keeps cursor ties` (`expect(allIds).toEqual(expectedIds)`), `stale checkpoint warns without complete claim` (`expect(coverage).toBe("unknown")`), and `proxy rejects publication POST` (`expect(status).toBe(404)`); cover no-store auth, malformed records, date/source/type/route/ticker filters, context versus plan, forward-only empty state, and safe detail links.
- [ ] Run `cd web-config && npm run check`; expect the new tests to fail before the reader and page exist.
- [ ] Implement validated API reads and UI. Keep existing Workflows and History purposes intact; coordinate final nav order with the operator-workspace plan and preserve mobile/keyboard access.
- [ ] Run `npm run check` in `web-config` and `web-landing`; expect pass.
- [ ] Commit the web read path and docs.

### Task 14: Coverage integration and release evidence

**Focused command:** `../../.venv/bin/python -m pytest -q tests/test_published_feed_contract.py`

**Files:** Create `tests/test_published_feed_contract.py`; modify `service-bursawatch-control/tests/test_publication_coverage.py`, `service-bursawatch-control/openapi/control-plane.v1.yaml`, `DEPLOYMENT.md`, `README.md`.

**Interfaces:** Each owner already has a receipt-backed checkpoint from Tasks 5 to 12. The workspace's all-publisher completeness claim requires every required owner checkpoint. The synthetic cross-package test exercises the published contract without a production read, write, or post.

- [ ] Write failing `test_all_publisher_coverage_requires_every_owner` (`assert coverage.complete is False` while one owner is lagging, paused, or unreported) and `test_api_outage_repair_uses_projection_only` (`assert discord_operation_count == 1`); use synthetic owner fixtures only.
- [ ] Run the focused coverage tests; expect failure until every owner supplies the checkpoint path.
- [ ] Document the activation sequence: additive schema, scoped credentials, all owner reporters staged and checked with projection disabled, explicit cutover record, web release, natural receipt and checkpoint verification. Keep actual production mutations in separate approved rollout work.
- [ ] Run all focused owner suites, `bash scripts/test-all`, `npm run check` in both web packages, and `python3 scripts/production_snapshot.py --production` before any current-production documentation claim; expect all local checks to pass and record the snapshot's stated limits.
- [ ] Commit final documentation and contract corrections.

## Execution handoff

This plan does not authorize deployment, service restart, scheduler change, destination change, production activation, replay, or test post. Keep each implementation task's branch reviewable and verify the exact owner receipt and read-model identity from a natural event only after a separately approved rollout. If a route has no natural publication during the verification window, report it as unverified.
