# X Swing Source Capability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a configurable X Swing Chart Context capability that preserves existing X output and sends eligible source-only events through the shared Swing Board owner.

**Architecture:** The Control Plane freezes compatible X capabilities and dispatch-group membership when it accepts a source event. One X-specific classifier evaluates the accepted thread once and selects one enabled route. The existing X owner delivers All first, then hands eligible Swing context to the existing Board owner, which applies the same episode rules used by Phintraco, Kelas Investasi, BRI Danareksa, and other sources.

**Tech Stack:** Python 3, FastAPI, PostgreSQL migrations, SQLite Board state, X source/media clients, shared Discord Delivery Owner and Source Media Owner clients, React/TypeScript, Vitest, pytest.

**Spec:** [2026-09-28 X Swing source capability design](../specs/2026-09-28-x-swing-source-capability-design.md)

## Current status, 2026-09-28

The X route-group, adapter, ordered multi-image, Board handoff, tests, and
package contracts are implemented in this worktree. This branch was based on
`d33f5828` and is being integrated with current `main`, which added Phintraco
weekly-plan linkage and Board schema version 11. The combined X Board storage
contract is schema version 12: v9-to-v10 adds lifecycle fields,
v10-to-v11 adds weekly-plan linkage, and v11-to-v12 adds ordered media paths.

The shared Board lifecycle runtime was released at
`d33f5828de11812d7def1ee9ceb5be85bb39cef8`; close/retry jobs and daily job
`f2b6c4f0995b` are registered. Its first production run happened on 2026-09-28
at 17:11 WIB. It resolved one stale episode, but its Discord edit and heartbeat
receipts were not yet applied back to the Board outbox, and the following tag
patch remained pending. Reconcile that durable work on a normal owner run and
confirm both Board outboxes are clear before any X cutover.

The new X source-ingest adapter remains unscheduled. The current X watcher and
queue remain authoritative, and no X source state or capability was changed.
The next production transition follows the repository's forward-only policy:
keep old state for rollback, start the new path at a fresh provider-head
boundary, and intentionally skip pre-boundary history instead of doing a full
state snapshot or cursor crosswalk.

## Global Constraints

- Classification remains X-specific. Do not move X relevance, route precedence, or thread interpretation into a shared universal router.
- For each X publication, assemble its accepted source thread once and run the existing X classifier once. It must not create one competing work item per matching X category.
- A valid Swing event is delivered to chronological `#id-stocks-swing` first. Submit one Board event only after All text and usable media legs have durable success or an explicit terminal-skip outcome.
- An X Board event is level 3 `Chart context` 🥉 with `plan: null`. X cannot change a structured plan, price state, target milestone, stop-loss state, lifecycle, tier policy, ticker route, or Discord forum topic.
- A failed strict Board gate is All-only and must not create a Board episode.
- Preserve the existing source-media and Discord delivery bounds: at most 16 media refs per event, 8 MiB per object, and 25 MiB aggregate.
- Use the same Board owner for all sources. There is one configured forum per ticker, at most one open episode per ticker, and one Discord thread per episode. Later episodes get new threads; resolved threads remain history.
- Board episode titles are generated as `TICKER - Ddd, DD Mon YYYY` from the first accepted source event's published timestamp converted to WIB, using fixed English three-letter weekday and month names. For example, `CPIN - Wed, 23 Sep 2026`. The weekday can be a weekend day. X cannot choose or change the title.
- The managed Discord forum channel stays persistent. Each ticker has one configured forum route and at most one open episode thread; every later episode gets a new thread and resolved history stays in place.
- Only complete Phintraco Primary plans receive after-close price reconciliation. Current closing position and furthest confirmed target are separate facts; closes update position, while the confirmed target milestone never regresses. X and other lower-tier sources cannot assert either fact.
- Keep the existing market tag labels exactly: `Below entry`, `Entry zone`, `Above entry`, `TP1 reached` through `TP6 reached`, and `Stop-loss breached`. `Resolved` replaces the source-tier tag; the reason stays in the card/history.
- Primary inactivity resets only on a new Phintraco BUY or material Phintraco progress/status. Source-only inactivity resets only on a qualifying new source event. Both resolve after 20 trading sessions inactive.
- `Resolved` replaces the source-tier tag. Stale and superseded closure removes the market-state tag; stop-loss and all-target terminal states retain their terminal market tag. Start native Discord archive after the resolved update and queued messages finish, then wait 48 quiet hours; no separate `Archived` tag is added.
- A first Phintraco BUY promotes an open level 2/3 source-only episode in its same thread and preserves the strongest prior starter as attributed history with first media. A distinct newer BUY during an open Primary episode supersedes it and starts a new thread; exact redelivery stays deduplicated.
- A level 2/3 event published before resolution but delivered late becomes dated history without reopening the episode. A qualifying level 2/3 event published after resolution may start a new source-only episode; a Phintraco status without a new BUY cannot start a Primary episode.
- Phintraco is level 1 `Primary plan` 🥇, Kelas Investasi is level 2 `Supporting setup` 🥈, and X, BRI Danareksa, and every other source are level 3 `Chart context` 🥉 unless a separately approved exception changes the catalog.
- The Delivery Owner is the only Bursawatch Discord REST path. The Source Media Owner is the only Supabase Storage path. The Control Plane stores validated media metadata and refs, not media bytes.
- The X adapter remains unscheduled until a separately approved cutover. Do not run a second X poller, reset cursors, replay history implicitly, change cadence, deploy, or send live messages as part of implementation.

