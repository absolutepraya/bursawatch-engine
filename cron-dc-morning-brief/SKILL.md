---
name: bursawatch-dc-morning-brief
description: Receipt-gated IHSG morning brief with frozen evidence and fixed-cap rotation illustrations.
---

# Morning brief contract

This package implements the numerical, frozen-evidence and bounded-writer owners
and an explicit production dispatcher. Installing it does not register or
activate a production job. Verified input production is a separate prerequisite.
The database-configured default freezes at 07:30 WIB on Monday to Friday,
selects a facts-only fallback by 07:55 when necessary, and targets delivery at
08:00. Preparation waits until the frozen target before any brief submission.
Weekends are a no-op, with a heartbeat. IDX-only mode also skips exchange holidays.
Engineering documentation is English;
brief prose is concise Indonesian. Model transport, rendering and publication integration remain explicit caller
inputs. The writer and source/calendar/quote adapters perform no network IO.

## Explicit offline inputs

Add `cron-dc-morning-brief/bin` and `lib-sectors/bin` to the caller's module path.
Imports perform no IO. `MorningConfig(run_store_path, sectors_store_path,
mode='cache_only')` requires separate paths and accepts only cache-only or
explicit synthetic-preview mode. It does not load environment credentials or
construct a provider client. `from_mapping` rejects unknown fields.

Sectors consumers must share one explicitly configured private host-local
provider coordination store and billing window. `lib-sectors` owns budgets,
leases, immutable cache versions and request generations. The morning producer owns stable 30-day cap request generations,
separate from other consumers' report generations. A morning run's SQLite database
is separate. Never erase provider state to refresh a snapshot. Select source
cache versions using the run's cutoff before preparing the numerical inputs.
Imported pages create no new reservations and never reveal an account balance.

Canonical retained history may be imported offline through
`sectors_client.import_retained` from the explicit caller-selected private path.
Typed loaders read the retained membership/cap shapes and supplied versioned
konglo CSV directly, recording SHA-256 digests of original bytes. Private payloads
are never copied into this package or committed. The supplied CSV represents
34 groups and 188 unique tickers with intentional overlaps. It does not establish
current ownership. Membership is imported once, with an explicit official-first
check reference for the Sectors IDX-IC fallback, without periodic refresh.

## Authoritative calendar and caps

Delivery-day selection is independent of numerical session verification.
New operator defaults use `delivery_days='weekdays'`, Monday to Friday in WIB,
including IDX holidays. `idx_sessions` preserves the strict trading-day rule;
existing version-1 records without the field retain that rule until explicitly
edited. Both are stored in the revisioned watcher configuration and editable in
Workflows. Frozen records and already published sessions keep their old settings.
Default cutoff and delivery times remain 07:30 and 08:00 WIB.

In weekday mode, an unavailable/stale official calendar or missing input
manifest cannot suppress factual delivery. It removes unverified IHSG facts,
outlook direction, charts and rotations, while independently verified Yahoo
globals and agenda remain usable. An IDX holiday gets a dated holiday notice;
an unavailable calendar gets an explicit verification notice. Weekends emit a
no-op heartbeat without provider collection or a new run. Source lookback uses
the previous publication weekday's actual frozen cutoff when available, or its
configured cutoff otherwise. This is a publication window, never an inferred
market session or a claim of source-history completeness. Recovery keeps all
frozen evidence, configuration, omissions and receipt operations.

`SessionCalendar.from_file(path, expected_version=..., expected_amendment=...,
as_of=...)` imports an explicitly reviewed JSON snapshot with fields:
`version`, `amendment`, `authority='IDX'`, `source_url`, `source_digest`,
`verified=true`, `amendment_checked_at`, `valid_from`, `valid_through`, `sessions`.
The source digest identifies the retained authoritative source; the import digest
identifies the exact snapshot bytes. Sessions must be unique, ordered ISO dates
inside the stated coverage. Verification cannot be future-dated; amendment checks
older than seven days are rejected. This is a conservative local check policy,
not a claim about an official amendment schedule. The caller must verify the
source and check amendments, rather than merely setting the flag.

`cap_refresh_due` checks for a missing snapshot or a snapshot at least 30 days
old. `cap_status` reports `fresh`, `stale` or `future` against the frozen cutoff.
A snapshot remains fresh for less than 30 days from its original collection
instant. Failed or incomplete refreshes retain the last successful snapshot,
with its original date and an explicit stale label after expiry. Unknown cap
effective dates remain `None`. A stale cap never permits stale prices or an
unverified trading calendar. Missing calendar coverage cannot be repaired with
weekdays.

`prepare_numerical_inputs(calendar, membership, caps, prices, benchmark,
through=..., publication_session=..., freeze_at=..., actions=())` requires an
explicit verified publication session matching the freeze's Jakarta date.
`through` must be the immediately preceding verified session and only defines
the closing window. Cap age is assessed at the actual frozen cutoff, independently of calendar
weeks. Cutoff-visible older snapshots remain usable with a stale label. Preparation revalidates publication
calendar coverage and amendment visibility/freshness at the freeze, even when
that calendar object was loaded earlier or later for another caller.
It validates an 18-level aligned benchmark window and cutoff-visible
membership/caps. Missing data raises
`InputUnavailable`. It never fetches a provider or supplies synthetic fallback.
Price eligibility and action compatibility are explicit caller-owned evidence;
positive closes alone are insufficient. `compatible_closes` accepts verified
split-adjusted series or explicitly resolves raw splits exactly once, excludes
dividend additions and fails unresolved/incompatible actions. The sampled DSSA
2680/3120 closes on 8/9 April 2026 agree between retained daily and bulk records;
the fixture preserves that observed compatibility rather than universally
reconstructing shares from cap/price ratios.

## Rotation calculations

`calculate_from_inputs(group_name, inputs)` preserves calendar/amendment,
membership, publication/closing sessions, cap and price/action version identities.
Members with missing/invalid caps or prices are excluded with reasons. At least
one member must have a positive cap and compatible prices in every aligned
session. There is no minimum coverage gate. Weights renormalize over the usable
subset and stay fixed across the whole trail. Partial-basket returns describe
that subset. Coverage uses known original caps as its denominator; unknown-cap
member counts are separate, never represented as zero caps. Partial baskets,
coverage and stale caps are retained in the manifest, not shown in public text or images.

