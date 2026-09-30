# Bursawatch source catalog transition recovery design

**Date:** 2026-09-30

**Status:** Design and implementation plan approved by the user on 2026-09-30; implementation underway

**Owner:** Bursawatch Telegram and Stockbit source ingestion packages

## Approval and operational authorization

The user approved this written design on 2026-09-30 and authorized implementation
and the production steps in this workstream, including temporarily pausing and
resuming the existing Telegram and Stockbit jobs, applying the package-owned
catalog transitions, and deploying eligible source-ingest code. Use the
repository's supported scheduler and release paths, and refresh production
evidence before acting. This authorization does not waive the exact-main-SHA CI
and release-agent gates, permit a cadence or destination change, or permit a
manual job run, replay, backfill, cursor reset, or test post.
Implementation begins after the user reviews the implementation plan and
selects an execution approach; this review does not request a new production
authorization.

## Goal

Restore future-only polling for the active Telegram and Stockbit readers after the global Source Catalog advances, when the source-owned configuration has not changed. Each package must prove that its existing source state remains compatible with the new catalog revision. Cursor positions, legacy seed provenance, validators, accepted owner work, and delivery state must remain intact.

This design covers the first repair workstream only. Phintas `trading_plans` routing, WhatsApp archive capture, X/RSSHub feed coverage, and any Telegram runner-order change are separate workstreams.

## Evidence basis

- A read-only catalog history comparison at 20:32 WIB on 2026-09-30 found the same seven enabled and verified Telegram endpoint-capability rows at revisions 5, 6, and 7, the same four enabled and verified Stockbit RSS rows, and an empty `selected_securities` list. Catalog hashes differed because configuration outside those source projections changed.
- A follow-up read-only comparison completed at 21:10 WIB found the four enabled, verified Stockbit RSS rows and empty `selected_securities` unchanged across revisions 4 and 5. The enabled Telegram projection was also unchanged across that edge. The RSS cutover receipt and all four lane seed records identify revision 4 as the immutable origin. This supports the proposed adjacent RSS path but does not replace refreshing history and state before a production transition.
- The read-only production snapshot at 21:19 WIB again found 13 Hermes jobs, eight active and five paused, with all eight desired interval schedules matching the live registry. Telegram source ingest and Stockbit RSS were active. The release agent was blocked and its CI state was pending for the then-current `origin/main`; recheck before rollout. The snapshot does not verify runtime checksums or prove a natural source-to-delivery event.
- At the same read-only check, the Telegram source-state marker was revision 5 and the RSS source-state marker was revision 4, while the effective Source Catalog was revision 7. These marker observations are time bounded and must be refreshed before any production transition.
- The read-only production snapshot at 20:57 WIB reported 13 Hermes jobs, eight active and five paused, with all eight desired interval schedules matching the live registry. Telegram source ingest and Stockbit RSS were active. A matching schedule and `last=ok` do not prove that a source was polled or an event delivered.
- The [incident audit](../../incident-reviews/2026-09-30-platform-ingestion-audit.md) contains the broader source findings and their evidence limits.

## Domain terms

| Term | Meaning |
| --- | --- |
| Effective Source Catalog revision | The global, versioned Control Plane snapshot used by source readers. |
| Reader revision marker | `catalog-revision.json` in one source reader's state root. It records the latest catalog revision that reader has accepted through its package-owned compatibility process. |
| Legacy seed origin revision | The catalog revision recorded when an existing cursor boundary was first seeded. It is provenance for the cursor boundary and does not change when the reader later proves compatibility with another revision. |
| Compatible transition journal | A private, durable record for one adjacent revision edge. It binds the reviewed catalog snapshots, the source-owned projection, and the state fingerprint used for apply. |
| Source-owned projection | The complete set of catalog rows and fields that one adapter uses to select and configure its endpoints. |

The global catalog revision and a reader's marker are related but distinct. The marker may advance only through a completed package-owned transition. A legacy seed origin remains fixed so the reader can preserve how its cursor boundary was established.

## Chosen approach

1. Keep Telegram's existing package-owned compatible transition command. Apply revision 5 to 6, then revision 6 to 7, one edge at a time. Its existing projection checks are sufficient for the observed unchanged Telegram rows and selected securities. No Telegram code change is in scope.
2. Add a package-owned compatible transition to the RSS source package. The RSS runner must validate a complete chain from each cursor's immutable seed origin through the current reader marker before polling.
3. Reuse the shared low-level source-state planner for state fingerprints and resumable journals. Add a caller-specified apply-guard environment variable while preserving the existing default for Telegram seed transitions. The RSS command uses `BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY=1`.

A shared coordinator that interprets both package projections would couple independent source owners. Rebuilding all RSS cursors from fresh feed pages would introduce unnecessary cursor-boundary risk while the Stockbit projection is unchanged. The package-owned RSS wrapper keeps the validation with the owner and reuses only the generic state transaction.

## Implementation touchpoints

- Add `cron-rss-source-ingest/bin/compatible_catalog_transition.py` for the RSS-owned preview and apply interface.
- Update `cron-rss-source-ingest/bin/adapter.py` and `bin/runner.py` to validate the effective RSS projection and seed-origin-to-marker journal chain before polling.
- Update the RSS package's `AGENTS.md` and `SKILL.md` contracts. Add focused transition tests under `cron-rss-source-ingest/tests/`.
- Extend `lib-bursawatch-source-ingest/bin/legacy_cursor_seed.py` with a caller-specified apply guard that preserves the current default. Cover that compatibility in `lib-bursawatch-source-ingest/tests/test_source_ingest.py`.
- Do not change Telegram code. Document use of its existing one-edge command in the implementation plan and production transition procedure.

## RSS transition flow