## Review Focus

1. A supported but unset or disabled X capability must not produce that route. Pin it in `service-bursawatch-control/tests/test_source_catalog.py`, `web-config/src/lib/source-catalog.test.ts`, and `cron-x-account-watch/tests/test_pipeline_owner.py`.
2. Multiple enabled X capabilities must freeze into one durable route-group work item, and watcher retries/corrections must retain the exact full dispatch snapshot, including per-capability source metadata. Pin it in `service-bursawatch-control/tests/test_source_inbox.py` and `cron-x-account-watch/tests/test_pipeline_owner.py`.
3. IHSG or broad macro precedence, company news, US stock news, and Swing classification must keep their current outcomes. A route whose mapped capability is disabled must be durably suppressed, never relabeled into another enabled category. Pin it in `cron-x-account-watch/tests/test_agent_protocol.py` and `tests/test_scan.py`.
4. Multiple thread images must reach the LLM and All in source order, then reach the Board without a later cron tick; a retry must not replay successful All legs. Pin it in `cron-x-source-ingest/tests/test_adapter.py` and `cron-x-account-watch/tests/test_scan.py`.
5. X context must join the current shared ticker episode without changing an open Phintraco plan or its generated title; Phintraco promotion of a source-only episode must retain the strongest earlier source and its first media exactly once. Pin it in `cron-dc-swing-board/tests/test_engine.py`.

---

## File Map

| Path | Responsibility in this plan |
|---|---|
| `service-bursawatch-control/bin/control_plane/source_catalog.py` | Define X compatibility and publish dispatch-group metadata in effective snapshots. |
| `service-bursawatch-control/bin/control_plane/source_inbox.py` | Freeze enabled X capability membership into one durable work item and retain it across corrections. |
| `service-bursawatch-control/migrations/017_x_swing_route_groups.sql` | Add compatibility group metadata and a durable dispatch-context field without rewriting existing rows. |
| `service-bursawatch-control/openapi/control-plane.v1.yaml` | Document compatibility groups and claimed work context. |
| `service-bursawatch-control/tests/test_source_catalog.py`, `tests/test_source_inbox.py`, `tests/test_migrate.py` | Cover registry, defaults, grouping, correction, legacy independent fan-out, and migration inventory/release metadata. |
| `web-config/src/lib/source-catalog.ts`, `src/lib/source-catalog.test.ts` | Validate the additional compatibility metadata and test capability selection. |
| `web-config/src/components/source-catalog.test.tsx`, `scripts/control-workspace-smoke.mjs` | Verify the existing data-driven workflow editor exposes the compatible Swing capability and keep fixtures aligned. |
| `cron-x-source-ingest/bin/adapter.py`, `bin/runner.py` | Accept X route-group subscriptions and dispatch them through the existing X owner. |
| `cron-x-source-ingest/tests/test_adapter.py` | Verify compatibility, one accepted event, ordered media refs, and legacy pending-work handling. |
| `cron-x-account-watch/bin/pipeline_owner.py`, `bin/state.py`, `bin/scan.py` | Validate the frozen route set, run the existing classifier once, preserve accepted thread/media state, and deliver All before Board. |
| `cron-x-account-watch/bin/vision_media.py` and `tests/test_pipeline_owner.py`, `tests/test_agent_protocol.py`, `tests/test_state.py`, `tests/test_scan.py` | Keep all accepted thread images available to the LLM and verify route, ordering, retries, and Board handoff. `test_agent_protocol.py` remains a classifier regression suite; do not change classifier routing to implement capability gating. |
| `cron-dc-swing-board/bin/models.py`, `bin/store.py`, `bin/board.py`, `bin/engine.py` | Accept ordered local media paths compatibly, own each file durably, and render starter plus ordered attachment replies through the current episode engine. |
| `cron-dc-swing-board/tests/test_models.py`, `tests/test_store.py`, `tests/test_engine.py` | Verify legacy one-image events, schema migration compatibility, multi-image ordering, idempotency, and shared Phintraco/source-only episode rules. |
| `service-bursawatch-control/README.md`, `cron-x-source-ingest/CRON.md`, `cron-x-account-watch/SKILL.md`, `cron-dc-swing-board/CRON.md`, `docs/adr/0021-x-swing-board-handoff-and-media-queue.md` | Keep API, runtime, Board, media, ownership, retry, and rollout contracts aligned. |

## Task 1: Make X Swing selectable and freeze the exclusive route group

**Files:**
- Modify: `service-bursawatch-control/bin/control_plane/source_catalog.py`
- Create: `service-bursawatch-control/migrations/017_x_swing_route_groups.sql`
- Modify: `service-bursawatch-control/bin/control_plane/source_inbox.py`
- Modify: `service-bursawatch-control/openapi/control-plane.v1.yaml`
- Test: `service-bursawatch-control/tests/test_source_catalog.py`
- Test: `service-bursawatch-control/tests/test_source_inbox.py`
- Test: `service-bursawatch-control/tests/test_migrate.py`
- Modify: `web-config/src/lib/source-catalog.ts`
- Test: `web-config/src/lib/source-catalog.test.ts`
- Test: `web-config/src/components/source-catalog.test.tsx`
- Modify: `web-config/scripts/control-workspace-smoke.mjs`

