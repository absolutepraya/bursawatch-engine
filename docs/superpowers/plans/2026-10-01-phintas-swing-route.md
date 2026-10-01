# Phintas Swing Route Canonicalization Plan

**Design:** [`../specs/2026-10-01-phintas-swing-route-design.md`](../specs/2026-10-01-phintas-swing-route-design.md)
**Status:** PR #35 open, merge pending required gates
**Worktree:** `phintas-swing-route`

## Implementation

- [x] Add `trading_plans` to the Phintas endpoint's reviewed source-adapter
  binding and add the matching Control Plane compatibility entry. Keep the
  legacy endpoint definition for historical compatibility, but do not leave
  its live subscription enabled after the move.
- [x] Update the Phintraco Swing owner default, canonical identity guard,
  renderer source link, and config baseline to `phintasprofits` with channel ID
  `1444713822`. Continue accepting already accepted work and the old configured
  handle for this channel during rollout, while rendering the canonical URL.
- [x] Add a narrowly guarded Phintas swing catalog transition. It must permit
  only disabling the old `trading_plans` row and enabling the Phintas row,
  require the existing Phintas cursor, fingerprint all other state, journal
  the transition, and advance only the catalog revision marker.
- [x] Add regression tests for the Phintas endpoint, reply metadata, current
  source link, legacy accepted work, exact catalog diff, cursor preservation,
  apply guard, and migration registration.
- [x] Align the two Telegram package contracts, Control Plane ownership docs,
  this incident record, `docs/README.md`, and this plan with the code and
  rollout contract.
- [x] Run focused package suites, then `bash scripts/test-all`, plus
  `git diff --check`. Do not claim tests not run.
- Focused suites passed: source ingest 58 tests, Phintraco Swing 201 tests,
  Control Plane 207 passed and 1 skipped. `bash scripts/test-all` passed across
  all package suites and repository policy checks.
- [x] Open pull request [#35](https://github.com/absolutepraya/bursawatch-engine/pull/35)
  and register it with the T3 thread. Do not wait on
  running CI. Request auto-merge only through the repository's required checks
  and review gates.

## Forward-only production transition

- [ ] After merge and eligible release, run a fresh
  `python3 scripts/production_snapshot.py --production`. Confirm release SHA
  equals `origin/main`, the Control Plane migration is present, and the source
  reader is active at its existing one-minute cadence.
- [ ] Re-read the effective catalog, Phintraco Swing config, source cursor,
  and source-work queue. Use the live values, not the earlier `35556` snapshot.
- [ ] Pause the Telegram source reader by setting its desired Control Plane
  schedule disabled at the existing interval. Let the natural reconciler
  apply it. Prove no run is in flight and no source work is pending, leased,
  or executing for the Swing owner.
- [ ] Capture the exact effective revision-N and revision-(N+1) catalog
  snapshots. Change only the `trading_plans` subscriptions: disable
  `telegram:phintraprofits`; enable `telegram:phintasprofits`.
- [ ] Update the Swing watcher source username to `phintasprofits`, preserving
  its numeric channel ID and destinations. Validate the returned config
  revision without exposing credentials.
- [ ] Preview the package-owned transition against the paused live source
  state. Confirm the Phintas cursor already exists and is unchanged, the old
  endpoint cursor remains untouched, and every other state hash matches.
  Archive no state and seed no cursor for this revision-only transition.
- [ ] Apply only the unchanged preview with its explicit package guard. Verify
  the journal and target revision marker, then restore the desired enabled
  schedule at the original cadence and let the natural reconciler apply it.
- [ ] Verify a natural scheduled run and healthy heartbeat, the new effective
  catalog binding, and unchanged future-only cursor semantics. Do not trigger
  the production job and do not send or recover message `35530`.
- [ ] Refresh current-production documentation only after a fresh production
  snapshot. State clearly that end-to-end delivery awaits a naturally arriving
  event after the boundary.

## Completion record

- Code/tests: complete. PR #35 is open and linked to the T3 thread; merge is
  pending the repository's required gates.
- Catalog and owner-config transition: pending.
- Natural source-to-delivery event: unobserved; this remains a separate
  evidence layer and is not required for an idle health claim.
