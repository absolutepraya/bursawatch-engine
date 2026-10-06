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
- Global equities require explicit regular exchange sessions and prior-close denominator.
  USD/IDR requires separately verified provider FX day windows and daily-close
  policy, never an inferred stock-exchange schedule.
  Calendar snapshots require primary URL, cutoff-visible verification and exact
  amendments; dynamic empty pages stay unavailable. No live-fetch fallback.
- Injected writers return strict source-grounded conditional scenario/core fields.
  Quote exact full source context for scenario roles; model-assessed roles never
  certify source stance, factual truth or consensus. Verified latest IHSG close
  plus a fresh dated upstream factual driver are required. Invocation, validation
  and candidate assembly share the frozen fallback deadline (default 06:55 WIB) and one daemon worker maximum.
  Late worker results never mutate the selected fallback or owner state. Missing
  conditional base/change evidence selects facts-only. Formatting trims claims
  with citations atomically and freezes actual published mode/scenario in
  `presentation`; closing anchors must never expose an omitted candidate.
- `MorningRunner` injects shared source/provider/delivery/publication clients.
  CLI/wrapper defaults to no-post, reads only explicit retained input paths, and
  never discovers credentials. Live injection requires reviewed destination and
  configuration provenance. Freeze `run_mode` before all input/capture work; reject
  preview/live reuse and legacy unknown mode, never relabel immutable old runs.
  All six selections and bytes freeze before submit.
- Confirm receipt key, digest, operation ID and destination before advancing.
  Never replace pending/ambiguous images with omissions. After the frozen attempt deadline (default 07:15 WIB), query
  and reconcile earlier attempts only. Projection retries cannot send messages.
- Every completed/no-op/degraded/fatal attempt emits or simulates the safe
  #hermes heartbeat. Retain original text/scenario for closing consumers.
- Run focused tests, then `python -m pytest -q cron-dc-morning-brief/tests`.
  Full repository verification belongs to the final integration task.
- Tests use injected dependencies and temporary state. No live model, provider,
  Discord, VPS or scheduler operations are part of package development.

- Operator settings use the existing Control Plane revisioned watcher-config API.
  `run_from_control_plane` uses the shared configuration client; never silently
  substitute a source file after an API read failure. `run_from_snapshot` validates
  the shared snapshot checksum and freezes `operator_config` before preparation.
  Default cutoff is 06:00 WIB and delivery is 07:00 WIB, with fallback five minutes
  before and last new attempt fifteen minutes after. Future edits cannot rewrite
  an existing session. Preparation must never submit before the frozen target.
  Host credentials, provider stores and calendar attestations remain separate.