**Interfaces:**
- A compatibility row is `{endpoint_id: str, capability_id: str, dispatch_group: str | None}`. X `company_news`, `macro_news`, and `swing_chart_context` rows use `dispatch_group: "x_post_route"`; unrelated source rows use `null`.
- An effective subscription carries the same `dispatch_group`, the existing `enabled` value, and the existing source/revision metadata. Compatibility alone never enables a subscription.
- New X group work uses `pipeline_id: "x_post_route"`, `capability_id: "x_post_route_group"`, `capability_version: 1`, `settings: {}`, and `dispatch_context: {"dispatch_group": "x_post_route", "subscriptions": [...]}`. Each subscription entry freezes `capability_id`, its capability version, empty settings, and its `config_source`. The work row's existing `catalog_revision` freezes the effective catalog revision. Keep the top-level `config_source` within its existing database enum by using endpoint-override precedence for the group and preserve each exact source in `dispatch_context`.
- Existing non-X subscriptions remain one work item per enabled capability. Existing `company_news` and `macro_news` rows already accepted before this change remain claimable during the compatibility drain.

- [x] **Step 1: Add failing catalog, inbox, and migration-inventory tests.** Assert every registered X endpoint supports all three X capabilities in the `x_post_route` group; a user-added X endpoint receives the same compatibility; unset settings remain disabled; and non-X compatibility remains independent. For a single accepted X envelope with all three capabilities enabled, assert one work item and a frozen subscription list. For an envelope with one enabled X capability, assert one work item containing only that capability. Assert non-X sibling subscriptions still create independent work. Update the exact migration inventory assertion to include migration 017 and verify its automatic release eligibility.

```python
def test_x_subscriptions_share_one_frozen_route_group(inbox, x_envelope):
    current = inbox.catalog.get()
    config = current["config"]
    config["endpoint_overrides"] = [
        {"endpoint_id": "x:writingtorch", "capability_id": capability,
         "enabled": True, "settings": {}}
        for capability in ("company_news", "macro_news", "swing_chart_context")
    ]
    inbox.catalog.put(current["revision"], config, "test")

    receipt = inbox.accept(x_envelope)
    work = inbox.claim(["x_post_route"], limit=10)

    assert len(receipt["work_keys"]) == 1
    assert len(work) == 1
    assert work[0]["capability_id"] == "x_post_route_group"
    assert [item["capability_id"] for item in work[0]["dispatch_context"]["subscriptions"]] == [
        "company_news", "macro_news", "swing_chart_context"
    ]
```

- [x] **Step 2: Run the focused tests and confirm the missing group metadata and duplicate work fail the assertions.**

Run from `service-bursawatch-control/`:

```bash
uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' \
  --with 'psycopg[binary,pool]>=3.2,<4' pytest -q \
  tests/test_source_catalog.py tests/test_source_inbox.py
```

Expected: the new tests fail because X compatibility has no group and Inbox creates one work item per capability.

- [x] **Step 3: Add the additive database migration and catalog metadata.** Start the new migration with the required `-- bursawatch-release: automatic` header because the changes are additive and preserve existing source settings. Add a nullable `dispatch_group` to compatibility and set it to `x_post_route` only for the three X capabilities on the ten registered X endpoints. Add `dispatch_context jsonb NOT NULL DEFAULT '{}'` to `bursawatch_source_work`; constrain stored values to JSON objects. Update the in-memory registry, `USER_PLATFORM_CAPABILITIES["x"]`, Postgres registry reader, and `effective_snapshot()` to expose the group. Do not seed enabled publisher defaults or endpoint overrides.

```sql
-- bursawatch-release: automatic
ALTER TABLE bursawatch_source_compatibility
    ADD COLUMN dispatch_group text,
    ADD CONSTRAINT source_compatibility_dispatch_group_check
        CHECK (dispatch_group IS NULL OR dispatch_group ~ '^[a-z][a-z0-9_]{0,63}$');

INSERT INTO bursawatch_source_compatibility (endpoint_id, capability_id)
SELECT endpoint_id, 'swing_chart_context'
FROM bursawatch_source_endpoints
WHERE platform = 'x';

UPDATE bursawatch_source_compatibility AS compatibility
SET dispatch_group = 'x_post_route'
FROM bursawatch_source_endpoints AS endpoint
WHERE endpoint.endpoint_id = compatibility.endpoint_id
  AND endpoint.platform = 'x'
  AND compatibility.capability_id IN ('company_news', 'macro_news', 'swing_chart_context');

ALTER TABLE bursawatch_source_work
    ADD COLUMN dispatch_context jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT source_work_dispatch_context_object_check
        CHECK (jsonb_typeof(dispatch_context) = 'object');
```

Keep the migration immutable after it is applied. For user-added X endpoints,
the in-memory `catalog_view()` must assign `x_post_route` to the three
compatible X capabilities too, because those endpoints are not present in the
SQL baseline migration.