Daily weighted returns compound over ten sessions. X is 100 times the basket
return minus IHSG return; Y is X minus X three sessions earlier. Five positions
require 18 aligned close levels. No price forward fill is allowed. Exact-zero
axes are Neutral; small nonzero coordinates retain their sign. These are
current-cap historical illustrations, not unbiased backtests.

Konglo highlight selection sorts changed quadrant first, then descending
absolute Y and alphabetical name, selecting at most 18 qualifying groups.
Table ordering independently sorts Leading, Improving, Weakening, Lagging,
Neutral; then descending X, descending Y and name. Neutral remains qualifying.
Unselected letters are assigned alphabetically and frozen by the owner, A to P
when 34 qualify and 18 are selected. Numerical results retain the eligible
weights, excluded members, original coverage, aligned closes and action decisions.

## Rotation visual trails

Renderer revision `bursawatch-render-v5` draws display-only cubic curves through
all five observed session markers. Coordinate tangents are bounded by adjacent
steps and zero at reversals, keeping each curve within its segment's observed
coordinate rectangle. No numerical prices, returns, quadrants or frozen
coordinates are smoothed. Direction arrows follow the displayed final tangent.

Sector images retain full-name labels and the 2600 by 1660 logical layout. Konglo
images use compact numbers matching the existing sorted 18-row full-name table;
other groups keep the owner's frozen alphabetical letters. Trails are thinner
and faded, with larger latest markers. The 2600 by 2400 logical layout adds a
separate central zoom panel below the full-range plot, so it never covers
observations. The zoom shows latest positions, with explicitly labelled separate
X/Y ranges based on the 80th percentile of absolute latest coordinates plus
15 percent padding, at least 1 pp and at most that axis's full-range absolute bound. It records
visible and outside groups; all groups remain represented in the full-range
plot/table/letter key. Zoom geometry and marker mappings freeze in the manifest.

Rotation text messages are only the dated heading (`### 🏭 ROTASI SEKTOR: <date>` or
`### 🐉 ROTASI KONGLO: <date>`) followed by the attachment-only image message. Basket
coverage, excluded members, cap collection dates, stale-cap status and basis stay in
the frozen manifest and numerical provenance, not in public text or in the image.
The images omit the coverage caption, the X/Y range line, the curve footnote and the
konglo zoom range subtitle. Revision v5 adds a larger title, date and Bursawatch
mark, a gold inset frame, history dots that are smaller and more faded than the
latest marker, larger right-panel text kept on one line per row (a name shrinks to
fit, and wraps only if it cannot fit at the minimum size), a gold-bordered table with
a gold rule under the header row, and a `LEGENDA` section (`pp = poin persentase`)
below the table. Plot labels, axes and quadrant geometry are unchanged.

Both rotation charts fit independent asymmetric linear X/Y limits to every
visible trail point, including zero and at least 1 percentage point of padding
on each side. Bounds round outward to tenths; tick spacing uses readable decimal
steps. Zero determines the quadrant rectangles and benchmark marker rather than
being fixed at the plot centre. Group count does not control quadrant area.
Full historical trails remain visible, including outliers. The central zoom
stays a separately labelled latest-position panel. Labels may use a nearest
available grid position with a leader when corner clusters exhaust local options.

Rotation geometry, fonts and strokes render directly at pixel ratio 2, without
resizing a completed raster. Sector PNGs are 5200 by 3320; konglo PNGs are 5200
by 4800. Table/marker text is also larger in logical layout units. Other charts
retain their existing native rendering. Manifests declare `logical-pixels`,
logical dimensions and pixel ratio; display bounds and points stay in logical
units while artifact width/height describe the actual PNG. Freeze separate
axis limits, padding policy and zero position with each rendered artifact.

## Durable run state

`RunStore(path)` creates private local state and restart-safe schema version 1.
One run identity/freeze instant exists per session. Active session leases reject
competitors. Expired leases may be recovered with a higher fencing generation;
all freeze/progress/receipt writes check the current lease and expiry.

`freeze(run_id, slot, payload, lease=..., now=..., dependencies=...)` stores
canonical JSON and its SHA-256 envelope, including dependency identities.
Identical retries return the same record. Conflicting payloads/dependencies fail
closed. SQL triggers reject frozen record updates/deletes. Slots are extensible
for numerical inputs, source manifests, evidence, quote/event snapshots, selected
publisher provenance, model/prompt versions, text, image artifact manifests,
rendering/font/logo/profile versions, frozen letters and explicit omissions.
Use JSON-compatible payloads, for example `dataclasses.asdict` results with dates
converted to ISO strings. Artifacts stay in ignored private state outside Git.

Text/image operation slots retain `operation_key` and `digest` for the frozen
transport payload. `append_receipt` requires those matching identities, preserving
immutable receipt observations and acceptance state. Progress checkpoints and
phase/fallback summaries are mutable under the fenced lease, separate from
publication freezes. The Publisher validates Delivery Owner receipts and gates
step dependencies, including text anchors, before submission.

## Frozen evidence and bounded writing

`evidence.freeze_source_evidence(store, run_id, client, previous_cutoff=...,
lease=..., now=...)` consumes `SourceEvidenceClient` from
`lib-bursawatch-control/bin/source_evidence_client.py`. The lower bound is the
previous publication weekday cutoff in weekday mode, or the previous verified
session cutoff in IDX-only mode, including weekend lookback. It freezes
`source_manifest` before any version batch read, then freezes `evidence` with the
manifest slot digest as its dependency. Recovery keeps exact refs/hashes and
never recaptures a changing source query. A complete saved evidence slot is
reused. Missing/corrupt batches freeze facts-only without source mutation/replay.

