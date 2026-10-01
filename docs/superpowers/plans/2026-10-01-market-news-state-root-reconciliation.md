# Telegram Market News State Root Reconciliation Plan

> **For agentic workers:** Follow the package and repository production
> release gates below. Do not run manual schedules or send test messages.

**Status:** Approved by the user on 2026-10-01; amended on 2026-10-01 to keep
the cutover forward-only. The source-runner canonical-path fix and original
reconciliation shipped through
[PR #33](https://github.com/absolutepraya/bursawatch-engine/pull/33). The
Phintas route follow-up also merged. A fresh production snapshot at
2026-10-01 16:08 WIB showed `origin/main` and the successful release at
`c955b7a8da6f6d4f439035270dd0b2f1b9588261`, with the release agent unblocked.
At that snapshot, the shared Telegram source reader was paused at desired
revision 8, applied revision 8, at its existing one-minute interval. The state
archive and state apply below have not been performed. A new package-owned
Delivery Owner preflight repair is implemented locally but is not yet
published or released.

**Workstream authorization:** The user has authorized the actions reasonably
needed to complete this Bursawatch ingestion repair without requesting separate
approval for each action. This includes opening and merging pull requests,
deploying reviewed fixes, pausing and resuming the affected existing job through
the supported scheduler interface, and applying the reviewed production state
plan. Repository and package release gates and every plan precondition still
apply. Do not replay or backfill historical items or send stale news.

**Goal:** Put Telegram source-work acceptance, Market News agent leases, and
classification submissions on one durable owner ledger while preserving
terminal history, dedupe, and confirmed delivery records. Do not deliver any
pre-cutover pending Market News work. The cutover keeps future intake live
without replaying stale news.

**Trigger:** The natural runs after catalog recovery proved intake works, but
Market News submissions still failed. The source runner launches
`pipeline_owner.py` directly. Without `IDX_MARKET_NEWS_STATE_PATH`, that process
uses the deployed skill's package-local `state.json`. The submission wrapper
selects `~/.hermes/state/idx-market-news.json`.

**Verified at 2026-10-01 11:45 WIB:** Both Telegram source cursors had advanced
through the latest inspected messages (`tuntunsekuritas` 15058 and
`phintasprofits` 35552). The package-local file contained 69
source-provenance candidates; all 69 keys also existed in canonical state, and
two overlapping keys had different phases. Canonical state contained 83
active candidates, all published before 2026-10-01: 82 `pending_analysis` and
one `awaiting_agent`, spanning 2026-09-28 to 2026-09-30. It had no candidate
in `pending_delivery`. The package-local file had 69 active candidates. Any
merge that leaves those phases runnable could deliver old news after the path
fix, so the reviewed apply now marks every active candidate abandoned before
the schedule resumes. It refuses unresolved candidate or stock-status
delivery operations. The package-local source file remains untouched and
archived.

The read-only Discord history review covered 62 `#id-stocks-news` messages
from Sep 25 through Oct 1 10:44 WIB and 8 `#id-industry-news` messages from
Sep 25 through Sep 29 14:21 WIB. Telegram still had Oct 1 Tuntun and Phintraco
posts. Tuntun message 15053 (Sep 30 18:26 WIB) produced three Industry
candidates that remain `pending_analysis`; message 15054 produced four
Corporate candidates but omitted its BRIS entry because the company name has
nested parentheses. Phintraco message 35549 (Oct 1 08:21 WIB) was rejected as
`invalid_status`: its effective date says `01 Oktober 2026`, while the parser
accepted English month names only. These parser fixes are forward-only; the
advanced source cursors will not replay those old posts.

**Observed at 2026-10-01 09:51 WIB:** The package-local file contained 69
source-provenance candidates, 68 `pending_analysis` and 1 `awaiting_agent`.
The canonical file contained 688 candidates, 30 `pending_analysis`, 1
`awaiting_agent`, and no source-work provenance. Thirty-one keys existed in
both files with identical candidate payloads and different phases; 38
package-local keys had no canonical counterpart. The source-local file had
retry history through attempt 20. Refresh all counts and both file digests
before any apply.

A later preliminary comparison, read while source-ingest was still active,
found four package-local Phintraco stock-status event records. All four keys
also existed in canonical state and their source identity and parsed payload
matched. Events `35454` and `35549` were rejected in both files. Events
`35484` and `35522` were `pending_delivery` locally and already `delivered`
canonically. The canonical delivered records have owner receipts and remain
authoritative. The local versions include `source_event_key` and
`config_revision`, which the canonical versions lack. Refresh this comparison
after writers are paused; the preview must report four overlaps and preserve
canonical delivery outcomes, handoffs, and receipts while adding only matching
source provenance that is absent. The apply then abandons every nonterminal
candidate so this migration cannot send pre-cutover news.

## Scope and ownership

- `cron-tg-market-news` owns validation and migration of its durable candidate
  ledger. `cron-tg-source-ingest` owns passing the configured canonical path to
  its direct Market News owner subprocesses.
- Use only the canonical production owner file at
  `~/.hermes/state/idx-market-news.json` as the merge destination. Treat
  `~/.agents/skills/bursawatch-tg-market-news/state.json` as a source of
  accepted candidate records, not as the long-term owner ledger.
- Preserve both complete input files in the private runtime-cutover backup.
  Never delete, truncate, reset, replay, or copy the package-local file over
  the canonical file.
- Keep the cutover forward-only: abandon all nonterminal candidates in the
  merged canonical ledger before resuming source-ingest. Do not submit them to
  the classifier or Delivery Owner. Preserve the complete package-local file
  and the canonical terminal history in the verified archive/state.
- Keep runner ordering, catalog routing, candidate classification policy,
  destinations, and delivery operation keys unchanged.
- Do not manually trigger a production job or send a test post.

## Merge contract

Add a package-owned preview/apply command that reads both regular `0600`
non-symlink state files with migration disabled and validates each with the
existing owner schema. Preview is read-only and writes a private plan outside
both state roots. The plan records input SHA-256 values and aggregate counts,
not source text, URLs, classifications, or credentials. Apply must re-read
both files and reject any hash, schema, or path change since preview.

For every candidate with a `news_source_work` provenance record in the
package-local file:

1. Require exactly one valid candidate record and valid provenance for that
   key. Reject orphan provenance, unsupported phases, or malformed records.
2. If the candidate key is absent from canonical state, import the complete
   candidate record and its validated source-work provenance.
3. If the key exists in canonical state, require the candidate payloads to be
   identical. Preserve the complete canonical candidate record while merging,
   including its phase, lease, retries, classification, selection, and
   delivery history. Add the source-work provenance only if canonical state
   has none. If canonical provenance exists, require its immutable event
   identity, version, content hash, source URL, enabled capabilities, and work
   keys to match; preserve the canonical frozen config snapshot. The separate
   forward-only apply step below then terminally abandons every nonterminal
   candidate, keeping its content and classification history intact.
4. Reject every payload or provenance conflict. Do not choose a winner by
   timestamp, retry count, or phase. The source-local overlap remains intact
   in the archived input for diagnosis.
5. Preserve all other canonical top-level fields and stats, including provider
   cursors, `dedupe`, `digest_windows`, stock-status events, publication
   intents, and existing source provenance. Candidate records change only
   where the forward-only step clears an active lease and retry deadline,
   records its reason, and sets the phase to `abandoned`.

For `stock_status_events` in the package-local file, require valid owner-schema
records. Import a source-only terminal event with its complete record. For an
overlapping event, require equal source message ID, URL, effective date, all
five parsed categories, channel, content, and any shared rejection outcome.
Preserve the canonical phase, retry state, delivery handoff, and receipt. Copy
`source_event_key` and `config_revision` only when canonical state lacks them;
reject conflicting values. Block if canonical state contains a pending stock
status delivery or if an unresolved source-only delivery would be imported.
Count source, new, overlapping, phase-different, and provenance-enriched
events in the private plan and apply receipt. An existing receipt proves
idempotence only while every source candidate, provenance record, status event,
and optional status-event provenance field is present in canonical state.

The apply step records `active_candidate_abandonment_count` in the exact plan.
It marks every nonterminal candidate in the merged canonical state `abandoned`
with the package-owned forward-only cutover reason before saving. This includes
source-only candidates imported by the merge. Reject any candidate or status
event with unresolved `pending_delivery`; those operations must be checked with
the Delivery Owner and a fresh plan before this cutover. Reapplying the same
plan is idempotent only when its receipt matches, all imported provenance is
present, and no active candidate remains. The immutable source file may retain
a pending phase for an overlapping candidate that the matching receipt proves
was already abandoned in canonical state.

The source file must contain only the reviewed source-work and status-event
ledgers plus the exact completed immediate-delivery marker. Nonempty source
dedupe, digest windows, provider cursors, runtime timestamps, or any other
stats ledger block preview. The canonical immediate-delivery marker must be
complete. These checks prevent silently omitting package-local owner state.

Apply the merged state through the package's validated atomic save path. Add a
small migration receipt to canonical state with version, input digests,
counts, and timestamp so a repeated apply can prove it already completed
without duplicating candidates. Validate the output and receipt before
returning success. Leave the package-local input byte-for-byte unchanged.

## File map

- Create `cron-tg-market-news/bin/reconcile_source_ingest_state.py` for
  preview, merge validation, atomic apply, and idempotent receipt handling.
- Update `cron-tg-market-news/bin/state.py` to expose validated atomic save
  without legacy auto-migration for this one state merge; default callers keep
  their existing migration behavior.
- Extend `cron-tg-market-news/tests/test_state.py` to pin the default and
  migration-disabled atomic save contracts.
- Create `cron-tg-market-news/tests/test_source_ingest_state_reconciliation.py`
  for source-only imports, identical-key overlaps with different phases,
  matching and conflicting candidate and status-event provenance, malformed
  or orphan records, unsupported source ledgers, changed preview inputs,
  atomic-write interruption, and complete idempotent re-apply.
- Extend `cron-tg-market-news/bin/stock_status.py` to parse Indonesian and
  English effective-month names, including `Oktober`; cover the live rejected
  message shape without causing it to be replayed.
- Extend the Tuntun Corporate ticker-line parser to accept nested parentheses
  in legal names; cover the omitted BRIS candidate shape without replaying the
  original message.
- Retain the source-runner environment fix in
  `cron-tg-source-ingest/bin/runner.py`; it gives source acceptance,
  `agent-status`, and `claim-agent` the same default canonical path while
  preserving an explicit override.
- Update the affected `AGENTS.md` files, the Market News README or contract if
  needed, this incident review, and `docs/README.md` in the same change.

## Implementation sequence

1. Add pure merge planning and regression tests. Prove canonical candidate
   records and all unrelated canonical state remain unchanged in preview.
2. Add guarded `preview` and `apply` CLI commands. Require an exact plan,
   unchanged source and target digests, safe file modes and paths, and valid
   owner state. Fail closed on every unresolved collision.
3. Test the source-runner canonical-path fix and the reconciliation package
   together. Run the focused suites, the package suites, and repository suite.
   Review affected package and repository Markdown contracts.
4. Publish through the normal exact-main CI and release gates. Verify the
   deployed source-runner checksum and its isolated no-post result before any
   state operation.

## Task 1: Resolve canonical pending candidate outcomes without sending

The first live preview against the released reconciliation command failed
closed because canonical state contains candidates in `pending_delivery`.
Read-only Delivery Owner lookups found two cases:

- Phintraco message `35557` has a persisted exact delivery payload and
  accepted handoff. The deterministic operation is `delivered`, and the
  returned digest matches the stored payload.
- Tuntun message `15063` has no persisted delivery payload or handoff. Its
  deterministic operation lookup returned `not_found`. This proves no current
  Delivery Owner operation exists for that candidate, but it does not identify
  why the candidate reached `pending_delivery` before the payload was saved.
- Two package-local Stock Information records overlap canonical events whose
  operations are already delivered with matching digests. The canonical
  outcomes remain authoritative.

Update the package-owned reconciliation preview and apply so they perform
status-only lookups for canonical `pending_delivery` candidates. Require a
matching terminal `delivered` receipt and digest when an operation exists. A
`not_found` result is safe only when canonical state has no accepted handoff or
Discord message ID. Persist only aggregate counts and a fingerprint of the
status outcomes in the private plan. Apply must repeat the lookups and stop if
any outcome changed. It must never submit, wait, or mutate the Delivery Owner.
Pending canonical stock-status delivery remains a separate blocking condition.

Review focus:

- Exact operation key and digest reconstruction from the frozen payload.
- Accepted legacy handoffs may use `reconcile_before_first_create` and the
  persisted legacy nonce; preview and apply must reconstruct that exact
  operation shape when its saved receipt proves it.
- Missing payload plus `not_found` versus missing payload plus an existing
  owner operation.
- Accepted local handoffs, mismatched receipts, pending remote receipts,
  failed lookups, and status changes between preview and apply.
- Any confirmed local Discord message ID or delivered saved handoff receipt
  must match the Delivery Owner's confirmed message ID before reconciliation
  can replace or preserve that evidence.
- Preservation of confirmed remote receipts before forward-only abandonment.
- Idempotent reapply when the unchanged source file retains a pending phase
  that this same plan already abandoned canonically.
- No Delivery Owner submit or wait calls on the preview/apply path.

Expected checks:

- Focused reconciliation tests cover delivered, not-found, mismatch, changed
  status, legacy accepted operations, confirmed message-ID conflicts,
  fail-closed behavior, idempotent reapply, and canonical stock-status
  blocking.
- The Market News package suite and `bash scripts/test-all` pass.
- `git diff --check` passes.
- Documentation says that candidate outcomes are checked read-only, while
  unresolved canonical stock-status deliveries remain blocking.

The plan has no separate design spec; this plan contains the approved design
and implementation contract.

## Separately approved production operation

After the source and target paths are refreshed and the approved preview is
reviewed:

1. Run a fresh production snapshot. Read both current state files using the
   package-owned read-only preview and confirm their modes, hashes, candidate
   counts, provenance counts, overlapping payloads, phase differences, lease
   expiries, stock-status event identities, phases, receipts, and provenance.
   Inspect the supported Hermes job definition for an explicit
   `IDX_MARKET_NEWS_STATE_PATH` override. The earlier counts are expectations
   only, not apply inputs.
2. Pause the existing Telegram source-ingest schedule through the supported
   scheduler interface. Prove no run is in flight and no Market News owner
   process or state lock remains. Confirm the legacy Market News watchdog is
   still paused. Wait for any outstanding two-minute agent lease to expire or
   complete before applying. If the live job has an explicit noncanonical
   path override, stop and review that exact config change before proceeding.
3. Archive both complete state files and SHA-256 inventories under
   `~/backup/hermes/runtime-cutovers/<YYYY-MM-DD>/bursawatch-tg-market-news/`.
   Verify the archive against the quiescent files. Preserve it for at least 30
   days.
4. Produce and review a fresh merge preview. Confirm every package-local
   source-provenance key is either a new canonical candidate or an identical
   payload overlap, there are zero unresolved conflicts, and the preview's
   `active_candidate_abandonment_count` covers every active candidate. Confirm
   every canonical pending candidate has either a matching delivered receipt
   or a not-found result with no local accepted handoff, and confirm there are
   no unresolved canonical stock-status deliveries.
5. Apply the reviewed plan while the writer remains paused. Verify all
   source-work provenance is present in canonical state, every formerly active
   candidate is `abandoned`, terminal canonical records and delivery receipts
   are unchanged, source-only candidates were added exactly once and are also
   abandoned, canonical status-event phases and receipts are unchanged, source
   status-event provenance is complete, and the source file is unchanged.
6. Resume the existing one-minute schedule through the supported scheduler
   interface. Observe natural runs only. Confirm new source acceptance,
   agent claims, and classification submissions use the canonical file. Only
   source events accepted after this forward-only boundary may enter analysis
   or delivery. Distinguish owner progress from confirmed Delivery Owner
   receipts.

If preview, archive verification, deployment, or apply fails, keep the
schedule paused after the pause step and stop before resuming. Do not restore
an archive over a live writer. Resolve the failure from the recorded hashes
and exact plan, then re-preview before retrying.

## Acceptance evidence

- Both source-work and agent-control subprocesses select
  `~/.hermes/state/idx-market-news.json` by default, and explicit test
  overrides still work.
- The package-local source state remains unchanged and archived.
- All valid source-work provenance is present in the canonical owner ledger.
- No pre-cutover active Market News candidate is sent; each is durably
  `abandoned` with a reason before the first resumed run.
- No unresolved pending-delivery operation is hidden by abandonment or
  reconciliation.
- All package-local stock-status events are present or overlap canonically with
  matching payloads, canonical delivery outcomes remain intact, and missing
  source-event provenance is added where validated.
- Existing terminal candidate phases, dedupe entries, confirmed delivery
  intents and receipts, provider state, and unrelated stats are preserved.
- Natural runs complete the source acceptance and classification handoff
  without candidate-not-in-durable-state or candidate-not-awaiting failures,
  and do not process work from before the forward-only boundary.
- A confirmed Discord receipt is required to claim delivery. Schedule health,
  a clean heartbeat, or an accepted source event alone is insufficient.