- [x] **Step 4: Group only compatible enabled X subscriptions in `source_inbox._subscriptions()`.** Sort the frozen subscription entries by capability ID, derive one stable work key from `x_post_route_group`, and persist `dispatch_context` in both memory and Postgres stores. Keep `settings` empty. Copy `dispatch_context` from version 1 when `revise()` creates a correction or tombstone work record. Preserve old work rows and their current pipeline IDs.
- [x] **Step 5: Update the API schema and web validators.** Add nullable `dispatch_group` to compatibility and effective-subscription schemas. Keep the existing capability toggle UI data-driven, then add fixtures and component assertions showing X exposes `Swing Chart Context` and still defaults to off when there is no source setting. Do not introduce new endpoint defaults or enable sources during the UI change.
- [x] **Step 6: Run the full Control Plane suite and web checks, then commit this task.** From `service-bursawatch-control/`, run `uv run --with 'fastapi>=0.115,<1' --with 'httpx>=0.27,<1' --with 'psycopg[binary,pool]>=3.2,<4' pytest -q tests`. Then from `web-config/` run `mise exec -- npm ci`, `mise exec -- npm test -- src/lib/source-catalog.test.ts src/components/source-catalog.test.tsx`, and `mise exec -- npm run check`. Confirm the migration remains additive and existing unrelated source subscriptions remain unchanged.

```bash
git add service-bursawatch-control/bin/control_plane/source_catalog.py \
  service-bursawatch-control/bin/control_plane/source_inbox.py \
  service-bursawatch-control/migrations/017_x_swing_route_groups.sql \
  service-bursawatch-control/openapi/control-plane.v1.yaml \
  service-bursawatch-control/tests/test_source_catalog.py \
  service-bursawatch-control/tests/test_source_inbox.py \
  service-bursawatch-control/tests/test_migrate.py \
  web-config/src/lib/source-catalog.ts web-config/src/lib/source-catalog.test.ts \
  web-config/src/components/source-catalog.test.tsx \
  web-config/scripts/control-workspace-smoke.mjs
git commit -m "feat: define X Swing source capability group"
```

## Task 2: Dispatch one X event through the existing classifier

**Files:**
- Modify: `cron-x-source-ingest/bin/adapter.py`
- Modify: `cron-x-source-ingest/bin/runner.py`
- Modify: `cron-x-account-watch/bin/pipeline_owner.py`
- Modify: `cron-x-account-watch/bin/state.py`
- Modify: `cron-x-account-watch/bin/scan.py`
- Test: `cron-x-source-ingest/tests/test_adapter.py`
- Test: `cron-x-account-watch/tests/test_pipeline_owner.py`
- Test: `cron-x-account-watch/tests/test_agent_protocol.py`
- Test: `cron-x-account-watch/tests/test_state.py`
- Test: `cron-x-account-watch/tests/test_scan.py`

**Interfaces:**
- `adapter.ALLOWED` includes `swing_chart_context`; `endpoints()` continues binding verified endpoint IDs to reviewed publisher IDs and never infers publisher identity from a handle.
- `runner.process_pending()` claims `x_post_route` with the same handler used by the watcher owner. It also retains `company_news` and `macro_news` handler entries until a read-only status check proves previously accepted legacy work is drained.
- `pipeline_owner._identity()` validates the exact X group marker and the frozen `dispatch_context`; it accepts legacy work under the existing validation for pending compatibility work.
- The existing classifier still chooses exactly one route candidate from its current taxonomy. Add `capability_for_route(route_key: str) -> str | None` and `eligible_capability_for_route(route_key: str, enabled_capabilities: frozenset[str]) -> str | None` in `scan.py`. After normal and deterministic classification, forward only if the mapped capability is in the event's frozen capability set. If it is disabled or unmapped, durably mark the X event `suppressed_ineligible` and do not relabel it, send it to All, or send it to the Board.
- Capability mapping is fixed for this X classifier: `id_stocks_news` and `us_stocks_news` require `company_news`; `macro_news` requires `macro_news`; and `id_stocks_swing` requires `swing_chart_context`.
- Persist the complete canonical `dispatch_context` on each new grouped watcher event alongside `source_catalog_revision`. It includes the group marker and each sorted subscription's capability ID, capability version, settings, and `config_source`. On retry, duplicate claim, or correction, compare this full snapshot as well as the revision and event identity. Reject a changed source, setting, version, or capability even when the enabled ID set is unchanged. Legacy work without `dispatch_context` keeps its existing validation and state shape.

- [x] **Step 1: Add failing tests for capability filtering, full snapshot freeze, and legacy handling.** Verify one group work item creates one watcher event and one classifier input; multiple enabled capabilities do not call the classifier more than once; a correction keeps the exact full `dispatch_context`; and a retry with the same IDs/revision but a changed per-capability `config_source` is rejected. Also verify an `id_stocks_swing` candidate with Swing disabled is durably suppressed without an All or Board post and is not relabeled as company news; macro still wins when both macro and Swing are enabled; and old `company_news` or `macro_news` work can still be acknowledged during drain.

```python
@pytest.mark.parametrize(("route_key", "capability"), [
    ("id_stocks_news", "company_news"),
    ("us_stocks_news", "company_news"),
    ("macro_news", "macro_news"),
    ("id_stocks_swing", "swing_chart_context"),
])
def test_route_maps_to_its_source_capability(route_key, capability):
    assert capability_for_route(route_key) == capability


def test_disabled_swing_candidate_has_no_eligible_capability():
    enabled = frozenset({"company_news", "macro_news"})
    assert eligible_capability_for_route("id_stocks_swing", enabled) is None
```

The scan integration test also verifies that this result is durably recorded
as `suppressed_ineligible` and creates no All or Board delivery operations.

- [x] **Step 2: Run focused adapter, owner, and protocol tests to verify the current independent X work has no group filter.**

```bash
../../.venv/bin/python -m pytest -q cron-x-source-ingest/tests/test_adapter.py \
  cron-x-account-watch/tests/test_pipeline_owner.py \
  cron-x-account-watch/tests/test_agent_protocol.py
```

