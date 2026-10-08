# Morning brief owner

Read the repository instructions and this package's single root `SKILL.md`.
This package contains the cache-only owner and an explicitly configured live
dispatcher for `bursawatch-dc-morning-brief`. Scheduler activation and verified
provider inputs remain separate rollout steps. Do not infer readiness or natural
delivery from local tests or an installed dispatcher.

- Imports perform no IO. Constructors and caller configuration are explicit.
- Default mode is cache-only. Synthetic fixtures require explicit preview inputs;
  never replace missing real evidence with synthetic prices, calendars or text.
- New numerical production uses the shared Yahoo parser and the explicit private
  producer cache for prices and `lib-sectors` for 30-day bulk cap snapshots.
  Use the existing shared Sectors coordination store and billing window. Ordinary
  split-adjusted Close and positive caps are required for usable members. Missing
  members remain exclusions, never reconstructed values or zero prices. Cap
  refresh failure reuses the last successful snapshot with its original date and
  a stale label. Do not automatically switch providers or retry paid requests. The morning run database is separate from both caches.
- Preserve supplied CSV bytes and overlap semantics. Sector membership is imported
  once with official-first fallback provenance, without an automatic refresh.
- Use a verified, versioned IDX calendar and amendment check. Never infer sessions
  from weekdays. Revalidate calendar visibility and amendment age at the freeze.
  The explicit publication session governs cap age; the immediately preceding
  verified session ends the closing window. Delivery days are separate operator
  configuration: new defaults use Monday to Friday, including IDX holidays.
  Never use publication weekdays as numerical trading sessions. Missing/stale
  calendars omit IHSG facts, charts and rotation, without suppressing a weekday
  factual brief. Legacy configurations without `delivery_days` retain IDX-only
  delivery and frozen recovery semantics.
- Freeze evidence and publication artifacts under the session's fenced lease.
  Conflicting freezes fail closed. Corrections cannot rewrite prior publications.
- All 18 levels use aligned sessions, compatible split-adjusted returns, a fixed
  cap snapshot and consistent members. Preserve exclusions and original coverage.
- Rotation curves are display-only interpolation through observed markers,
  bounded against overshoot. Preserve numerical coordinates and quadrants.
  Konglo numbered markers match the full-name table; preserve frozen secondary
  letters. Its separately labelled central zoom must not cover the full-range
  plot or silently drop outliers. Fit independent asymmetric axes to all visible
  history, include zero and 1 pp padding; quadrant area follows ranges, not counts.
  Draw rotation fonts/strokes/geometry natively at 2x density. Record logical
  coordinate space and pixel ratio; preserve native IHSG/chart pixels. Freeze
  axis, zero, curve, marker and zoom geometry metadata.
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
  The writer may retry once after a validation failure (never after a model failure), inside the
  same worker and deadline. A numeric probability is `probabilitas`/`probability` with a number or
  `peluang`/`berpeluang` with a percentage in one sentence; levels beside "berpeluang" pass.
  Media-only items are omitted and counted, not disabling; partial history of at least six hours is
  accepted and noted. Late worker results never mutate the selected fallback or owner state. Missing
  conditional base/change evidence selects facts-only. Formatting trims claims
  with citations atomically and freezes actual published mode/scenario in
  `presentation`; closing anchors must never expose an omitted candidate.
  The main message follows formatter revision `bursawatch-text-v5`: no IHSG/global
  source links, timestamps, delays, missing-data prose, pulse/scenario headings or
  middots; missing numbers are `-`; an unavailable Outlook paragraph reads `(Analisis outlook gagal dimuat)`;
  image messages are attachment-only and a rotation heading is skipped with its missing image. The IHSG
  tracker comes from the shared Yahoo `parse_closes`/`close_performance` over the
  retained daily source (1/5/22/66 verified sessions, gaps retained) and is frozen
  only with its hash, cutoff and benchmark-equality attestation. Build native
  session proof at actual collection time, never a future provisional cutoff.
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
  Retained input manifests require `provenance='live-retained'` and cutoff visibility.
  Numerical facts require a checksum-bound verified IDX calendar. Weekday delivery
  may use independently verified globals/agenda without that calendar; missing
  or rejected manifests degrade to unavailable sections. Never promote preview data.