Selection reads all bounded manifest batches first, then admits only text with
case-insensitive whole-term IHSG, JKSE or JCI aliases, Jakarta Composite Index,
or IDX Composite. Bare Composite and unrelated records are omitted with an
`irrelevant` count before publisher/total caps; this is not a coverage failure.
The current immutable read surface has no reviewed relevance tags, so no tag-only
admission is inferred. Relevant stories sort by publication instant descending
(observation instant when no publication time exists), then event key/version
reference for deterministic ties. Keep at most 30 stories and three per publisher
across routes, preferring recent items for both caps. Exact content hashes or normalized copied
text collapse to one story. Verified original identity is used when available;
otherwise collecting publisher/unknown origin is retained. Missing publisher,
truncated/unavailable text and invalid durable media metadata are explicit gaps.
No selected record establishes independent opinion counts. Late/early capture,
overflow and unknown/unavailable history force facts-only, while independently
valid globals/calendar/numerical facts remain usable.

Capture can never precede its cutoff, so the Control Plane and its client share
one `CAPTURE_GRACE_SECONDS = 120` constant: a capture 0 to 120 seconds after the
cutoff is `on_time`, a larger gap is `late` and facts-only, and the signed
`capture_gap_seconds` stays in the frozen evidence. `freeze_source_evidence`
attempts `capture_window` once. Any capture failure freezes `{'status': 'unavailable'}`
and selects facts-only, including on recovery. Capture has no idempotent snapshot
handle: a repeated request could observe a newly committed transaction whose
creation timestamp precedes the cutoff. This supersedes the earlier two-retry
ruling and agrees with the shared reader contract. The successful first-capture
grace remains a timing policy, not proof of exact cutoff database visibility.

Rollout input: `history_status` is `unknown`, and the run therefore facts-only,
unless the Control Plane is provisioned with
`CONTROL_PLANE_SOURCE_HISTORY_AVAILABLE_FROM` set to a timestamp at or before the
previous session cutoff of the lookback window. Without it the generated outlook
never triggers. This is a separate reviewed Control Plane provisioning input.

`global_markets.parse_yahoo_chart(name, payload, freeze_at=..., retrieved_at=...,
sessions=...)` parses an injected daily Yahoo chart response. `sessions` requires
reviewed regular start/end instants, timezone, version, source digest, verification
time and explicit date coverage, including holidays and daylight saving. There is
no weekday fallback. Names are KOSPI, Nikkei, SPY, QQQ, EIDO and USDIDR, maximum six rows.
Asia uses timestamped open regular metadata or its latest completed session;
SPY, QQQ and EIDO use the latest completed regular US session even during the current
US session. EIDO represents the iShares MSCI Indonesia ETF, not an IHSG index quote.
The prior regular close is the percentage denominator. Indices retain points;
SPY, QQQ and EIDO require USD. SPY is the S&P 500 ETF proxy; its USD
price change is not an S&P 500 index-point change. USDIDR is the USD/IDR pair (`IDR=X`), denominated in
IDR per USD. Its injected session snapshot must explicitly declare
`market_type='fx'` and `baseline_policy='provider_daily_close'`; its reviewed
provider timezone must match quote metadata. FX day windows may cross midnight
and meet at their boundaries, but are ordered, non-overlapping and at most 24
hours each. The producer verifies the provider's daily rollover, weekend/holiday
coverage and previous daily close. No stock-exchange schedule or implicit weekday
baseline is reused for FX. An open FX snapshot compares its timestamped rate with
the immediately preceding verified daily close; a closed window uses its verified
completed daily bar. Missing FX provenance is unavailable. USD/IDR displays signed
IDR-per-USD and percentage changes, with rising rates labeled `IDR melemah` in red
and falling rates `IDR menguat` in green. This states currency direction, not a
predicted or measured causal IHSG effect. Retrieval and price must be cutoff-visible. A missing expected
session bar is stale; missing timestamp/denominator is unavailable. After-hours
metadata does not enter completed-session calculations. Quote delay comes from
explicit `exchangeDataDelayedBy` minutes; absent delay is unknown, never assumed
live. Open quotes older than the stated delay plus five minutes are stale.
`freeze_globals` stores the immutable `globals` slot. `format_global_rows` takes
only supplied actual logo markup, reuses green/red IDs and uses Unicode exact-flat.
No logo IDs are invented. Markdown optionally has explicit hard line breaks.

`economic_calendar.SnapshotCache(path)` stores private content-addressed HTML
bytes once and immutable retrieval/verification/amendment metadata per snapshot.
`put(...)` accepts only the reviewed BPS national Rencana Terbit and BI schedule
URLs listed in `PRIMARY_URLS`; `get(snapshot_digest)` validates retained integrity.
`select_calendar_events(snapshots, freeze_at=...)` validates bounded table fixtures,
not live page extraction. Dynamic empty pages and unknown structures are
unavailable. Verification must be cutoff-visible and at most seven days old,
a conservative owner policy rather than an official release schedule. BI
multi-day decision dates require explicitly verified `decision_day='last'`.
Amendments resolve before future filtering. Explicit shared release IDs with
matching date/time collapse joint BI/BPS briefings before the three-event cap.
Retain both authorities' snapshot metadata and links. Coincident dates or similar
labels alone do not establish joint identity;
only national relevant releases are selected, next three across dates. Unknown
future-date time is labeled; unknown same-day time cannot prove future eligibility.
No consensus or monthly-habit dates are generated. `freeze_calendar_events`
persists original `calendar_snapshots` before `calendar_events`; recovery retains
the old snapshot, never a newer amendment.

`outlook.freeze_bundle(store, run_id, model_version=..., prompt_version=...,
lease=..., now=...)` freezes `writer_bundle` from existing `evidence`, `globals`,
`calendar_events` and optional `inputs` slots with their exact dependency digests.
`write_outlook(bundle, injected_model, now=..., timeout_seconds=30)` accepts the
frozen record and supplies a serialized isolated JSON bundle. The bounded writer
uses `source-scenario-v2`: `{claims, scenario}` only. `claims` permits zero to
three `{evidence_id, excerpt}` exact complete source sentences; their full source
context is also retained, so selecting a later sentence cannot hide prior
negation. `scenario` contains `base_case`, `supporting`, `opposing`,
`change_conditions` and `pulse={optimistic, cautious}`. The base case is one source
reference, role lists contain at most three refs, and change conditions require
at least one. Every scenario ref is `{evidence_id, excerpt}` quoting the **entire
untruncated frozen source text**, at most 600 characters, from at most three
unique source records. Publication/acceptance timestamps must be within the
frozen source window. Base and change-condition contexts must include explicit
sourced conditional language (for example `jika`), otherwise select facts-only.
A ref carries frozen version/hash, publisher, origin status, URL and timestamps
into the result. No generated freeform prose or invented levels are accepted.
Numerical probability statements, including wrapped text, fail facts-only.