Expected: the new route-group tests fail while existing classifier-precedence tests continue to pass.

- [x] **Step 3: Add the group handler while keeping the legacy handlers.** Update adapter capability selection and `process_pending()` handler mapping. Validate the stable work/effect key and `dispatch_context` in `pipeline_owner.py`; persist its complete canonical snapshot and catalog revision with the accepted outbox event. Reject unknown capabilities, non-X endpoints, mismatched catalog snapshots, and any attempt to change the snapshot or add a capability after intake.
- [x] **Step 4: Gate the existing classifier result using frozen capabilities.** Add `capability_for_route()` with an exhaustive mapping for the four current X destination keys and `eligible_capability_for_route()` for the frozen capability check. Preserve the current LLM prompt, route taxonomy, deterministic precedence, and one-route result. Before creating any Discord outbox work, check that the candidate's mapped capability is in the frozen work context. Persist `suppressed_ineligible` for disabled or unmapped candidates, with no fallback route and no Board handoff.
- [x] **Step 5: Verify source identity and retry invariants.** Test that a handle whose profile ID differs still maps through the reviewed publisher binding, duplicate delivery stays idempotent, a correction retains the exact original dispatch snapshot, a same-ID/revision snapshot mutation is rejected, and old accepted work can finish without creating a second Discord delivery.
- [x] **Step 6: Run focused tests and commit this task.** From the worktree root, run `../../.venv/bin/python -m pytest -q cron-x-source-ingest/tests cron-x-account-watch/tests`, then commit the X adapter and account-watch files from this task.

```bash
git add cron-x-source-ingest/bin/adapter.py cron-x-source-ingest/bin/runner.py \
  cron-x-source-ingest/tests/test_adapter.py \
  cron-x-account-watch/bin/pipeline_owner.py \
  cron-x-account-watch/bin/state.py cron-x-account-watch/bin/scan.py \
  cron-x-account-watch/tests/test_pipeline_owner.py \
  cron-x-account-watch/tests/test_agent_protocol.py \
  cron-x-account-watch/tests/test_state.py cron-x-account-watch/tests/test_scan.py
git commit -m "feat: dispatch X Swing through the source owner"
```

## Task 3: Carry ordered thread images through Vision, All, and the shared Board

**Files:**
- Modify: `cron-x-source-ingest/bin/adapter.py`
- Modify: `cron-x-account-watch/bin/pipeline_owner.py`
- Modify: `cron-x-account-watch/bin/scan.py`
- Modify: `cron-x-account-watch/bin/vision_media.py` only if its current accepted-reference traversal drops a thread image
- Modify: `cron-x-account-watch/bin/agent_protocol.py`
- Test: `cron-x-account-watch/tests/test_agent_protocol.py`
- Modify: `cron-dc-swing-board/bin/models.py`
- Modify: `cron-dc-swing-board/bin/store.py`
- Modify: `cron-dc-swing-board/bin/board.py`
- Modify: `cron-dc-swing-board/bin/engine.py`
- Test: `cron-x-source-ingest/tests/test_adapter.py`
- Test: `cron-x-account-watch/tests/test_pipeline_owner.py`
- Test: `cron-x-account-watch/tests/test_scan.py`
- Test: `cron-dc-swing-board/tests/test_models.py`
- Test: `cron-dc-swing-board/tests/test_store.py`
- Test: `cron-dc-swing-board/tests/test_engine.py`

**Interfaces:**
- X source envelopes continue to carry the accepted `thread_posts` snapshot and durable ordered media refs. Include supported authored and quoted images in post order, with authored images before quoted images within each post, even when both are present. Accept up to 16 refs, 8 MiB per object, and 25 MiB aggregate. Preserve explicit blocked/terminal-skip outcomes for unsupported, unavailable, and failed media; never silently omit or reorder accepted refs.
- `SourceEvent.from_json()` keeps the existing required `media_path` and `media_urls` fields. It accepts optional `media_paths: list[str]` for a new ordered local-path list. When present, `media_paths[0]` equals the compatibility `media_path`; an absent list normalizes a legacy non-null `media_path` to a one-item ordered list. Reject duplicate paths, non-absolute paths, and lists over 16.
- `SourceEvent.media_paths` is the normalized ordered tuple. Persist it in additive SQLite column `source_events.media_paths_json`; old rows read as `()` or their existing single `media_path` without changing event identity.
- Bump the Board store from schema version 11 to 12 and add `_migrate_v11_to_v12()` to append `media_paths_json` with an empty-list default. Keep the existing v9 lifecycle migration and v10 setup-link migration in their original versions. When reading a legacy row, use `(media_path,)` if the old column is non-null and the new JSON list is empty. Preserve all existing event, episode, history, and outbox rows.
- Add `episode_title(ticker: str, opened_at: datetime) -> str` in the Board engine. It returns `TICKER - Ddd, DD Mon YYYY`, with fixed English three-letter weekday/month names and `opened_at` converted to WIB. New source-only and Primary episodes use it; promotion and later replies keep the episode's original title. The existing title-repair command recalculates only from stored ticker and opening time.
- The Board owner atomically copies every path into its private media directory with stable per-event and per-index names. The first available image attaches to the starter; remaining images become ordered media-only replies with stable operation keys. Existing `media_urls` behavior remains for legacy events.
- The same queued X event is drained through successful text and media legs in one worker invocation. Each leg keeps its receipt and nonce. Board submission waits for all text/media success or explicit terminal media skips; Board retries never repost successful All legs.
- Do not implement episode, resolution, price, or archive logic in the X watcher. Tests exercise these outcomes through the existing shared Board engine, which remains the owner of Phintraco and source-only lifecycle decisions.