- The writer follows the installed Hermes model/provider through its existing
  router. No separate model pin, provider fallback or SDK retry is allowed.
  A frozen writer bundle retains its original version on recovery.
  Chart request and proof freeze in upstream before rendering; verified cached
  legacy provider bytes use `lib-chart-img`, without a live fetch in the dispatcher.
  New IHSG charts use the retained Yahoo daily snapshot and
  `lib-yahoo-market-data` for ordinary OHLC, SMA 10/20/50/100 and Wilder RSI(14).
  Require the official preceding close, a complete three-month visible window
  and MA100 warm-up sessions. Missing candles stay gaps, never interpolated.
- Yahoo can return `close = null` for the latest completed session (seen in every 07:29 WIB
  response on 2026-10-08, while evening and later responses had it). Fill only that one bar via
  `yahoo_market_data.latest_close`, from evidence that agrees with the bar: the response's own
  closing-window price when its day high/low/volume match, or the hourly series when that price
  confirms it, or `chartPreviousClose` of a later one-day chart. The hourly series alone is not
  trusted: it can stop before a closing auction (KOSPI/Nikkei differed by 0.2%-0.3%). Retain the
  method and source hashes; any disagreement keeps `-`. A stale open Asian or FX snapshot shows
  the last completed session instead.
- `collect_public_inputs.py --collect-public` is a separate explicit no-post
  producer. It may fetch at most fourteen bounded Yahoo responses, plus at most one
  one-day previous-close chart per non-FX market whose latest completed close is still null,
  without retries, redirects, paid requests, writer calls or publication calls. Native
  hourly `tradingPeriods` establish session windows; daily timestamps cannot
  establish schedules. Preserve unavailable configured instruments as visible
  rows. The IHSG facts benchmark requires the previous official IDX session and
  a matching completed native bar. The separately bounded Yahoo rotation
  producer supplies all eighteen stock levels, action/trading evidence and
  basket-specific cap snapshots. Preparation after cutoff cannot backdate a live manifest.
  IHSG daily collection requests one year, shared by benchmark and chart. Reuse
  completed, verified history for the same final session with original provenance.
  Coordinate live HTTP through the explicit private source cache; a 429 records
  Retry-After (or a 24-hour unknown cooldown), and remaining calls stop without
  retries. Publication and previews never fetch indicators separately.
- `collect_rotation_inputs.py --collect-public` resumes at most 24 provider
  request attempts by default, with an explicit limit of 3 to 64 shared by Sectors
  cap pages and Yahoo stock histories. Sectors access requires paired absolute
  credential/store paths in producer config and the shared library. Commit only
  complete validated bulk pagination; preserve pending generations and original
  page provenance. Cache caps for 30 days, retaining the last successful snapshot
  with a stale label on failure. No coverage percentage blocks publication: one
  usable cap/price member is sufficient. Display partial baskets, known-cap
  coverage and unknown-cap counts. A provider 400/404/410 or unparseable response for one stock is retained as unavailable for
  the closing window without blocking later stocks; a 429, cooldown or transport fault still
  stops the pass. Retain invalid stock responses for the closing
  window, so ticks cannot refetch halted stocks. New closing sessions use new
  immutable history sources. A manifest is not natural-delivery proof.
- BPS native Arc release responses are retained verbatim and parsed separately
  from table fixtures. Publication records are not statistical releases. Missing
  reference periods and times remain unknown. Public action IDs rotate with
  frontend deployments and are not hardcoded in the production collector.
- `scheduled_runner.py` composes the producer and dispatcher behind one private
  process lock. `--check` never initializes stores, fetches providers or posts.
  `--live` before cutoff uses bounded rotation chunks, then refreshes global and
  benchmark inputs in the last ten minutes. At/after cutoff or during frozen
  recovery, never run producers. Read timing from the database, not fixed cron
  times. Missing/stale official calendars remain fatal for `idx_sessions`;
  `weekdays` keeps global preparation and factual delivery with visible omissions.
  An installed wrapper or paused desired schedule does not prove readiness.
- The Hermes command job uses `bursawatch-dc-morning-brief-job.sh`, which accepts
  no arguments and explicitly invokes the installed scheduled wrapper with
  `--live`. Register with `--no-agent --deliver local` so the owner alone handles
  Discord delivery. The scheduled wrapper's manual `--check` remains no-post.
