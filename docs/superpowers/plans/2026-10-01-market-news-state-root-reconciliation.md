# Telegram Market News State Root Reconciliation Plan

> **For agentic workers:** Follow the package and repository production
> release gates below. Do not run manual schedules or send test messages.

**Status:** Approved by the user on 2026-10-01; implementation underway in the
`bug-squashing` worktree. Production apply is authorized within the reviewed
sequence below.

**Goal:** Put Telegram source-work acceptance, Market News agent leases, and
classification submissions on one durable owner ledger while preserving the
existing canonical candidate, dedupe, and delivery history.

**Trigger:** The natural runs after catalog recovery proved intake works, but
Market News submissions still failed. The source runner launches
`pipeline_owner.py` directly. Without `IDX_MARKET_NEWS_STATE_PATH`, that process
uses the deployed skill's package-local `state.json`. The submission wrapper
selects `~/.hermes/state/idx-market-news.json`.

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
canonical phases, delivery handoffs, and receipts while adding only matching
source provenance that is absent.

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
   identical. Preserve the complete canonical candidate record, including its
   phase, lease, retries, classification, selection, and delivery history.
   Add the source-work provenance only if canonical state has none. If
   canonical provenance exists, require its immutable event identity,
   version, content hash, source URL, enabled capabilities, and work keys to
   match; preserve the canonical frozen config snapshot.
4. Reject every payload or provenance conflict. Do not choose a winner by
   timestamp, retry count, or phase. The source-local overlap remains intact
   in the archived input for diagnosis.
5. Preserve all other canonical top-level fields and stats, including provider
   cursors, `dedupe`, `digest_windows`, stock-status events, publication
   intents, and existing source provenance.

For `stock_status_events` in the package-local file, require valid owner-schema
records. Import a source-only event with its complete record. For an overlapping
event, require equal source message ID, URL, effective date, all five parsed
categories, channel, content, and any shared rejection outcome. Preserve the
canonical phase, retry state, delivery handoff, and receipt. Copy
`source_event_key` and `config_revision` only when canonical state lacks them;
reject conflicting values. Count source, new, overlapping, phase-different,
and provenance-enriched events in the private plan and apply receipt. An
existing receipt proves idempotence only while every source candidate,
provenance record, status event, and optional status-event provenance field is
present in canonical state.

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
   payload overlap, and there are zero unresolved conflicts.
5. Apply the reviewed plan while the writer remains paused. Verify all
   source-work provenance is present in canonical state, canonical records
   from before the merge retain their phases and delivery data, source-only
   candidates were added exactly once, canonical status-event phases and
   receipts are unchanged, source status-event provenance is complete, and the
   source file is unchanged.
6. Resume the existing one-minute schedule through the supported scheduler
   interface. Observe natural runs only. Confirm source acceptance, agent
   claims, and classification submissions use the canonical file, then
   distinguish owner progress from confirmed Delivery Owner receipts.

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
- All package-local stock-status events are present or overlap canonically with
  matching payloads, canonical delivery outcomes remain intact, and missing
  source-event provenance is added where validated.
- Existing canonical candidate phases, dedupe entries, delivery intents,
  receipts, provider state, and unrelated stats are preserved.
- Natural runs complete the source acceptance and classification handoff
  without candidate-not-in-durable-state or candidate-not-awaiting failures.
- A confirmed Discord receipt is required to claim delivery. Schedule health,
  a clean heartbeat, or an accepted source event alone is insufficient.