- [x] **Step 1: Add failing adapter, owner, protocol, Board-model, and store-migration tests.** Assert two or more self-chain images, including authored and quoted images on the same post, produce one ordered durable ref per accepted image; owner validation resolves every ref exactly once; the complete 16-image Vision bundle passes agent payload serialization and validation while 17 is rejected; Vision, All, and Board retain images in authored-then-quoted order; and legacy one-image `SourceEvent` payloads still parse. Reject duplicate or over-bound path lists. Update schema-version and synthetic old-schema fixtures to prove the v11-to-v12 migration and legacy single-path fallback preserve existing data.

```python
def test_source_event_normalizes_legacy_and_ordered_media_paths(source_event_json):
    legacy_payload = {**source_event_json, "media_path": "/private/legacy.jpg"}
    legacy = SourceEvent.from_json(legacy_payload)
    assert legacy.media_paths == ("/private/legacy.jpg",)

    multi = SourceEvent.from_json({
        **source_event_json,
        "media_paths": ["/private/first.jpg", "/private/second.png"],
        "media_path": "/private/first.jpg",
    })
    assert multi.media_paths == ("/private/first.jpg", "/private/second.png")
```

The parser keeps the existing strict base keys and permits only the one new
optional field. `_EVENT_KEYS` remains the required set, so old callers do not
need to add `media_paths`:

```python
unknown = set(payload) - _EVENT_KEYS - {"media_paths"}
missing = _EVENT_KEYS - set(payload)
if unknown or missing:
    raise ValueError("source event fields are invalid")

media_paths = _parse_media_paths(payload.get("media_paths"), media_path)
```

`_parse_media_paths()` requires at most 16 unique absolute paths. If the field
is absent, it returns the legacy non-null `media_path` as a one-item tuple or
`()`. If present and non-empty, the first entry must equal `media_path`; an
explicit empty list is valid only when `media_path` is `None`.

- [x] **Step 2: Run focused tests and confirm the current one-image guard and Board event schema fail the new multi-image cases.**

```bash
../../.venv/bin/python -m pytest -q cron-x-source-ingest/tests/test_adapter.py \
  cron-x-account-watch/tests/test_pipeline_owner.py \
  cron-x-account-watch/tests/test_scan.py \
  cron-dc-swing-board/tests/test_models.py
```

- [x] **Step 3: Remove the X one-image rejection within current media bounds.** Keep per-image upload validation and aggregate checks. Preserve the event's thread post order and each post's authored/quoted image order, including quoted images when the same post also has authored images. Verify every ref is used by exactly one thread entry and no raw media URL or image bytes enter the Control Plane payload.
- [x] **Step 4: Preserve every accepted image for Vision, All, and Board delivery.** Resolve the source refs to private cached paths for Vision. Keep the protocol's serialization and submission-validation cap aligned at 16 with the acquisition cap. Build All delivery legs and Board `media_paths` in the same order by walking the accepted thread snapshot and resolving each non-skipped media ref, including quoted images when authored images are also present. Update the X delivery drain only if needed so it sends text then each usable image sequentially during the same invocation, saving a receipt after each leg. A transient Delivery Owner response keeps only the incomplete leg pending. A terminal media skip advances that leg and allows unrelated queued events to continue.
- [x] **Step 5: Add backwards-compatible Board storage, title generation, and operation rendering.** Extend `SourceEvent`, add `media_paths_json` through the Board's versioned SQLite migration, and make `_source_event_from_row()` read old rows. Update `_own_media()` to copy all paths safely and idempotently. Add `episode_title()` and use it for newly created source-only and Primary episodes, preserving the opening timestamp on promotion. Update `schedule_title_migration()` and its CLI preview so a repair derives the canonical dated title from the stored ticker/opening time. Extend starter and source-reply generation so the first image accompanies the starter and each later image is emitted in order with a stable dedupe key. Keep existing `media_path`, `media_urls`, text formatting, and one-image behavior intact.
- [x] **Step 6: Add behavior tests for retry and Phintraco interaction.** Assert the recorded fake Discord sequence is All text, every accepted authored and quoted image in order, then Board submission. Include one thread post with both authored and quoted media. Assert a Board retry does not replay any All operation. Assert a level 3 X event adds source context to an open Phintraco Primary episode without changing plan, close position, target milestone, tags, lifecycle, or generated title. Assert the generated title uses the first accepted event's published time in WIB, fixed English abbreviations, and stays fixed when later X context arrives, including a weekend date. Assert X starts a source-only episode when no episode is open, joins an open Kelas/source-only episode, and is promoted by a later Phintraco BUY in that same thread while retaining the strongest prior source starter and its first media exactly once.
- [x] **Step 7: Run watcher and Board suites, then commit this task.** Run each package in a separate pytest process from the worktree root to avoid collisions between unqualified test module names: `../../.venv/bin/python -m pytest -q cron-x-source-ingest/tests`, then the same command separately for `cron-x-account-watch/tests` and `cron-dc-swing-board/tests`.

