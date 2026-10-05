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
  from weekdays. Non-sessions produce a no-op heartbeat under the planned runner.
- Freeze evidence and publication artifacts under the session's fenced lease.
  Conflicting freezes fail closed. Corrections cannot rewrite prior publications.
- All 18 levels use aligned sessions, compatible split-adjusted returns, a fixed
  cap snapshot and consistent members. Preserve exclusions and original coverage.
- Run focused tests, then `python -m pytest -q cron-dc-morning-brief/tests`.
  Full repository verification belongs to the final integration task.
- Tests use injected dependencies and temporary state. No live model, provider,
  Discord, VPS or scheduler operations are part of package development.