Role assignment is the injected model's assessment of attributed source views,
not certification that the publisher holds a particular stance or that commentary
is a verified market fact. The brief says this explicitly. Full quoted contexts
preserve negation and conditions; unsupported roles never introduce extra text.
Missing supporting/opposing evidence is stated unavailable, conflicting source
views state that the session direction is not assured. Narrative role refs form
one section: one available publisher is explicitly a single-source view; multiple
collecting publishers are collected views, never independent consensus. No
qualifying narrative refs omit the pulse. The writer never infers a scenario
from an image, RSI or SMC overlays.

The assessment evidence floor uses the existing runner-produced frozen `inputs`:
`previous_session`, nonempty `benchmark_version`, and a finite positive
`{label: "IHSG close <previous_session>", value, unit: "poin"}` fact.
These fields originate from the exact hash/cutoff-bound `benchmark_attestation`
and the calendar's immediately previous verified session, not an undated `IHSG`
label or positive arbitrary row. At least one fresh dated factual driver must
also exist: a validated frozen global quote with available status and `price_at`
inside the source lookback window, or a verified upcoming national release from
frozen `calendar_events.events`. Pure source commentary does not satisfy this
floor. Inputs below it skip the model with reason `evidence_floor`; no new
producer-only annotation field is required.

Model invocation and support validation share one daemon worker and one
process-wide worker gate. Timeout includes both, with a monotonic budget capped
at the frozen fallback deadline (default 07:55 WIB) and a prebuilt fallback. A still-running worker cannot mutate selected
output or owner state, blocks new model workers rather than accumulating retries,
and never delays interpreter exit through an executor join. Python does not
cancel the external callable; its transport must impose its own request limits.
Results retain `global_facts`, `calendar_facts`, optional deterministic upstream
`market_facts`, bundle digest and model/prompt versions even on writing failure.
The final publication owner must freeze its selected `outlook` before delivery.
For optional numerical fact display, the already frozen `inputs.facts` list uses
`{label, value, unit}` with finite numeric values. This does not certify upstream
price visibility or replace `prepare_numerical_inputs` validation.

## Known scope

The local writer implements the conditional base case, supporting/opposing
source evidence, conditions that change the source view and narrative pulse
through strict grounded structured refs. It does not certify source truth or
provide calibrated probabilities. Longer or incomplete contexts, absent sourced
conditions, unavailable factual-driver/close evidence and oversized final cores
select deterministic facts-only. Fresh verified facts and supported images remain
available. This conservative fallback is visible, not an accepted omission of
the approved core. Live producer permissions, data extraction and injected model
transport remain separate rollout inputs.

Immutable old bundles/outlooks/selections are not rewritten. A legacy run with
no trustworthy mode marker cannot be adopted for either mode; use separate state.
Legacy already-frozen publisher records preserve their text and anchor shape.
New `presentation` freezes the exact selected text and exposed scenario/mode after
budgeting; `outlook` retains the original candidate. `morning_anchor()["scenario"]`
uses `presentation` when present, including `scenario=None` for a published
facts-only fallback, rather than exposing a generated core dropped by formatting.

## Integrated owner and receipt-gated publication

The explicit `collect_public_inputs.py` producer is separate from publication:

```sh
python collect_public_inputs.py --collect-public \
  --runtime-config /private/host-config.json \
  --calendar-snapshot /private/verified-idx-calendar.json \
  --source-cache /private/morning-sources
```

It reads operator timing, delivery days and instruments from the revisioned database,
selects the next eligible publication day whose configured cutoff has not passed, and makes at
most fourteen fixed-origin Yahoo requests (daily and hourly for IHSG and the
configured global instruments). There are no retries, redirects, Sectors or
Chart-IMG requests, source captures, model calls, run-store creation or posts.
IHSG daily history uses `range=1y`; the same retained response supplies both
benchmark facts and the local chart. Other daily/hourly requests keep their
existing one-month windows. A completed history snapshot can be reused for the
same required latest session with its original retrieval/provenance intact.
The explicit private source-cache directory coordinates HTTP and persists a
429 cooldown across process restarts. Honor Retry-After; an absent or malformed
value blocks new requests for 24 hours. No automatic retry occurs.
The private content-addressed source records and manifest versions remain
immutable; only the input-manifest pointer advances. Preparation completed after
the cutoff cannot replace that pointer. Missing latest IHSG close blocks the
strict IDX-mode manifest; weekday mode can retain independently verified globals
and agenda with empty numerical inputs. An unavailable calendar is recorded as
`calendar=null`, without changing any price's source timestamp.

`public_sources.yahoo_sessions` consumes the actual hourly response's
`tradingPeriods` and `currentTradingPeriod.regular`, with strict identity,
timezone, interval, overlap and coverage checks. No weekday, trading-hour or FX
rollover defaults are used. `ihsg_benchmark` verifies the latest completed close
against the immediately preceding official IDX session for independent facts.
It does not independently provide rotation prices, action compatibility or weights.
Missing configured global inputs become explicit unavailable rows, including
when an operator adds an instrument after source preparation.

Optional repeated `--economic-snapshot /private/source-snapshot.json` arguments
attach explicit retained primary snapshots. The existing snapshot integrity,
cutoff visibility and freshness checks still govern them. `SnapshotCache.put`
accepts `source_format='bps-native-flight-v1'` for a verbatim national BPS Arc
`getArcBrs` response. The parser requires native `brs` records, preserves BPS
local release identities, and leaves absent period/time fields unknown. It
never promotes a publication schedule into a statistical release. Native
frontend action discovery and automated BI/BPS retrieval remain producer work.

The producer's `manifest_written=true` only proves that it retained a verified
IHSG facts input. Its output explicitly lists incomplete calendar and rotation
sections, plus the chart when unsupported; it is not a full-brief activation or
delivery-readiness claim.
An official calendar amendment refresh and a scheduled pre-cutoff producer are
still required for an unattended rollout.