```bash
git add cron-x-source-ingest/bin/adapter.py cron-x-source-ingest/tests/test_adapter.py \
  cron-x-account-watch/bin/pipeline_owner.py cron-x-account-watch/bin/scan.py \
  cron-x-account-watch/bin/vision_media.py cron-x-account-watch/bin/agent_protocol.py \
  cron-x-account-watch/tests/test_pipeline_owner.py cron-x-account-watch/tests/test_agent_protocol.py \
  cron-x-account-watch/tests/test_scan.py \
  cron-dc-swing-board/bin/models.py cron-dc-swing-board/bin/store.py \
  cron-dc-swing-board/bin/board.py cron-dc-swing-board/bin/engine.py \
  cron-dc-swing-board/tests/test_models.py cron-dc-swing-board/tests/test_store.py \
  cron-dc-swing-board/tests/test_engine.py
git commit -m "feat: preserve ordered X thread images on Swing Board"
```

## Task 4: Align contracts, verify integration, and prepare the separate cutover gate

**Files:**
- Modify: `service-bursawatch-control/README.md`
- Modify: `cron-x-source-ingest/AGENTS.md`
- Modify: `cron-x-source-ingest/CRON.md`
- Modify: `cron-x-account-watch/AGENTS.md`
- Modify: `cron-x-account-watch/SKILL.md`
- Modify: `cron-dc-swing-board/CRON.md`
- Modify: `cron-tg-kelas-investasi-gtw/tests/test_discord.py`
- Modify: `docs/adr/0021-x-swing-board-handoff-and-media-queue.md`
- Update related tests and fixtures in the packages above.

**Interfaces:**
- Documentation describes the X-specific `x_post_route` contract, supported but disabled-by-default `swing_chart_context`, frozen event capabilities, existing-route compatibility, media limits, LLM image coverage, same-invocation ordered delivery, Board handoff order, the Swing-only `omit_last` override, and explicit retry behavior.
- Documentation states that all sources use the existing Board owner and its Phintraco lifecycle rules: X is level 3 source context; one ticker has one configured forum and at most one open episode; source context never modifies a Primary plan; source-only promotion, supersession, late history, resolution, and archive remain Board-owned. Episode titles stay `TICKER - Ddd, DD Mon YYYY`, with fixed English abbreviations and the first accepted source timestamp in WIB, even when that date is Saturday or Sunday.
- Read-only rollout evidence records sanitized revisions, endpoint and publisher bindings, current X routes, counts of old queued work, registered Board routes/open episodes, pending Delivery Owner effects, package SHA, and health. Forward-only rollout does not require a complete state snapshot, cursor crosswalk, or history replay. Record the new poll's provider-head boundary and intentionally skipped old backlog without exposing credentials or source bodies.
- The approved shared Board design requires owner-driven 20-trading-session inactivity resolution and 48-hour quiet archival. Do not recreate this lifecycle in X. Verify the current Board schema and clear its pending durable outbox work before X cutover.

- [x] **Step 1: Update active package contracts and the accepted ADR.** Remove the obsolete statement that multi-image X Board work must remain unclaimed; update the X source-ingest route-group contract; and correct stale X watcher `AGENTS.md` media-order rules. Document the ordered multi-image path: all accepted images reach Vision; every accepted X Swing image reaches All and Board even when the profile uses `omit_last`; non-Swing routes retain that profile policy. Retain the approved 0021 ordering, strict gate, terminal-skip, and promotion decisions. Replace the old ticker-only forum-title wording with the current Board rule: generated `TICKER - Ddd, DD Mon YYYY` using fixed English abbreviations, fixed from the first accepted source timestamp converted to WIB. Update Control Plane and X package docs to distinguish capability compatibility from enabled state.
- [x] **Step 2: Add or extend fake-client integration coverage.** Extend `cron-x-source-ingest/tests/test_adapter.py` to assert the one route-group handoff is acknowledged once, and `cron-x-account-watch/tests/test_scan.py` to assert All text/media delivery precedes exactly one Board submission. Assert stable operation keys on retry and no live Discord/Storage client use. Update the Kelas integration expectation in `cron-tg-kelas-investasi-gtw/tests/test_discord.py` to use the approved generated episode title from the fixture's published timestamp.
- [x] **Step 3: Run the focused checks and complete suite.** Re-run the focused commands from Tasks 1 to 3, run `bash scripts/test-all` from the repository root, and run `git diff --check`. Do not poll or wait for GitHub CI. When its result is needed, inspect the completed run and act on its observed result.
- [x] **Step 4: Perform a read-only migration preflight after implementation is approved.** Read `GET /v1/source-catalog/effective` and `GET /v1/watchers/bursawatch-x-account-watch/config`. Match each configured profile ID and handle against the reviewed publisher binding in `REVIEWED_PUBLISHERS`; do not infer identity from a handle. Reconcile active legacy routes with the frozen capability set. Record counts for X cursor, pending source work, thread/media state, All outbox, Board routes/open episodes, and pending Delivery Owner effects. For forward-only cutover, do not require importing or proving legacy cursor history; record that pre-boundary backlog will be skipped. Verify the Board lifecycle schedule and clear its pending durable outbox work before switching writers.
- [x] **Step 5: Document the forward-only release and cutover gate.** Release the Control Plane migration/API, verify schema and health, release the Board v12 and approved X packages through the exact-main release process, and verify package parity plus the independent Vercel `web-config` deployment. At cutover, pause the old X poller and finish its in-flight run, then let already-accepted queue work drain before stopping that queue. Start the new reader with a fresh state root; its first successful poll establishes the latest provider ID as the boundary and delivers no earlier history. Record skipped backlog counts, retain old state unchanged, and process only new work after that boundary. Keep the current reader authoritative until a separately approved cutover. A separate approval is required before enabling capabilities, pausing live jobs, changing schedules, deploying X packages, or sending a production X message.
- [x] **Step 6: Commit this task after the documentation, fake-client test, and release checklist agree with the implementation.** Preserve the feature worktree and branch for review; do not create a pull request, merge, deploy, or clean up the worktree unless separately requested.

