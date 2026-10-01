# Bursawatch Catalog Transition Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Choose `executing-plans` (recommended) or `subagent-driven-development` after plan review. Steps use checkbox syntax for tracking.

**Status:** Approved by the user on 2026-09-30; implementation underway.

**Goal:** Restore future-only polling for Telegram and Stockbit RSS by proving their existing reader state remains compatible with each intervening Source Catalog revision.

**Architecture:** Keep Telegram's existing one-edge compatibility command unchanged and apply it for 5 to 6 and 6 to 7. Add an RSS-owned one-edge preview/apply command that proves the complete enabled Stockbit projection is unchanged, uses the shared source-state planner in revision-only mode, and validates each legacy seed's immutable revision-4 origin through a complete journal chain before polling.

**Tech Stack:** Python 3, pytest, JSON catalog snapshots and state, the shared Bursawatch source-ingest library, Control Plane desired-schedule revisions, the VPS Hermes schedule reconciler, and the Bursawatch release agent.

**Spec:** [docs/superpowers/specs/2026-09-30-bursawatch-catalog-transition-recovery-design.md](../specs/2026-09-30-bursawatch-catalog-transition-recovery-design.md)

## File Map

- `lib-bursawatch-source-ingest/bin/legacy_cursor_seed.py` owns the generic state fingerprint and durable revision-only journal. Add an optional caller-specific apply-guard environment variable while retaining its current default.
- `lib-bursawatch-source-ingest/tests/test_source_ingest.py` proves the guard contract, default compatibility, and resumable marker-only transition.
- `lib-bursawatch-source-ingest/README.md` documents the caller-specific guard and revision-only behavior.
- `cron-rss-source-ingest/bin/compatible_catalog_transition.py` owns RSS snapshot validation, preview/apply CLI, package-specific guard, and RSS journal metadata.
- `cron-rss-source-ingest/bin/adapter.py` validates immutable seed origins and the complete RSS journal chain before polling.
- `cron-rss-source-ingest/bin/runner.py` passes the effective catalog and validated Stockbit config to the production seed guard.
- `cron-rss-source-ingest/tests/test_compatible_catalog_transition.py` covers the RSS transition CLI and its state preservation. `test_adapter.py` and `test_runner.py` cover runtime journal validation and fail-closed behavior.
- `cron-rss-source-ingest/AGENTS.md` and `SKILL.md` document the future-only transition contract and runtime provenance rules.
- `platform-bursawatch-release/tests/test_release_agent.py` pins the RSS command and shared planner to the already allowlisted runtime units. The existing manifest already covers RSS `bin/**` and the shared source-ingest `bin/**`; do not widen it without evidence.
- `docs/README.md` links this plan and the approved design.

## Global Constraints

- Work in `/Users/absolutepraya/Documents/Projects/Hermes/.worktrees/bug-squashing` on branch `absolutepraya/bug-squashing`.
- Handle one consecutive catalog edge per RSS preview and apply: 4 to 5, 5 to 6, then 6 to 7.
- Keep each `legacy_seed.catalog_revision` immutable at its revision-4 origin; accept a later marker only with a complete, consecutive RSS-owned journal chain.
- RSS transition apply uses `BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY=1`; the shared planner keeps `BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY` as its default for existing callers.
- A transition may change only `catalog-revision.json` and its private journal. Preserve cursor bytes, validators, seed records, Stockbit owner state, inbox work, receipts, and destinations.
- Pause each source writer and prove no run is in flight before production apply. Use the supported Hermes scheduler interface to pause and resume the existing jobs.
- Refresh the production snapshot and catalog history before rollout. Preserve the original runtime state under `~/backup/hermes/runtime-cutovers/<YYYY-MM-DD>/<runtime-identity>/` for at least 30 days.
- Tests use synthetic catalog snapshots and temporary state, make no source or Discord requests, and send no messages. RSS runtime release verification remains `runner.py --verify-synthetic`.
- Use the existing published-code, release manifest, and exact-main-SHA CI gates. Do not change delivery destinations or cadence, run a job manually, reset a cursor, replay, backfill, or send a test post.
- Keep related Markdown aligned as implementation clarifies or changes behavior. Before each task commit, review affected package and repository contracts, including `README.md`, `AGENTS.md`, `CRON.md` or `SKILL.md`, release documentation, and `docs/README.md` as applicable. Update affected documents in the same task and commit. Leave unaffected documents untouched and record the documentation review in the execution ledger.
- After apply, restore schedules through the supported scheduler path and observe natural scheduled runs. Scheduler health alone does not prove source-to-delivery.

