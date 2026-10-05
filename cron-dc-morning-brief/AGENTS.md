# Morning brief owner

Read the repository instructions and this package's single root `SKILL.md`.
This package is a local implementation of the proposed
`bursawatch-dc-morning-brief` runtime. Scheduler activation, destination selection,
provider permissions, credentials and service provisioning are separate rollout
inputs. Do not infer readiness or natural delivery from these local tests.

- Imports perform no IO. Constructors and caller configuration are explicit.
- Default mode is cache-only. Synthetic fixtures require explicit preview inputs;
  never replace missing real evidence with synthetic prices, calendars or text.
- Use the existing `lib-sectors` shared provider store and immutable generations.
  The morning run database is separate. Do not duplicate its budget/cache ledger.
- Preserve supplied CSV bytes and overlap semantics. Sector membership is imported
  once with official-first fallback provenance, without an automatic refresh.
- Use a verified, versioned IDX calendar and amendment check. Never infer sessions
  from weekdays. Revalidate calendar visibility and amendment age at the freeze.
  The explicit publication session governs cap age; the immediately preceding
  verified session ends the closing window. Non-sessions produce a no-op
  heartbeat under the planned runner.
- Freeze evidence and publication artifacts under the session's fenced lease.
  Conflicting freezes fail closed. Corrections cannot rewrite prior publications.
- All 18 levels use aligned sessions, compatible split-adjusted returns, a fixed
  cap snapshot and consistent members. Preserve exclusions and original coverage.
- Source manifests freeze before version reads/selection. Recovery compares every
  immutable hash/ref and never recaptures; incomplete corpora force facts-only.
- Globals require explicit regular exchange sessions and prior-close denominator.
  Calendar snapshots require primary URL, cutoff-visible verification and exact
  amendments; dynamic empty pages stay unavailable. No live-fetch fallback.
- Injected writers return complete attributed source excerpts only. Invocation and
  validation share a deadline capped at 07:55 WIB, with one daemon worker maximum.
  Late worker results never mutate the selected fallback or owner state.
- Run focused tests, then `python -m pytest -q cron-dc-morning-brief/tests`.
  Full repository verification belongs to the final integration task.
- Tests use injected dependencies and temporary state. No live model, provider,
  Discord, VPS or scheduler operations are part of package development.
