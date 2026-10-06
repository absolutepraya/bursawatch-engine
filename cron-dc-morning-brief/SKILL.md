---
name: bursawatch-dc-morning-brief
description: Proposed receipt-gated IHSG morning brief with frozen evidence and fixed-cap rotation illustrations.
---

# Morning brief contract

This local package implements the numerical, frozen-evidence and bounded-writer
owners for a proposed morning brief. It does not register or activate a production job.
The database-configured default freezes at 07:30 WIB on verified IDX sessions,
selects a facts-only fallback by 07:55 when necessary, and targets delivery at
08:00. Preparation waits until the frozen target before any brief submission.
A non-session is a no-op, with a heartbeat. Engineering documentation is English;
brief prose is concise Indonesian. Model transport, rendering and publication integration remain explicit caller
inputs. The writer and source/calendar/quote adapters perform no network IO.

## Explicit offline inputs

Add `cron-dc-morning-brief/bin` and `lib-sectors/bin` to the caller's module path.
Imports perform no IO. `MorningConfig(run_store_path, sectors_store_path,
mode='cache_only')` requires separate paths and accepts only cache-only or
explicit synthetic-preview mode. It does not load environment credentials or
construct a provider client. `from_mapping` rejects unknown fields.

All Sectors consumers must share one explicitly configured private host-local
provider coordination store and billing window. `lib-sectors` owns budgets,
leases, immutable cache versions and request generations. Weekly caps use a
caller-owned generation such as `caps:2026-W41`. A morning run's SQLite database
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

`cap_refresh_due` is true only on the first verified session of a week.
`cap_status` uses complete verified calendar weeks, including holiday amendments:
current week, one extra preceding week, expired or future. Snapshot collection
time is retained; the companies screener's underlying cap effective date is
unverified and remains `None`. Missing calendar coverage cannot be repaired with
weekdays. Expired caps omit unsupported rotation.

`prepare_numerical_inputs(calendar, membership, caps, prices, benchmark,
through=..., publication_session=..., freeze_at=..., actions=())` requires an
explicit verified publication session matching the freeze's Jakarta date.
`through` must be the immediately preceding verified session and only defines
the closing window. Weekly cap age is assessed against the publication session,
so a fresh first-session cap snapshot is valid before the freeze while a snapshot
from two publication weeks ago is expired. Preparation revalidates publication
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
Every original member needs
a valid positive cap. Eligible members must have compatible prices in every
aligned session and cover at least 90 percent of original basket cap. Weights
renormalize over eligible caps and remain fixed across the whole trail.

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
previous verified session cutoff, including weekend/holiday lookback. It freezes
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
the original visible cutoff/target labels and records actual lateness.

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

## Verification

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
calendar/image attestations. The Sectors and Chart-IMG caches/allowances remain
separate and account-shared, never duplicated in morning state.

`run_from_snapshot(snapshot, **inputs)` accepts a retained shared API snapshot
for no-post review. The CLI input manifest supports `config_snapshot` for this
purpose. Before data capture, freeze the snapshot revision, checksum and values
in `operator_config`. Capture, selection, writer fallback, attachment captions,
last-attempt deadlines and lateness use that record. Restarting after a dashboard
edit resumes the same settings and destination. The previous verified session's
actual frozen cutoff bounds the next source window when available, preventing a
cutoff edit from skipping source history. Missing original history still degrades
honestly. Legacy explicitly injected local callers retain their old 07:30/08:00
contract; do not promote those sessions into the database-backed runtime.

This configuration implementation does not supply live Yahoo/BI/BPS adapters,
verified IDX calendars, shared provider stores, TradingView layouts or host
credentials. Those are production rollout gates, as are reviewed schedule
activation and the first natural delivery. No synthetic post validates them.