## Review Focus

1. A malformed catalog, nonconsecutive edge, extra enabled RSS endpoint, or changed enabled Stockbit row must block; pin these in Task 2.
2. Missing, malformed, mixed-origin, or mixed-digest cursor seeds and malformed validators must block without rewriting provenance; pin these in Task 3.
3. A missing, incomplete, overlapping, foreign, or changed-projection journal must block polling, and a direct marker edit must not pass; pin these in Task 3.
4. A changed state file, plan, symlink, or unsafe plan path between preview and apply must block before source state changes; pin these in Task 2.
5. The RSS guard must be required while the shared planner's existing default remains valid for Telegram News callers; pin these in Task 1.

---

### Task 1: Add a caller-specific apply guard to the shared transition planner

**Files:**

- Modify: `lib-bursawatch-source-ingest/bin/legacy_cursor_seed.py`
- Modify: `lib-bursawatch-source-ingest/tests/test_source_ingest.py`
- Modify: `lib-bursawatch-source-ingest/README.md`

**Interfaces:**

- Extend `plan_catalog_revision_transition` with `apply_guard_env: str = "BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY"`.
- Validate `apply_guard_env` as a nonempty environment variable name matching `[A-Z][A-Z0-9_]*`; read only that variable when applying.
- Existing callers that omit the argument retain the current guard behavior. The RSS command passes `BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY`.

- [ ] **Step 1: Add the caller-specific guard regression test**

Add `test_catalog_revision_transition_uses_caller_specific_apply_guard`. Build a revision-only preview with `allow_empty_seeds=True` and valid `metadata.reason`. Set only the existing default variable and assert apply is blocked with the caller-specific variable named in the reason. Then set only the requested variable and assert apply advances the marker and completes the journal.

Run: `mise exec -- python -m pytest -q lib-bursawatch-source-ingest/tests/test_source_ingest.py::test_catalog_revision_transition_uses_caller_specific_apply_guard`

Expected: FAIL because the planner does not accept `apply_guard_env`.

- [ ] **Step 2: Implement the optional environment-variable parameter**

Add the parameter after `expected_plan`, preserve the current default, validate its name before planning, and use it instead of the hard-coded variable at the apply guard. Keep the environment variable name out of journal metadata and source state.

- [ ] **Step 3: Prove existing default behavior remains unchanged**

Run the new test plus `test_catalog_revision_transition_seeds_all_cursors_before_advancing_and_resumes` and `test_catalog_revision_only_transition_preserves_all_cursor_files`.

Run: `mise exec -- python -m pytest -q lib-bursawatch-source-ingest/tests/test_source_ingest.py -k 'catalog_revision_transition'`

Expected: PASS. Existing callers still apply with `BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY=1`; the RSS-specific name authorizes only calls that explicitly request it.

- [ ] **Step 4: Cover an interrupted revision-only apply**

Add `test_catalog_revision_only_transition_resumes_after_marker_update`. Interrupt the final journal completion after the marker has advanced, verify the journal remains `applying`, then rerun with the same preview and guard and assert it completes without changing any cursor, validator, or seed file.

Run: `mise exec -- python -m pytest -q lib-bursawatch-source-ingest/tests/test_source_ingest.py::test_catalog_revision_only_transition_resumes_after_marker_update`