```bash
git add service-bursawatch-control/README.md \
  cron-x-source-ingest/AGENTS.md cron-x-source-ingest/CRON.md \
  cron-x-account-watch/AGENTS.md \
  cron-x-account-watch/SKILL.md \
  cron-dc-swing-board/CRON.md \
  cron-tg-kelas-investasi-gtw/tests/test_discord.py \
  docs/adr/0021-x-swing-board-handoff-and-media-queue.md \
  cron-x-source-ingest/tests/test_adapter.py cron-x-account-watch/tests/test_scan.py
git commit -m "docs: align X Swing rollout and Board contracts"
```

## Completion Checklist

- [x] Control Plane returns `swing_chart_context` compatibility for verified X endpoints with explicit off-by-default effective state and revision.
- [x] One accepted X publication creates one route-group work item regardless of how many matching X capabilities are enabled; retries and corrections retain and validate the full frozen dispatch context and revision.
- [x] The existing X classifier runs once and still applies current route precedence and destinations.
- [x] Eligible X Swing output reaches All before the shared Board; rejected strict-gate events remain All-only.
- [x] Every accepted thread image reaches Vision; every accepted X Swing image reaches ordered All delivery and Board replies, regardless of `omit_last`; non-Swing routes preserve `omit_last`. The Board attaches the first image to its starter with later images in ordered replies.
- [x] Board retries do not duplicate successful All output, Board replies, or source images.
- [x] X obeys the shared Phintraco/level-2/level-3 episode rules, and cannot mutate a Phintraco plan or lifecycle.
- [x] Existing data remains readable after both Postgres and SQLite migrations; legacy X work remains drainable.
- [ ] The Board lifecycle prerequisite is complete: the first run is verified, but reconcile its delivered edit/heartbeat receipts and pending tag patch on a normal owner run, then confirm both Board outboxes are clear.
- [ ] The X branch is integrated with current `main`; SQLite migrations remain ordered as v9-to-v10 lifecycle, v10-to-v11 weekly setup link, and v11-to-v12 ordered media paths.
- [x] Package docs, API schema, tests, and rollout checklist describe the same contract.
- [x] The new X adapter remains unscheduled. No X capability was enabled, old X writer was paused, X state was imported or replayed, or X production message was sent. The separate Board lifecycle scheduler was registered as an approved prerequisite.

## Read-only cutover preflight, 2026-09-28

- The live Control Plane catalog is revision 3 and the X watcher config is
  revision 8. All 10 configured X profile IDs match their reviewed publisher
  bindings. The legacy watcher has all 10 profiles enabled; three profiles
  still use the legacy `id_stocks_swing` route.
- The live Source Catalog exposes only the existing X `company_news` and
  `macro_news` capabilities, both disabled in that catalog. The
  `swing_chart_context` compatibility and `x_post_route` dispatch group from
  migration 017 are not live yet. These catalog settings do not disable the
  separate legacy watcher config.
- The source-polling and queue jobs remain active at their existing 10-minute
  and 1-minute cadence. The new source-ingest adapter has no scheduled job.
- X state is version 3 with 12 retained profile namespaces and 11 cursors. Two
  namespaces, `dafandikri` and `idnfinancials`, are not in the current
  10-profile config; retain them as state history. One legacy `macro_news`
  outbox row drained naturally during the read-only checks. The current X
  outbox is now empty. No state was edited or replayed.
- The Board database had 69 episodes, 24 open episodes, and 567 outbox rows,
  all complete at the time of the initial check. The Delivery Owner health
  check reported zero pending, blocked, or ambiguous operations.
- Board runtime checksums matched the published main source. The existing close
  and retry jobs are active at 16:30 and 17:00 WIB on weekdays. Lifecycle job
  `f2b6c4f0995b` is active at 17:10 WIB daily. The live Board database reported
  schema version 9 at this original preflight; see the later follow-up below.
- No X catalog change, source-schedule change, state handoff, replay, or
  production X message was performed.

## Read-only lifecycle follow-up, 2026-09-28 21:53 WIB

- The live Board SQLite database reports schema version 10 and has the lifecycle
  fields. Current `main` has schema version 11, and the integrated X Board code
  uses schema version 12 to preserve both main's Phintraco setup-link migration
  and X's ordered-media migration.
- The first daily lifecycle run completed at 17:11 WIB with
  `resolved=1`, `quiet=44`, `archive=0`, and `pending=2`. It emitted a degraded
  heartbeat because durable work remained.
- The Delivery Owner is healthy. Its ledger shows the resolved-card edit and
  lifecycle heartbeat as delivered, but Board has not applied those receipts
  locally. The dependent forum-tag patch is still pending and has not reached
  the Delivery Owner. The next ordinary Board drain should reconcile the two
  delivered receipts and submit the patch. Do not run a manual retry or X
  cutover while this is unresolved.
- No Board message, cursor, schedule, catalog setting, or X state was changed
  during this inspection.