### Bounded Yahoo rotation production

The separate `collect_rotation_inputs.py --collect-public` command reads the
same revisioned operator timing and an explicit private `--references` file.
That file contains `sectors` and `konglo` entries with absolute `path`, exact
`sha256`, stable `version` and `source_url`; sectors also requires
`official_check_reference`. Original membership bytes remain private retained
inputs. Keep the imported 11-sector/962-stock universe and the supplied
34-group/188-stock CSV overlaps unchanged.

```sh
python collect_rotation_inputs.py --collect-public \
  --runtime-config /private/host-config.json \
  --calendar-snapshot /private/verified-idx-calendar.json \
  --references /private/fixed-membership-references.json \
  --source-cache /private/morning-sources --request-limit 24 \
  --producer-config /private/morning-producer.json
```

Each pass permits 3 to 64 provider request attempts, default 24, shared between
Sectors cap pages and Yahoo stock history. Configure `--producer-config` with
explicit `sectors_store_path` and `sectors_key_file` paths. They must point at the
same host-local coordination store and credential file used by participating
Sectors consumers. No default credit ceiling is imposed. Missing configuration
omits caps unless this producer already has a successful retained snapshot.

The producer uses `lib-sectors` to collect the structured companies endpoint in
200-row pages, with `sector IS NOT NULL`, `order_by=market_cap` and query values.
Complete pagination, stable totals, unique symbols and native cutoff-visible
sources are required before a new snapshot replaces the last successful one.
One bulk snapshot supplies both sector and conglomerate weights. It stays cached
for 30 days. No per-company overview calls or shares reconstruction are needed
for the verified current membership. Missing/invalid caps remain exclusions.
The compact producer index references an immutable checksum-bound cap artifact;
source pages retain their original availability and hashes in the shared cache.

Refreshes use a caller-owned pending generation that survives incomplete ticks.
Only cache misses invoke the shared client, with `retry=False` and the existing
conservative provider ledger. Failed requests never silently retry or erase
reservations. Reuse the last successful snapshot, even after expiry, and visibly
label its original date and stale status. A blocked/uncertain pending generation
requires explicit provider reconciliation/recovery before it can be retried;
ordinary ticks continue with retained caps. `sectors_request_attempts` counts
cache-miss calls into the shared client, not confirmed provider billing.

Yahoo supplies three-month daily stock responses with native dividends/splits.
`lib-yahoo-market-data` validates all 18 official aligned sessions, ordinary
split-adjusted Close and positive trading volume on every required day. Never
apply splits twice or add dividends; unknown actions exclude that stock. Request
only members with usable caps. Missing members do not prevent a partial basket.
Collection runs after the prior closing date and before the configured cutoff,
without writer, source-capture, run-store or publication calls.

A private producer lock prevents concurrent mutation. Content-addressed Yahoo
records remain immutable; completed and invalid responses are reused for their
closing window. Yahoo calls share the HTTP lock and 429 cooldown with the
chart/global collector. A Yahoo failure stops remaining Yahoo calls in that pass.
A Sectors refresh failure does not stop independent Yahoo collection for retained
caps. Neither publication nor preview rendering performs provider requests.

The producer advances only `rotation-current.json` and retains each manifest
version. Pass this explicit file to `collect_public_inputs.py` using
`--rotation-snapshot /private/morning-sources/rotation-current.json`. It must
match the upcoming publication/closing session, calendar checksum and cutoff;
preview, future or stale windows cannot replace numerical inputs. The runner
assesses caps separately for each basket, preserving mixed snapshot ages and
omitting only unsupported baskets. Manifests do not certify full coverage.

`import_idx_calendar.py --pdf <private-file> --listing-envelope <private-file>
--output <absolute-new-file>` imports retained primary evidence without network
requests or posts. It uses installed `pdftotext` to extract the exact PDF bytes,
requires the complete native IDX `GetAllAnnouncement` response in the envelope,
and binds the PDF's announcement reference to its sole matching attachment.
The complete monthly table, explicit weekend rule, listed closures, twelve
published monthly counts and annual count must reconcile. Missing source rows
never fall back to weekdays. A partial listing or a separate amendment rejects
the base PDF for a separately reviewed amended import. Verification age uses
the listing's actual retrieval timestamp, not the import time. The source PDF,
listing, extracted-text and imported-snapshot digests remain distinct.

This import is repeatable and versioned. It does not automate primary-source
retrieval or waive the seven-day amendment policy. Keep retained primary source
files private and outside Git. Installing the collector/importer does not add
or enable a Hermes job.

`morning_brief.runner.MorningRunner(store, source, delivery, projection, clock=...)`
uses explicit injected clients. `run(calendar=..., numerical=..., global_inputs=...,
calendar_snapshots=..., model=..., model_version=..., prompt_version=..., preview=True)`
is cache-only and no-post by default. `preview=False` additionally requires a
reviewed `destination` and nonempty `reviewed_config` provenance. This gate records
caller intent, not external proof of rollout approval or provider rights.
Before any capture/input work, `run_mode` freezes `preview` or `live`; `upstream`
also records that mode. Mode mismatches fail closed without brief submissions or
recapture. Preview `selection.json` records the actual preview mode and explicit
caller-input provenance, never an invented synthetic/attested assertion.
Optional `logos` maps instrument names to provisioned custom emoji markup. It
freezes in `upstream` and is passed to the formatter; later changes cannot alter
selected text on recovery. Missing or malformed markup retains readable names.
The no-post CLI accepts this mapping in its explicit input manifest.
Direct live injection also waits until the default 08:00 target, including on recovery.
Use the shared SourceEvidenceClient, DeliveryClient and PublicationClient for
reviewed runtime transports; the owner never calls Discord REST directly.