Expected: PASS after implementation; the same plan resumes, and the marker is never accepted as complete until the journal status is `complete`.

- [ ] **Step 5: Document the guard contract**

Update the README's library-usage statement to name its current imports from Telegram, X, WhatsApp, Stockbit RSS, and the Instagram adapter; make clear Instagram has no registered job. Then describe the optional guard parameter, its default, and the caller-specific RSS value. State that revision-only apply fingerprints all existing files and changes only the marker and journal.

- [ ] **Step 6: Commit the shared planner change**

```bash
git add lib-bursawatch-source-ingest/bin/legacy_cursor_seed.py lib-bursawatch-source-ingest/tests/test_source_ingest.py lib-bursawatch-source-ingest/README.md
git commit -m "feat: allow source-specific catalog transition guards"
```

### Task 2: Add the RSS-owned adjacent transition command

**Files:**

- Create: `cron-rss-source-ingest/bin/compatible_catalog_transition.py`
- Create: `cron-rss-source-ingest/tests/test_compatible_catalog_transition.py`

**Interfaces:**

- Define `build_plan(prior: dict[str, Any], target: dict[str, Any], state_root: Path, loaded_config: Any) -> dict[str, Any]`.
- Define `apply_plan(expected: dict[str, Any], prior: dict[str, Any], target: dict[str, Any], state_root: Path, loaded_config: Any) -> dict[str, Any]`.
- The CLI is `python bin/compatible_catalog_transition.py {preview,apply} --prior-catalog PATH --target-catalog PATH --state-root PATH --plan-file PATH`. It loads the current validated Stockbit config with `load_watch_config_for_run()` for both actions.
- Every preview/apply handles one adjacent edge. Apply calls `plan_catalog_revision_transition` with `seeds=[]`, `allow_empty_seeds=True`, RSS-specific metadata, and `apply_guard_env="BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY"`.

- [ ] **Step 1: Add preview and validation tests**

Add tests for a valid 4-to-5 preview, nonconsecutive revisions, malformed snapshots, a changed enabled row in each of identity/capability/settings/provenance/verification/dispatch metadata, a missing or extra enabled Stockbit lane, a symlinked state root, and a plan path inside or symlinked into the state root. Assert preview does not modify any file under the state root and the plan contains hashes and revisions but no feed URL or article text.

Run: `mise exec -- python -m pytest -q cron-rss-source-ingest/tests/test_compatible_catalog_transition.py`

Expected: FAIL because the RSS transition command does not exist.

- [ ] **Step 2: Implement RSS projection validation and plan construction**

Require both snapshots to contain a valid integer revision, with `target.revision == prior.revision + 1`. Compare the complete enabled Stockbit subscription rows after sorting by `(endpoint_id, capability_id)`, require exactly the four configured Stockbit lanes and the `stockbit_snips` capability, and reject duplicate identities. Bind canonical prior/target catalog hashes, projection digest, live watcher-config revision, common seed-origin revision, and the shared planner's complete state fingerprint. Do not store catalog rows, feed URLs, config payloads, or article data in the plan.

Require the state marker to be at `prior.revision`, except when the exact current edge already has its matching journal and the marker has advanced to `target.revision` during an interrupted apply. Validate the complete seed-origin-to-prior chain before creating a new edge. For interrupted apply, allow only that exact current-edge journal while validating the prior chain, then let the shared planner validate the journal against the unchanged plan. Require the plan path to be private and outside the state root.

- [ ] **Step 3: Add apply and resume tests**

Add `test_apply_advances_only_marker_and_journal` and `test_apply_resumes_interrupted_edge_from_same_plan`. Compare every preexisting cursor, validator, seed, owner, inbox, and prior-journal file byte for byte before and after. Assert a changed plan, state fingerprint, RSS apply guard, or current catalog snapshot blocks without changing those files.