The RSS package adds `cron-rss-source-ingest/bin/compatible_catalog_transition.py` with `preview` and `apply` actions. Each invocation handles exactly one consecutive catalog edge. The intended current path is 4 to 5, 5 to 6, then 6 to 7.

### Preview

Preview accepts prior and target effective catalog snapshots, the RSS state root, and a private plan path outside that root. It verifies:

- Both snapshots are valid and the target revision is exactly one above the prior revision.
- The complete enabled, verified Stockbit RSS projection is identical in both snapshots. This includes endpoint identity, capability, settings, dispatch metadata, verification state, and provenance. The projection must contain the four supported lanes, with no extra enabled RSS rows accepted by this reader.
- The reader marker equals the prior revision, the live Stockbit config revision matches `watch-config-revision.json`, and the existing seed-to-prior journal chain is valid.
- Each of the four legacy cursor records and endpoint validator files is present and valid. All four seeds share the same origin revision and legacy state digest. Cursor positions and response validators are not used as new seed boundaries.
- The state root contains no unsupported symlink or filesystem entry and can be fully fingerprinted.

The plan binds the prior and target catalog hashes, the normalized Stockbit projection digest, the watcher config revision, the origin and target revisions, and the source-state fingerprint. It contains no article text, feed URLs, credentials, or delivery payloads. Preview does not change the source state.

### Apply

Apply reloads the same snapshots and plan, repeats all package checks, and requires the source state to match the preview fingerprint. The source writer must be paused with no run in flight before apply; the CLI cannot prove scheduler quiescence. The package-specific apply guard is required.

The command calls the shared planner in revision-only mode. It writes one private transition journal under `catalog-transitions/` and advances only `catalog-revision.json`. It does not write cursors, validators, seed records, Stockbit owner state, inbox work, or receipts. Each edge gets its own preview and apply so that an interrupted step can resume only from its exact plan.

### Runtime validation

Before RSS polling, the adapter validates the effective catalog projection, current watcher config revision, and reader marker. It treats each `legacy_seed.catalog_revision` as the immutable origin revision. It then checks that:

- All four seeds have the same origin revision, and the origin is no newer than the reader marker.
- A marker equal to the origin has no transition edges. Otherwise, every adjacent journal from the origin through the marker exists, is complete, and identifies the RSS compatible transition type.
- The journal chain has no gaps or overlaps. Each edge records the same normalized Stockbit projection digest and watcher config revision as the current validated inputs.
- The last edge ends at the effective catalog revision. The marker equals that revision.

The runtime guard must reject a directly edited marker without a valid journal chain. A partial journal or changed projection stays blocked. The original legacy seed revision and cursor boundary remain unchanged.

## Telegram and owner work

Telegram uses its current `cron-tg-source-ingest/bin/compatible_catalog_transition.py` command for two separate adjacent transitions. It pauses the source writer, previews and applies 5 to 6, then previews and applies 6 to 7 with the exact matching snapshots and fresh state fingerprint required by the current command.

This design does not reorder Telegram `run_once()`. After the RSS and Telegram transitions are separately released and applied, observe Telegram's due owner work on a natural scheduled run. If it remains due, diagnose its lease, model response, and owner state in a separate workstream. Stockbit's runner already services accepted pipeline work when intake is blocked, so no runner-order change is included for it either.

## Failure behavior

Preview blocks without writing source state when a source-owned row, watcher revision, marker, cursor, validator, seed origin, state file, or prior journal does not match the reviewed inputs. Apply blocks on a changed plan or state fingerprint. An interrupted apply remains non-runnable until the same plan resumes and completes. A new or changed catalog edge requires a fresh review; the tool must not skip it or infer compatibility from matching first and last snapshots alone.

The package emits bounded, sanitized error reasons. Plans and journals stay private and never include article text, URLs, credentials, or delivery content. There is no automatic rollback, cursor reset, replay, backfill, direct Discord resend, permanent cadence change, or destination change in this design. The user authorized a temporary pause and resume of the existing source jobs for the reviewed rollout.

## Regression coverage

Tests use temporary state roots and synthetic catalog snapshots. They make no network requests and send no messages. Coverage includes:

- Valid adjacent RSS snapshots with an unchanged four-lane projection preview and apply successfully.
- A changed endpoint row, capability, setting, provenance, verification state, watcher revision, or nonconsecutive revision blocks before apply.
- A preview is read-only. Apply changes only the catalog marker and its transition journal; cursor records, validator files, and legacy seed provenance are byte-for-byte preserved.
- A changed state file or plan between preview and apply blocks.
- The RSS apply guard is required. The Telegram seed guard alone cannot authorize an RSS transition.
- A complete origin-to-marker journal chain is accepted. A missing, incomplete, overlapping, foreign, or changed-projection journal is rejected.
- A direct marker advance without a journal is rejected. An interrupted apply resumes from the same plan and remains blocked until its journal is complete.
- Existing Telegram one-edge behavior remains unchanged when the shared planner gains a caller-specific apply guard.

The implementation plan will sequence focused RSS and shared planner tests, the package suites, and `bash scripts/test-all` as required by the repository contract.

## Production and release boundary

The approved design authorizes the implementation and bounded production actions described above. The implementation plan must sequence package release, fresh production checks, rollback preservation, temporary job pauses, state application, schedule restoration, and natural-run observation. Do not bypass the existing CI and release-agent gates.

Before the authorized production transition, refresh the production snapshot and catalog history, verify both package projections and state markers, preserve the required rollback archive under `~/backup/hermes/`, and pause each active writer with no in-flight run. Apply the Telegram and RSS edges through their package commands, verify the completed marker and journal chain, then restore schedules only through the approved scheduler path. Validation of the first natural runs is separate from schedule or service health. No synthetic message or manual cron trigger is allowed.