The `numerical` dictionary contains JSON-compatible exact imported `memberships`
(by sectors/konglo), `caps`, `prices`, `actions` and `benchmark`. Price attestations
are indexed by symbol in `price_attestations`; `benchmark_attestation` also needs
an explicit version. Each attestation declares `kind='caller_attestation'`,
`verified=True`, the exact canonical content SHA-256, cutoff-visible
`available_at`, source URL and evidence reference. These are caller evidence,
never derived eligibility or proof from positive rows. Missing evidence excludes
rotation members or the benchmark without substituting prices. All upstream
records, versions and attestations freeze in `upstream` before selection.
`actions_attestation` independently binds the exact complete `actions` list to
the same attestation fields and cutoff before numerical preparation. An empty
list must be explicitly present and verified, not inferred from a missing key.
Absent, unverified, changed or post-cutoff action evidence omits both rotations;
independently supported benchmark facts remain available. A price attestation
does not certify the separate action decisions.

Optional `sectors_client`/`sectors_requests` use the shared client's cache-only
`get` with max_cost zero and retain exact request keys/URLs, payloads, availability
and provenance. No cache miss permits provider access. Optional
`chart_client`/`chart_request` use shared `render(..., cache_only=True)`;
accepted IHSG images require matching external as-of attestation and the
calendar's immediately preceding session. The requested cutoff must equal the
run's exact immutable freeze instant before any cache render; an otherwise valid
same-day request at another time is omitted. Returned artifact request identity
must match the selected request, and the frozen image manifest retains that
identity and cutoff. Unsupported images are explicitly
omitted before publication. Raw global input rows contain name, Yahoo chart
payload, retrieval instant and reviewed exchange sessions. Official calendar
snapshots come from the shared immutable SnapshotCache. Empty calendar/global
inputs remain gaps, not fabricated dates or zero changes.

New IHSG images use `chart.provider='yahoo'` and
`profile_revision='ihsg-yahoo-candles-sma-rsi-v1'`. This profile replaces the
TradingView/LuxAlgo primary for new prepared inputs. The context freezes the
exact daily payload, canonical payload checksum, original source checksum/URL,
retrieval, native regular-period proof and exact cutoff in `upstream`.
`yahoo_chart.prepare_chart` validates the latest completed bar against the
official preceding IDX session and selects exactly the official sessions in
the three-calendar-month window ending on that close. The shared
`lib-yahoo-market-data` parses ordinary OHLC and computes simple MA 10/20/50/100
and Wilder RSI(14) locally. Every visible MA100 value requires 99 preceding
verified sessions; all intervening candles must exist. The chart omits when
calendar coverage, historical warm-up, checksum, completed close or cutoff is
unsupported. Year boundaries may require a calendar spanning the prior year.

`render_yahoo_ihsg` renders a light candlestick/MA panel and RSI panel inside the
dark branded frame, without Volume or SMC/divergence overlays. It retains exact
visible OHLC and indicator values, history sessions, calendar/source digests,
profile and asset revisions in the image manifest. It makes no HTTP requests
and has no Chart-IMG store requirement. A failed Yahoo image never triggers an
automatic provider fallback. Legacy frozen/injected Chart-IMG requests retain
their existing proof and immutable recovery contract.

One bounded writer uses the frozen bundle. Output selection is fixed by the
frozen fallback deadline (default 07:55 WIB), with facts-only degradation on missing evidence, timeout or unsupported
claims. Source-safe URL rendering percent-encodes Markdown delimiters; unsafe URLs
are rejected at source-ref acceptance. Text budgeting removes complete source
claims/citations and optional sections atomically, never cuts a URL. A presentable dated factual-driver block is reserved before selecting the core. An
unrenderable or oversized scenario/core freezes a facts-only `presentation` and
closing anchor. Three exact Indonesian texts and all available image bytes/manifests,
letters, global/calendar facts and omissions freeze under the fenced lease.
The configured defaults freeze at 07:30 WIB and target delivery at 08:00 WIB.
Every brief operation has an immutable attempt deadline (default 08:15 WIB),
including retries. Delayed recovery keeps
the original frozen timing and records actual lateness. Message bodies omit the
cutoff/target timing line in all three sections. Formatter revision
`bursawatch-text-v4` renders the main message as: dated heading; the Indonesian-
formatted last IHSG close with 1D/1W then 1M/3M changes; one `Outlook IHSG`
paragraph; six compact global rows (KOSPI, Nikkei, SPY, QQQ, EIDO, USD/IDR); and
`Agenda Ekonomi Indonesia` with the agenda source links in its header and at most
three dated bullets. Any missing number renders `-`. The message carries no IHSG
or global source links, quote timestamps, delays, missing-data explanations,
pulse/scenario headings or middots. The outlook paragraph keeps each source's
attribution and full conditional context but no link. If the whole paragraph
cannot fit it is replaced atomically with `-`, never clipped. Source URLs, hashes
and timing stay in private run provenance, so a long hidden URL never degrades
the visible text. Image messages are attachments only: publication freezes their
content as empty text, projection sends null text for those legs, and a missing
image leg is skipped. Plot labels inside the images are unchanged.

The IHSG tracker uses `yahoo_market_data.parse_closes` and `close_performance` on
the same retained daily source as the verified benchmark: exactly 1, 5, 22 and 66
verified prior sessions, with a gap kept as a gap instead of sliding to an older
close. The collector attests the tracker hash, cutoff and benchmark equality, and
the runner freezes the tracker only when those checks pass and its latest price
equals the verified close. Native global session proof is built at the actual
collection time, bounded by the configured cutoff, because a future provisional
cutoff can cross into the next Tokyo/Seoul day and reject valid native sessions.
The FX parser ignores null day placeholders, still rejects duplicate non-null
quotes, and uses the latest verified completed native FX day when the live
timestamp is stale.

`publication.Publisher.freeze` persists all six alternating IHSG text/image,
sector text/image and konglo text/image steps before submission. Attachment bytes
are base64 in immutable private RunStore records, with original byte hashes.
They remain retained across durable acceptance and recovery. No staged-media-ref
API or automatic service media TTL is assumed. `publish` validates exact key,
digest, operation ID, status, destination and message receipt, then advances from
matching delivery only. A rejected text anchor blocks its image; pending or
ambiguous images stay unresolved. Missing/corrupt bytes fail closed. Shared
receipt waiting uses DELIVERY_RECEIPT_WAIT_SECONDS (10); that duration does not
extend the attempt deadline or claim cancellation of an earlier attempt.