Run: `mise exec -- python -m pytest -q cron-rss-source-ingest/tests/test_compatible_catalog_transition.py -k 'apply'`

Expected: FAIL until apply is implemented; afterward, only `catalog-revision.json` and `catalog-transitions/<from>-to-<to>.json` differ.

- [ ] **Step 4: Implement apply and the CLI**

Recompute and compare the package plan during apply, then pass its revision-only subplan to the shared planner. Journal metadata must identify `rss-compatible-catalog-transition`, the projection digest, watcher-config revision, catalog hashes, and seed-origin revision. Emit bounded sanitized errors and a JSON result containing status, edge, state counts, and plan digest only. Never emit catalog row values, source text, URLs, credentials, or delivery payloads.

- [ ] **Step 5: Run the focused RSS command tests**

Run: `mise exec -- python -m pytest -q cron-rss-source-ingest/tests/test_compatible_catalog_transition.py`

Expected: PASS for preview, rejection cases, private plan handling, apply, and exact-plan resume.

- [ ] **Step 6: Commit the RSS transition command**

```bash
git add cron-rss-source-ingest/bin/compatible_catalog_transition.py cron-rss-source-ingest/tests/test_compatible_catalog_transition.py
git commit -m "feat: add guarded Stockbit catalog transitions"
```

### Task 3: Validate immutable RSS seed provenance before polling

**Files:**

- Modify: `cron-rss-source-ingest/bin/adapter.py`
- Modify: `cron-rss-source-ingest/bin/runner.py`
- Modify: `cron-rss-source-ingest/tests/test_adapter.py`
- Modify: `cron-rss-source-ingest/tests/test_runner.py`

**Interfaces:**

- Change the guard to `require_legacy_cursor_seed(state_root: Path, snapshot: dict[str, Any], loaded_config: Any) -> None`.
- Derive the projection digest from the effective catalog rows accepted by `endpoints(snapshot, loaded_config)`. Pass the same effective catalog and config snapshot from the runner before source polling.
- Define `_require_rss_transition_chain(state_root: Path, origin_revision: int, through_revision: int, projection_sha256: str, watch_config_revision: int, *, allow_pending_edge: tuple[int, int] | None = None) -> None`. The runtime guard calls it through the reader marker without a pending edge. The preview/apply builder calls it through the prior edge and may allow only its exact current edge; the shared planner then validates that edge against the unchanged plan.
- Validate journal path `catalog-transitions/<from>-to-<to>.json` for every adjacent edge from the common immutable seed origin to the reader marker. Require a complete version-1 journal, empty `seeded_endpoints`, a revision-only plan, the RSS transition type, and matching projection digest and watcher-config revision.

- [ ] **Step 1: Add origin and journal-chain tests**

Update `_seeded_rss_root` fixtures to use four revision-4 seed origins. Add `test_production_seed_gate_accepts_complete_adjacent_transition_chain` with markers 4 and 7, complete 4-to-5, 5-to-6, and 6-to-7 RSS journals, and byte-identical seed provenance. Add rejection tests for a direct marker change without journals, a missing edge, an incomplete edge, an overlapping or foreign edge, changed projection/config revision metadata, mixed seed origins, mixed legacy-state digests, and malformed validator files.

Run: `mise exec -- python -m pytest -q cron-rss-source-ingest/tests/test_adapter.py -k 'seed_gate or cursor_handoff'`

Expected: FAIL because the current guard requires seed origin to equal the effective catalog revision and does not inspect a journal chain.

- [ ] **Step 2: Implement the seed-origin-to-marker validator**

Keep each cursor's `legacy_seed.catalog_revision` unchanged. Require all four seeds to share one integer origin revision and legacy-state digest, with origin no newer than the marker. Validate exact expected journal filenames and no unexpected transition entries; reject gaps, overlaps, symlinks, incomplete or foreign journals, non-revision-only journals, changed projection digests, and changed watcher-config revisions. When marker equals origin, require no transition edges. When marker is later, require a complete chain ending at that marker.

