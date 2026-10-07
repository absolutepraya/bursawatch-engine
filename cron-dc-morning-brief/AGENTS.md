# Morning brief owner

Read the repository instructions and this package's single root `SKILL.md`.
This package contains the cache-only owner and an explicitly configured live
dispatcher for `bursawatch-dc-morning-brief`. Scheduler activation and verified
provider inputs remain separate rollout steps. Do not infer readiness or natural
delivery from local tests or an installed dispatcher.

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
  and candidate assembly share the frozen fallback deadline (default 07:55 WIB) and one daemon worker maximum.
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
  Never replace pending/ambiguous images with omissions. After the frozen attempt deadline (default 08:15 WIB), query
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
  Default cutoff is 07:30 WIB and delivery is 08:00 WIB, with fallback five minutes
  before and last new attempt fifteen minutes after. Future edits cannot rewrite
  an existing session. Preparation must never submit before the frozen target.
  Host credentials, provider stores and calendar attestations remain separate.

- `live_runner.py --check --runtime-config <private-file>` reads the database
  configuration and explicit private inputs only. It must not initialize stores,
  capture source evidence, resolve model credentials, fetch providers or post.
  `--live` is a separate required switch. Host configuration contains absolute
  paths, never credential values or replacements for database operator settings.
  Retained input manifests require `provenance='live-retained'`, cutoff visibility,
  and a checksum-bound verified IDX calendar. Never promote a preview manifest.
- The writer follows the installed Hermes model/provider through its existing
  router. No separate model pin, provider fallback or SDK retry is allowed.
  A frozen writer bundle retains its original version on recovery.
  Chart request and proof freeze in upstream before rendering; verified cached
  legacy provider bytes use `lib-chart-img`, without a live fetch in the dispatcher.
  New IHSG charts use the retained Yahoo daily snapshot and
  `lib-yahoo-market-data` for ordinary OHLC, SMA 10/20/50/100 and Wilder RSI(14).
  Require the official preceding close, a complete three-month visible window
  and MA100 warm-up sessions. Missing candles stay gaps, never interpolated.
- `collect_public_inputs.py --collect-public` is a separate explicit no-post
  producer. It may fetch at most fourteen bounded Yahoo responses, without
  retries, redirects, paid requests, writer calls or publication calls. Native
  hourly `tradingPeriods` establish session windows; daily timestamps cannot
  establish schedules. Preserve unavailable configured instruments as visible
  rows. The IHSG facts benchmark requires the previous official IDX session and
  a matching completed native bar; never substitute Yahoo for Sectors rotation
  inputs. Preparation after cutoff cannot backdate a live manifest.
  IHSG daily collection requests one year, shared by benchmark and chart. Reuse
  completed, verified history for the same final session with original provenance.
  Coordinate live HTTP through the explicit private source cache; a 429 records
  Retry-After (or a 24-hour unknown cooldown), and remaining calls stop without
  retries. Publication and previews never fetch indicators separately.
- BPS native Arc release responses are retained verbatim and parsed separately
  from table fixtures. Publication records are not statistical releases. Missing
  reference periods and times remain unknown. Public action IDs rotate with
  frontend deployments and are not hardcoded in the production collector.