After expiry, earlier operations may still be queried/reconciled and confirm,
but no absent operation is submitted. The existing Delivery Owner deadline
policy remains authoritative for worker sends and bounded reconciliation.
After every required available receipt, the exact output projection freezes
and submits to the bounded logical `morning_brief` route/type. This route is
metadata, not a selected live channel. Projection outage retries that snapshot
alone. `morning_anchor(run_id)` exposes original selected IHSG text, scenario and
matching receipt for a later closing consumer. Corrected inputs cannot rewrite
prior output. Completed attempts release leases while preserving fencing;
a crashed writer remains fenced until its lease expires.

## Local entrypoint, heartbeat and provisioning boundary

`bin/runner.py` and executable `bin/bursawatch-dc-morning-brief.sh` are no-post
review entrypoints. With no input they emit a simulated no-data heartbeat and
perform no network access or credential loading. For an explicit local preview:

```sh
python cron-dc-morning-brief/bin/runner.py --input /private/retained-input.json \
  --state /private/morning.sqlite --preview-dir /private/morning-preview
```

The input manifest names `calendar_path`, expected `calendar_version` and
`calendar_amendment`, `numerical`, `global_inputs`, `calendar_snapshots`,
`model_version` and `prompt_version`. The CLI uses an unavailable source/model
transport and facts-only output; controlled full integration uses injected fake
or separately reviewed shared clients. `--as-of` is an explicit aware fixture
instant, never a production currentness assertion. Runtime model transport and
its own request deadline remain separate provisioning inputs.