- [ ] **Step 3: Wire the effective inputs before intake**

Update `runner.run_once` to pass its already loaded effective catalog and Stockbit config to the seed guard before calling `ingest_once`. Keep the existing fail-closed heartbeat reason for an invalid handoff. Preserve the existing behavior that accepted pipeline work and the Stockbit owner worker still run when new RSS intake is blocked.

- [ ] **Step 4: Test the production runner boundary**

Add a runner test asserting an invalid journal chain prevents `fetch_feed` from running while the pipeline owner path still executes. Keep the existing `test_production_runner_blocks_before_fetch_when_cursor_handoff_is_missing` behavior.

Run: `mise exec -- python -m pytest -q cron-rss-source-ingest/tests/test_adapter.py cron-rss-source-ingest/tests/test_runner.py`

Expected: PASS for origin-4 marker-4, complete origin-4 marker-7, rejection of tampering, no feed request on invalid state, and continued owner work.

- [ ] **Step 5: Commit the runtime provenance guard**

```bash
git add cron-rss-source-ingest/bin/adapter.py cron-rss-source-ingest/bin/runner.py cron-rss-source-ingest/tests/test_adapter.py cron-rss-source-ingest/tests/test_runner.py
git commit -m "fix: validate Stockbit seed transition history"
```

### Task 4: Update package and release contracts

**Files:**

- Modify: `cron-rss-source-ingest/AGENTS.md`
- Modify: `cron-rss-source-ingest/SKILL.md`
- Modify: `platform-bursawatch-release/tests/test_release_agent.py`
- Modify: `docs/README.md`

- [ ] **Step 1: Document the RSS transition command and runtime invariant**

Replace the RSS contract that requires seed catalog revision to equal the current effective revision. Document immutable seed origin, complete adjacent journal validation, preview/apply inputs, the RSS-specific apply guard, plan privacy, unchanged state files, and the no-manual-run/no-replay boundary. Explain that each edge needs its own fresh preview and apply.

- [ ] **Step 2: Pin existing release-manifest coverage**

Extend `test_rss_source_ingest_resolves_as_an_installable_runtime` to assert `cron-rss-source-ingest/bin/compatible_catalog_transition.py` maps to `cron-rss-source-ingest-pilot` and `lib-bursawatch-source-ingest/bin/legacy_cursor_seed.py` maps to `lib-bursawatch-source-ingest-pilot`. Keep the current wildcard paths and dependency ordering unless this test proves they are insufficient.

Run: `mise exec -- python -m pytest -q platform-bursawatch-release/tests/test_release_agent.py::test_rss_source_ingest_resolves_as_an_installable_runtime`

Expected: PASS with the existing manifest and no broadened runtime allowlist.

- [ ] **Step 3: Link the plan and approved spec**

Update `docs/README.md` to link this implementation plan and retain the spec's approved status. Keep production facts time-bounded and refer readers to a fresh production snapshot before live actions.

- [ ] **Step 4: Commit the package and release documentation**

```bash
git add cron-rss-source-ingest/AGENTS.md cron-rss-source-ingest/SKILL.md platform-bursawatch-release/tests/test_release_agent.py docs/README.md
git commit -m "docs: record catalog transition runtime contract"
```

### Task 5: Verify the repair and perform the authorized rollout

**Files:**

- No additional source files. Use the completed tasks, existing package commands, and the supported Hermes scheduler and release-agent interfaces.

**Interfaces:**

- Telegram transition owner: `cron-tg-source-ingest/bin/compatible_catalog_transition.py`, one edge per preview/apply, existing apply guard `BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY=1`.
- RSS transition owner: `cron-rss-source-ingest/bin/compatible_catalog_transition.py`, one edge per preview/apply, RSS guard `BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY=1`.
- The current recorded production marker observations are Telegram 5 and RSS 4 against catalog 7. They are historical evidence only. The latest snapshot at 21:19 WIB on 2026-09-30 showed both jobs active, desired schedules matched, and the release agent blocked with CI pending; all must be refreshed before rollout.

