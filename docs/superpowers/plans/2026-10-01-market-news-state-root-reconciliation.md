# Telegram Market News State Root Reconciliation Plan

> **For agentic workers:** Follow the package and repository production
> release gates below. Do not run manual schedules or send test messages.

**Status:** Approved by the user on 2026-10-01; amended on 2026-10-01 to keep
the cutover forward-only. The source-runner canonical-path fix and original
reconciliation shipped through
[PR #33](https://github.com/absolutepraya/bursawatch-engine/pull/33). The
Phintas route follow-up also merged. PR #36, which adds the guarded
Delivery Owner preflight repair, merged to `main` at 2026-10-01 16:47 WIB as
`32c7ccd158479bcf90dd33f2a7c587d0c32943ef`.
PR #37, which restores legacy receipt compatibility and adds guarded
`finalize_legacy` handling, merged at 2026-10-01 18:23 WIB as
`4e6db9ce97bd651926c7b6aaff1b936aa2e4d861`.

**Pre-release snapshot at 2026-10-01 18:24 WIB:** `origin/main` was
`4e6db9ce97bd651926c7b6aaff1b936aa2e4d861`, while the last successful VPS
release was `32c7ccd158479bcf90dd33f2a7c587d0c32943ef`. Telegram source-ingest
was paused at desired/applied revision 8. This was a pre-release observation.

**Latest production snapshot at 2026-10-01 19:12 WIB:** `origin/main` and the
successful VPS release both equal `4e6db9ce97bd651926c7b6aaff1b936aa2e4d861`;
the exact-main release CI state is `success`, the release agent is unblocked,
Hermes is running, and all 8 desired interval schedules match. There are 13
jobs (8 active, 5 paused). Telegram source-ingest is active at desired/applied
revision 9 and its existing one-minute interval. The legacy Market News reader
and watchdog remain paused at revision 6. The X account watcher still reports
`last=error`, while its queue job, WhatsApp, and Stockbit report `last=ok`; these
labels do not establish delivery. This snapshot proves release and schedule
state only, not source-to-delivery completion.

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

## Original production reconciliation and receipt regression

The original version-1 reconciliation was applied at 2026-10-01 13:46:32 WIB,
while Telegram source-ingest was paused. Its receipt records 81 source
candidates/provenance records, 12 new candidates, 69 overlaps, four stock
status events, two provenance additions, and 95 active candidates abandoned.
The original private plan and version-1 receipt still match. The original
archive under
`~/backup/hermes/runtime-cutovers/2026-10-01/bursawatch-tg-market-news/`
passes its SHA-256 manifest. The package-local source file remains byte-for-byte
unchanged at digest
`c9ed4604e89ccd5c5bce71b0a8d4477d3fcb554141134844f47e76162e25d27d`.

PR #36 then introduced a stricter pending-delivery receipt schema but kept the
receipt version at 1. The deployed state reader therefore rejected the
already-applied legacy receipt as malformed. The first apply did happen; this
is a later backward-compatibility regression. Do not repeat the original merge
or overwrite its archive.

The approved code follow-up accepts both exact old version-1 and new version-2
receipt schemas. Plan version 3 has two explicit modes. `merge` is for state
with no prior receipt. `finalize_legacy` requires the original version-1 plan
and receipt to match, verifies every source candidate and provenance record is
already imported and each matching canonical candidate is terminal, then
resolves every canonical pending delivery with read-only Delivery Owner status
checks. It preserves
confirmed delivery evidence, abandons only verified `not_found` pending
candidates, and stores the prior receipt and plan digests in the new receipt.
It does not repeat the import or change the source file.

The current pending outcomes are Phintraco message `35557`, confirmed
`delivered` with a matching stored digest and message ID, and Tuntun message
`15063`, `not_found` with no saved handoff or Discord ID. Finalization must
reconfirm the exact outcomes during preview and apply. It must not post either
item or any other pre-boundary candidate.

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

## Guarded production finalization

The original archive and version-1 plan/receipt are immutable evidence. Before
the follow-up state write:

1. Run a fresh production snapshot and verify the exact released SHA and
   existing schedule revisions. Keep shared Telegram source-ingest, the legacy
   Market News reader, and its watchdog paused.
2. Prove there is no run in flight, Market News owner process, open state lock,
   or live candidate lease. Confirm the scheduled job still has no explicit
   `IDX_MARKET_NEWS_STATE_PATH` override.
3. Archive the complete current source and canonical files with a new
   SHA-256 manifest in a unique subdirectory beneath
   `~/backup/hermes/runtime-cutovers/2026-10-01/bursawatch-tg-market-news/`.
   Verify both archived files against the quiescent live files. Keep both this
   recovery point and the original archive for at least 30 days.
4. Run the deployed version-3 `preview` with the original version-1 plan named
   explicitly. Review the private plan before apply. It must say
   `mode=finalize_legacy`, show zero new imports or provenance additions,
   confirm all 81 source candidates and provenance records are present in
   canonical state, their canonical candidate records are terminal, and report
   exactly two pending deliveries: one confirmed and one not found. Its
   abandonment count must be one, and all other candidate work must already be
   terminal.
5. Apply that exact version-3 plan while every writer remains paused. Verify a
   version-2 receipt linked to both the old receipt and plan hashes, message
   `35557` in `delivered` with its confirmed message ID, message `15063` in
   `abandoned` with the forward-only reason, all source candidate/provenance
   data still present, the source state unchanged, and no other state changed
   beyond the reviewed finalization.
6. Run a fresh production snapshot and verify the release/checksum and paused
   schedule state again. Then resume only `bursawatch-tg-source-ingest` through
   the authenticated Control Plane desired-schedule interface, preserving its
   existing one-minute cadence and timezone. Leave the legacy Market News
   reader and watchdog paused.
7. Observe natural runs only. Confirm source acceptance, owner work and
   classification use the canonical state path. Distinguish accepted events,
   pipeline work, agent execution, and confirmed Delivery Owner receipts. Do
   not process pre-boundary candidates or send stale news.

If preview, archive verification, runtime checksum validation, or apply fails,
keep the schedules paused and stop before resume. Never restore an archive over
a live writer. Diagnose from the recorded hashes and exact plan, then make a
fresh preview before retrying. Never run a production schedule manually, replay
or backfill news, or post a test message.

## Production execution and natural-run observation

The release and guarded state finalization completed on 2026-10-01. Before
resume, the released runtime hashes matched the reviewed files, the Telegram
runner's isolated no-post synthetic check passed, and a fresh snapshot showed
the exact release SHA with the affected schedules paused. A unique recovery
archive was created at
`~/backup/hermes/runtime-cutovers/2026-10-01/bursawatch-tg-market-news/pre-finalization-183759-wib/`;
its source and canonical inputs matched the live files and its manifest
verified. The version-3 preview at 18:38:44 WIB matched the reviewed
`finalize_legacy` boundary, and the guarded apply completed at 18:39:38 WIB
with `status=legacy_finalized`. It preserved all 81 source candidates and
provenance records, made no new imports, abandoned the one unresolved legacy
candidate, retained the confirmed Phintraco delivery for message `35557`, and
abandoned Tuntun message `15063` because its Delivery Owner operation was
confirmed not found. Post-apply checks confirmed all canonical candidates were
terminal and no old pending delivery remained.

Telegram source-ingest was resumed only through the authenticated desired-
schedule API, retaining the one-minute cadence and Asia/Jakarta timezone. The
fresh 18:57 WIB production snapshot showed revision 9 applied and effective,
with the legacy Market News reader and watchdog still paused. The first
resumed natural run (`d2f744eb48f546268dd04c6c9bd64375`, started at 18:48:35
WIB) accepted same-day Telegram events `35559` and `35560` from Phintas,
`15064` to `15067` from Tuntun, and `10905` and `10906` from Kelas. Read-only
Control Plane inspections found the associated 18 pipeline-work rows in
`done` with no error codes. No cursor was edited and no replay, backfill,
manual schedule run, or test post was used.

The first natural intake created 14 Market News candidates from Tuntun messages
`15065` and `15066` in the canonical state file. At the read-only owner-state
check after the 18:59 WIB scheduled run began, 5 were in `pending_selection`,
8 in `pending_analysis`, and 1 in `awaiting_agent`. None yet had a matching
confirmed publication receipt in the canonical publication ledger at that
time. The flow had reached source and owner acceptance, but not the plan's
natural-run delivery acceptance criterion. The later receipt failure and
corrective work are recorded below. Do not mark this plan complete until the
current-day classification and delivery handoff is resolved without
candidate-state errors and each claimed delivery has a confirmed owner
receipt; leave all pre-boundary candidate work abandoned.

At the 19:12 WIB owner-state check, the same 14 candidates had progressed to 8
`pending_delivery`, 3 `pending_analysis`, 1 `awaiting_agent`, and 2
`suppressed_rank`. Tuntun message `15065` candidate `industry-1` has a matching
Delivery Owner `delivered` status and digest, with Discord message ID
`1555188202858483763`; its operation target is the frozen Industry channel
`1549418098807930880`. The stored receipt contains only `message_id`, which is
valid under the shared typed receipt contract. Because the Market News
projection required `receipt.channel_id`, it rejected that delivery as
`delivery receipt is not a confirmed matching operation`, left the candidate
pending, and repeated the error on subsequent natural runs. The exact deployed
`publication_projection.py` and `delivery.py` hashes matched this worktree,
and the publication projection flag was enabled. The stable operation remains
delivered, so the recovery must inspect that same operation and must not create
another Discord message.

The worktree regression now exercises the complete delivery call site with a
valid message-only receipt. It failed on the original code and passed after
the projection derived an omitted destination from the already-validated
operation target; the explicit wrong-channel guard still passes. Focused and
full Market News suites pass. Repository `bash scripts/test-all` also passed
with exit 0, including 91 RSS tests and one existing skipped Control Plane
test. This follow-up is not yet deployed. Keep the natural-run acceptance open
until the fix reaches production and the existing pending deliveries settle
through their stable operations with matching receipts and canonical
publication records.

The scheduled Market News source run `0b0b9c827ef442db964bc15c597781b4`
completed at 19:15:37 WIB. A read-only owner-state check found the same 14
candidates: 10 `pending_delivery`, 2 `pending_analysis`, and 2
`suppressed_rank`. Only `tuntun:15065:industry-1` has an accepted Delivery
Owner handoff among the pending deliveries; that operation is already
`delivered` with message ID `1555188202858483763`. The other nine pending
deliveries have no persisted handoff yet. None of the 14 has a Published Feed
projection entry. The 19:19 WIB production snapshot still showed the exact
`main` SHA released, exact-main CI success, and all 8 desired schedules
matching, with source-ingest active at revision 9. It continued to show the X
watcher at `last=error`, while WhatsApp and Stockbit were `last=ok`. These are
separate scheduler observations, not proof of delivery. The receipt fix remains
local; keep this plan open until it is deployed and natural runs confirm the
existing stable operation and resulting publication records without a second
Discord create.

## Acceptance evidence

- Both source-work and agent-control subprocesses select
  `~/.hermes/state/idx-market-news.json` by default, and explicit test
  overrides still work.
- The package-local source state remains unchanged and archived.
- All valid source-work provenance is present in the canonical owner ledger.
- The canonical state has a valid version-2 reconciliation receipt, and the
  state reader also accepts exact legacy version-1 receipts during the
  compatibility window.
- No canonical pending delivery remains unresolved at the finalization
  boundary; each observed delivery outcome is confirmed or safely abandoned.
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

## 2026-10-01 pending-delivery follow-up

A 22:15 WIB read-only check found 12 current-day Tuntun candidates in
`pending_delivery` in the canonical Market News state. They have
classified routes; this is not an unknown-destination problem. The
message-only receipt fix from PR #38 is released, but the earlier handoff
inspection proved a delivered stable operation for only one candidate.
Inspect each remaining handoff and operation before assigning one cause.
Reconcile any prior Discord create through the same operation key.

The operator accepts natural draining of already accepted durable work
even when its source time is old. Preserve source and delivery times.
Previously abandoned pre-cutover candidates remain terminal; this does
not authorize manual insertion or replay. A fresh eligible post in the
right room is useful evidence but does not block unrelated fixes.