Live heartbeats wait up to the shared `DELIVERY_RECEIPT_WAIT_SECONDS` on the same
operation key when an accepted receipt is nonterminal; they never resubmit for the wait.
Every attempted session, non-session, no-data, degraded and fatal run emits or
simulates the repository heartbeat destination `1505162000420835388` (#hermes).
Shape: `🫀 bursawatch-dc-morning-brief · HH:MM WIB · <safe tokens>[ ⚠️]`;
fatal: `❌ bursawatch-dc-morning-brief · HH:MM WIB · failed: <safe reason>`.
Tokens summarize run phase, cache hits/misses, reserved/spent/uncertain credits,
coverage gaps, selected fallback, image omissions, matching receipt outcome and
actual lateness. Unavailable billing counters stay unknown. An explicit
`accounting` snapshot can supply bounded numeric counters, never an inferred
provider balance. Heartbeats contain no secrets or raw sensitive evidence.
Preview writes heartbeat JSON, exact six-block Markdown, rendered bytes and
manifests to the explicit private directory and contacts no service.

New provider and morning release units remain manual. Manifest registration,
local tests and visual fixture review do not authorize provider requests,
credential provisioning, service changes, destination or schedule activation.
The brief destination is a separate reviewed deployment input.

Provider package-local ignored `.env` files remain canonical main-checkout
inputs with conflict-preserving worktree links; this core reads neither file.
VPS package-scoped credentials, provider/run state paths, source-reader access,
service inputs, scheduler wrapper mode 0755, emoji onboarding, destination and
activation are separate provisioning/deployment approvals. Do not copy Mac state
or credentials to a runtime. No live validation is implied by local fixtures.

## Production dispatcher

The original `runner.py` and `bursawatch-dc-morning-brief.sh` remain explicit
offline previews. `live_runner.py` composes the existing `MorningRunner` with
`SourceEvidenceClient`, `DeliveryClient`, and `PublicationClient`. All APIs are
the established VPS loopback owners. The private host JSON follows
[`runtime-config.example.json`](runtime-config.example.json); it contains paths
to distinct host-local credentials, the private run store, an optional legacy
Chart-IMG store and the independently prepared live-input manifest. Operator timing,
destination, instruments and emojis continue to come from the database.

Run `bursawatch-dc-morning-brief-live.sh --check` first. It reads the current
database configuration, checks private credentials and verified live inputs,
and reports bounded readiness gaps. It does not create a run/provider store,
capture a source window, call a model or provider, or contact Discord. This
check is a baseline input/configuration check, not end-to-end delivery proof.

`--live` is required for a scheduled dispatcher tick. Each tick uses the real
clock and the database timing. It cannot accept `--as-of`, a preview state path
or a different destination. Before cutoff it emits a no-op heartbeat. A first
tick after the last-new-attempt deadline reports a missed session without
freezing a late brief. Existing publication attempts still reconcile under
the original deadline. A persisted publication or upstream snapshot recovers
without reopening changing input files. Its frozen database config also remains
authoritative when the configuration API is unavailable. All source and receipt
recovery remains with the existing owner.

The writer reads the installed Hermes default model/provider and uses its
existing auxiliary client router. It issues one structured request, with a
30-second transport timeout and no SDK retries or tools. The core's fallback
deadline and validation remain authoritative. A changed Hermes model cannot
relabel an already frozen bundle; recovery uses the original writer version
and a facts-only fallback when that model is no longer selected.

The live input manifest has version 1 and `provenance='live-retained'`, with an
aware cutoff-visible `available_at`. It contains `calendar` (`path`, `sha256`,
`version`, `amendment`), `numerical`, `global_inputs`, `calendar_snapshots` and
optional `chart` (Yahoo context or legacy `request`/`verification`). All JSON files must be private
regular files. Numerical, Yahoo and agenda sections use the existing owner
shapes and retain their original independent verification rules. A legacy
chart uses the shared cache and an exact image/request-bound external proof,
verified by cutoff. Its request/proof freeze in upstream before rendering.
New Yahoo chart contexts use the provider/profile/daily/sessions/cutoff shape
described above instead of request/verification. The dispatcher renders them
from frozen data without a provider store. It is never fetched by the
dispatcher. Missing optional images remain explicit
omissions; missing authoritative numerical sessions cannot be repaired by weekdays.
Weekday mode accepts a calendar gap only for independently verified sections,
and discards numerical/chart inputs when its calendar cannot be verified.
Readiness reports these optional gaps while checking destination, credentials
and the installed Hermes runtime. It does not imply full data coverage.

The dispatcher never performs producer HTTP requests or
authorizes paid historical initialization. The separate bounded Yahoo producer supplies 18-session closing data,
memberships, caps, split/action evidence, exchange/FX sessions, official agenda
snapshots and verified chart inputs must be supplied by a reviewed producer before
activation. Provider access failures cannot turn preview fixtures into live
inputs. Unknown source retention continues to select facts-only.

## Verification

### Recurring composition, staged paused

`scheduled_runner.py` requires explicit private `--runtime-config` and
`--producer-config` files and exactly one of `--check` or `--live`. The producer
configuration is version 1 and contains absolute distinct `calendar_snapshot`,
`references`, `source_cache` paths plus optional `economic_snapshots` paths and
a paired `sectors_store_path` / `sectors_key_file`. The pair enables Sectors cap
collection through the shared library; construction is lazy and pre-cutoff only.
It contains no credentials or replacements for database operator timings.
`producer-config.example.json` is a path-only provisioning template, not proof
that those files exist or that primary-source refresh is configured.

Check mode validates retained membership references and the existing dispatcher
readiness without creating stores, HTTP provider requests, model resolution,
source capture or posts. Live mode takes a private exclusive process lock.
Before the configured cutoff on a verified session, it runs one bounded rotation
chunk per tick. In the last ten minutes it also refreshes the global/benchmark
manifest, including eligible retained rotation and agenda inputs. After cutoff
it invokes only the existing dispatcher. Frozen recovery bypasses producers
and a changing configuration API. The same database configuration snapshot
governs the first dispatch; it is not fetched twice across a timing change.
Strict IDX mode produces a no-op heartbeat on non-sessions, and a fatal
heartbeat for a missing/stale calendar. Weekday mode skips weekends, omits
rotation preparation without a verified trading session, and still prepares
global/agenda inputs near cutoff. No mode extends calendar verification or
infers numerical sessions from weekdays.

`bursawatch-dc-morning-brief-scheduled.sh` is the reviewed dispatcher wrapper for the exact
`bursawatch-dc-morning-brief` runtime job name. The source schedule is a paused
60-second interval in manual migration 024 and the reconciler allowlist.
Default cutoff/delivery remain 07:30/08:00 WIB. Jobs controls can change desired
enabled state; morning timing, instruments and logos remain in its watcher
configuration. The minute interval itself is fixed so the source-capture
on-time grace is meaningful.

Hermes command jobs do not forward script arguments. Their explicit live
entrypoint is `bursawatch-dc-morning-brief-job.sh`, installed under
`~/.hermes/scripts/` at mode 0755. It accepts no arguments and invokes the
scheduled wrapper with `--live`. Register this one job with `--no-agent
--deliver local`; the morning owner performs any bounded model call internally
and exclusively delivers through the shared Delivery Owner. Hermes must not
forward the command's JSON stdout into a Discord channel. Manual no-post checks
continue to use the scheduled wrapper with `--check`.

Installing the wrapper at mode 0755, registering a paused Hermes command job,
applying the manual migration and reconciler code, checking source/input
readiness, and enabling the authenticated desired schedule are separate reviewed
rollout steps. Do not hand-edit the registry or manually trigger a live run.
Verify the next natural preparation and receipt-gated delivery. No paused row,
successful check, local preview or component health check substitutes for that
evidence. Official calendar/agenda acquisition must be resolved independently;
the scheduler does not make unavailable primary sources fresh.

Run `python -m pytest -q cron-dc-morning-brief/tests` with the repository
interpreter. The analytical fixtures explicitly use synthetic sessions/prices.
The private retained cache has four complete sessions and one partial session,
which is insufficient for an 18-level rotation trail. Retained cache gaps must
remain gaps. Run `bash scripts/test-all` after touched package suites. Deployment review is
separate; natural source-to-visible-delivery verification requires a separately
approved rollout and cannot be established by these offline tests.


## Durable operator configuration

The Control Plane registers `bursawatch-dc-morning-brief` as a configuration-only
watcher. Migration 023 adds no scheduler entry. Its absent-only baseline seeds
version 1 into the existing private Postgres configuration revisions, preserving
any dashboard-authored revision. The baseline has no destination and cannot
publish until a channel and host runtime are separately reviewed.

Workflows in web config exposes cutoff and delivery in WIB, fallback lead time
(1 to 30 minutes), the new-attempt grace after delivery (1 to 60 minutes), a
nullable Discord destination, the six supported global instruments and nullable
custom emoji mappings. The approved instrument IDs live in the private backend
baseline, never in browser bundles. Keys and HH:MM values are validated by the
canonical owner parser; the isolated Control Plane bundle has byte-parity tests.
The fixed timezone is Asia/Jakarta. Require cutoff before fallback before target,
with the attempt deadline on the same date. Scheduler enablement/cadence stays
in Jobs and requires a separately provisioned job; saving settings cannot create
or activate it.

A host adapter calls `MorningRunner.run_from_control_plane(base_url=..., token=...,
**inputs)` using the shared `control_plane_client.fetch_config`. Configuration
read or checksum failure stops work; it never falls back to source defaults.
Credentials stay in host configuration, outside operator settings. The adapter
must inject the existing shared `SectorsClient`, shared `ChartImgClient`, source
reader, Delivery Owner and publication client with their reviewed host stores and
provider policies. Configuration cannot authorize provider spend or bypass
calendar/image verification. The Sectors and Chart-IMG caches/allowances remain
separate and account-shared, never duplicated in morning state.

`run_from_snapshot(snapshot, **inputs)` accepts a retained shared API snapshot
for no-post review. The CLI input manifest supports `config_snapshot` for this
purpose. Before data capture, freeze the snapshot revision, checksum and values
in `operator_config`. Capture, selection, writer fallback, attachment captions,
last-attempt deadlines and lateness use that record. Restarting after a dashboard
edit resumes the same settings and destination. The previous eligible publication day's
actual frozen cutoff bounds the next source window when available, preventing a
cutoff edit from skipping source history. Missing original history still degrades
honestly. Legacy explicitly injected local callers retain their old 07:30/08:00
contract; do not promote those sessions into the database-backed runtime.

This configuration implementation does not activate the separate Yahoo producers or supply live BI/BPS acquisition,
verified IDX calendars, shared provider stores, TradingView layouts or host
credentials. Complete numerical output needs its verified inputs; factual
weekday delivery may omit unavailable sections. Reviewed schedule activation
and the first natural delivery remain rollout gates. No synthetic post validates them.