- [x] **Step 1: Run focused tests and synthetic release verification**

Run:

```bash
mise exec -- python -m pytest -q lib-bursawatch-source-ingest/tests/test_source_ingest.py
mise exec -- python -m pytest -q cron-rss-source-ingest/tests
mise exec -- python -m pytest -q cron-tg-source-ingest/tests/test_compatible_catalog_transition.py
mise exec -- python -m pytest -q platform-bursawatch-release/tests/test_release_agent.py
mise exec -- python cron-rss-source-ingest/bin/runner.py --verify-synthetic
bash scripts/test-all
```

Expected: all checks pass; synthetic RSS verification reports `network=false`, `secrets=false`, and `writes=false`. Do not poll or wait for GitHub CI; inspect its exact result only when needed for the chosen release path.

- [x] **Step 2: Prepare the implementation branch for publication**

Commit the reviewed source and documentation changes and push the worktree branch with `git push -u origin absolutepraya/bug-squashing`. Carry the branch through the repository's normal reviewed publication path, but do not make it eligible for automatic production release yet. Do not edit `main` directly or bypass the exact-current-main-SHA CI and release-agent checks.

- [x] **Step 3: Refresh production evidence and verify the reviewed boundary**

Before the production window, run `python3 scripts/production_snapshot.py --production`. Read current catalog revisions 4 through 7 and confirm the exact unchanged Telegram and Stockbit projections. Read the current state markers, RSS watch-config revision, all four RSS cursor seeds, validators, and transition journals. Record accepted owner-work and lease counts so apply can prove it left them unchanged; they do not need to be empty. Also inspect `bursawatch-schedule-reconciler.timer` and the desired schedule revisions. Stop if any projection, state marker, provenance, job identity, cadence, or destination differs from the reviewed design.

