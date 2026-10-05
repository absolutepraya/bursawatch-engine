---
name: bursawatch-dc-morning-brief
description: Proposed receipt-gated IHSG morning brief with frozen evidence and fixed-cap rotation illustrations.
---

# Morning brief contract

This local package implements the numerical and durable input owner for a
proposed morning brief. It does not register or activate a production job.
The planned schedule freezes at 07:30 WIB on verified IDX sessions, selects a
facts-only fallback by 07:55 when necessary, and targets publication by 08:00.
A non-session is a no-op, with a heartbeat. Engineering documentation is English;
brief prose is concise Indonesian. Model invocation, evidence selection,
formatting and publication integration are subsequent owner modules.

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

`prepare_numerical_inputs` validates an 18-level calendar window, aligned
benchmark, cutoff-visible membership/caps and cap age. Missing data raises
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
membership, cap and price/action version identities. Every original member needs
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
publication freezes. Subsequent integration must validate actual Delivery Owner
receipts and gate step dependencies, including text anchors, before submission.

## Planned heartbeat and provisioning boundary

The later runner must emit a heartbeat for each attempted session, no-op,
degraded and fatal run to `1505162000420835388` (#hermes). Planned shape:
`🫀 bursawatch-dc-morning-brief · HH:MM WIB · <safe tokens>[ ⚠️]`;
fatal: `❌ bursawatch-dc-morning-brief · HH:MM WIB · failed: <safe reason>`.
Tokens summarize phase, cache hits/gaps, reserved/spent/uncertain credits,
coverage, fallback, explicit image omissions and matching receipt state.
No secrets or raw sensitive evidence belong in heartbeats.

The brief destination is a separately reviewed input, never implicitly chosen.
Shared Discord Delivery Owner is the sole REST path. Shared Control Plane owns
source reads and confirmed output projection. A six-step publication manifest,
attachment retention, receipt gates and projection recovery belong to integration.

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
remain gaps. Full repository checks and deployment review occur at final
integration; natural source-to-visible-delivery verification requires a separately
approved rollout and cannot be established by these offline tests.