**Verified 2026-10-01 00:53 to 00:54 WIB:** catalog revision 7 remains current. Revisions 4 through 7 have identical enabled Telegram projection SHA-256
`b77cec55af0baf547c3cd65027abbee14e8c0c05ed28700463fdcb02757be810`, identical four-row RSS projection SHA-256
`307835c8f98403433a024e136101392be01c1a66a5fe13670dfe70815cd2550d`, and selected-security SHA-256
`4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. Telegram has 212 accepted work
rows, all done, and no active lease; RSS has no accepted work rows. State markers remain Telegram 5, RSS 4,
and Stockbit watcher config 1. The four RSS seeds remain at immutable origin revision 4 with a shared
legacy-state digest; all four validator files parse, and no RSS transition journals exist.

- [x] **Step 4: Pause both writers through desired schedule state**

The VPS schedule-reconciler timer was active in the 2026-10-01 00:35 WIB snapshot. Before pausing, refresh that status. For Telegram job `bursawatch-tg-source-ingest` and Stockbit Control Plane job `bursawatch-stockbit-snips` (Hermes name `cron-stockbit-snips`), use the authenticated admin schedule interface to store `enabled=false` at each existing interval and timezone. This temporary desired-state change is authorized for this rollout. Let the natural reconciler pass apply each revision, then verify `applied_revision`, paused Hermes state, unchanged interval and delivery configuration, and no run in flight. A direct `hermes cron pause` while desired state remains enabled can be undone by the next timer pass.

**Verified 2026-10-01 00:53 WIB:** Telegram desired revision 2 and Stockbit desired revision 6 are applied and
effective, both disabled at their original 60-second and 900-second intervals in `Asia/Jakarta`. The
production snapshot reports 6 active and 7 paused Hermes jobs, with all eight desired schedules matching.
No source-reader process was found, and the last runs were `ok`.

- [x] **Step 5: Archive both quiescent reader state roots**

After both writers are paused and no run is in flight, archive their complete source-state roots with SHA-256 inventories under `~/backup/hermes/runtime-cutovers/<YYYY-MM-DD>/bursawatch-tg-source-ingest/` and `.../bursawatch-rss-source-ingest/`. Verify the archive checksums against the quiescent live trees before any catalog marker or journal write. Keep the archives private for at least 30 days.

**Verified 2026-10-01 00:54 WIB:** private archives and SHA-256 inventories are stored under
`~/backup/hermes/runtime-cutovers/2026-10-01/`. The Telegram archive contains 13 files and has archive
SHA-256 `c04df46e07d0ff179c7527493d506534f72046e38da66a22c0fed2836edd7ee9`; the RSS archive contains
11 files and has archive SHA-256 `ec3a31b1e8d1d912a04600d51b7515e3155a303afda0e55cc34dadc6777e9fb0`.
Both archive members matched the complete live-tree SHA-256 inventories. Archive directories are mode
`0700`; files are mode `0600`. No catalog marker or transition journal was changed.

- [ ] **Step 6: Publish and verify the exact-main release**

Carry the branch through the normal reviewed main publication path. Let CI and the release agent process the exact current main SHA, then verify the shared source-ingest library and RSS source-ingest runtime checksums plus each isolated no-post result before applying state. Do not poll or wait on a pending CI run; continue independent read-only preparation or end the turn, leaving jobs paused until the result is ready. If CI or release fails before state apply, restore both desired schedules to enabled at their original intervals and timezones, verify natural reconciliation, then stop without changing source state.

- [ ] **Step 7: Apply the package-owned catalog transitions**

For Telegram, use the existing command to separately preview and apply 5 to 6, then 6 to 7. For RSS, use the new command to separately preview and apply 4 to 5, 5 to 6, then 6 to 7. Use the exact prior/target snapshots and state root for each edge. Require a fresh matching plan per edge. After each apply, verify the marker and complete journal. For RSS, verify all seed origins remain revision 4 and cursor, validator, owner, inbox, receipt, and prior-journal files remain byte-for-byte unchanged.

If an apply is interrupted, resume only with its exact plan and complete journal. If source projection or state evidence changes, stop before the next edge. Do not reset markers, reseed, replay, or restore an archive over a state root with an active writer.

- [ ] **Step 8: Resume schedules and observe natural runs**

After both transition chains are complete, restore the two existing desired schedules to enabled at their original intervals and timezones through the authenticated admin schedule interface. Let the natural reconciler pass apply each revision and verify the paused state clears while cadence and delivery configuration remain unchanged. Observe the next natural scheduled runs without manually triggering either job or sending a test message. Verify the readers pass their catalog gates and record fetched/accepted counts, owner work progress, and Delivery Owner receipts where new work exists.

For Telegram, observe whether due owner work drains naturally. If it remains due after compatibility is restored, keep runner order out of scope and open the separate lease/model/owner-state diagnosis agreed in the design. A clean schedule heartbeat without new source content is not proof of a new source-to-delivery event; report that limit explicitly.

## Self-Review

- **Spec coverage:** shared default guard, RSS revision-only transition, catalog projection proof, immutable seed origins, exact journal chain, fail-closed runtime behavior, state preservation, regression tests, production pause/apply/resume, and natural-run observation are covered by Tasks 1 to 5.
- **Step scan:** each task defines exact files, interfaces, named tests, expected outcomes, and commands. Production actions occur only after local verification and a fresh state/schedule check.
- **Type consistency:** RSS `build_plan` and `apply_plan` both receive the same snapshots, state root, and loaded Stockbit config object; the adapter guard consumes the effective snapshot and loaded config produced by the runner.
- **Review Focus:** all five listed input classes have named tests in Tasks 1 to 3.
- **Proportion:** the plan preserves five independently reviewable deliverables and one gated operational rollout without copying implementation bodies from the spec.
