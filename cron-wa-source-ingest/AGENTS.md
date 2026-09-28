# WhatsApp source ingest

This package supplements the repository `AGENTS.md`. It is an unscheduled
Task 5 adapter with a watcher-owned agent handoff. Read `SKILL.md` before
changing its queue, inbox, media, or wake contract.

The adapter reads the existing bridge queue through the Channel watcher's
validator. It does not pair WhatsApp, follow a Channel, fetch history, or
delete queue files. Only BRI's reviewed forwarding endpoint has a source
capability. INS and Samuel remain observe-only under the current archive owner.
New forwarding publishers fail closed until explicitly reviewed.

The existing watcher remains the canonical owner of archive, agent analysis,
BRI Chart context, Board handoff, rendering, Delivery Owner handoff, and
heartbeat. `PipelineRuntime` passes accepted Source Inbox work to
`cron-wa-channel-watch/bin/pipeline_owner.py`, which persists it in the
existing watcher outbox before acknowledging work. This package does not write
that outbox directly or send Discord messages. Do not run the adapter beside
the existing source reader. A history-preserving cursor migration requires an
approved cutover and a reviewed queue/archive/outbox/receipt reconciliation.
For a deliberately forward-only cutover, a fresh source state root starts at
the current queue head and skips existing queued events; it does not import or
change the legacy watcher's state. Use that mode only after the legacy reader
stops, and retain the legacy state for rollback. For media-bearing items, read
only the watcher's immutable archive and use the Source Media Owner client.
Never read the queue's disposable staging path or call Storage directly.
Missing archive bytes, an unsupported MIME, absent Owner configuration, or an
invalid upload response must leave the event blocked and its cursor unchanged.

The source-ingest library already supports a forward-only bootstrap for an
endpoint with no cursor: the adapter records the newest durable queue arrival
position without parsing or accepting existing queue files. Queue items at or
before that position are intentionally skipped, while later arrivals remain
eligible. This does not import or validate the legacy watcher's timestamp/event
cursor. Keep `plan_legacy_cursor_seed` blocked. Use a fresh source state root
only during an approved cutover after the legacy reader stops, and never reset
an existing root to trigger this behavior.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use a fake queue, isolated state, and no bridge or Discord calls.

## No-write migration preflight

`bin/migration_preflight.py --metadata <sanitized.json>` reads only the
operator-supplied JSON file and prints a report to stdout. It does not discover
or read live queue, archive, watcher state, media, Delivery Owner receipts,
databases, Discord, WhatsApp, or Hermes. It has no apply option and never
initializes or writes a cursor. Unknown fields are rejected, including source
text, media paths, payloads, credentials, and raw media bytes.

The version-3 metadata document is BRI-only. It contains queue, immutable
archive, watcher outbox, and Delivery Owner receipt inventories. Each inventory
has the same `snapshot_id` and timezone-aware `capture_boundary`, a declared
`record_count`, a `canonical_sha256`, and sanitized `records`. The queue rows
carry `event_key`, `published_at`, `mtime_ns`, the content-derived `filename`,
media descriptors, and the capture process's exact-marker boolean for leading
`#TechnicalReview`. Archive rows carry matching identity and publication time,
the capture process's record-checksum result, and media capture status,
checksum, byte count, and integrity result. Watcher rows carry the persisted
profile, routability, agent, media, Board, and Board-link phases, plus the
number of saved text-message IDs. Receipt rows carry only the operation-key
hash, payload digest, operation kind, status, and whether the Owner has a
receipt. No source content, media bytes, or raw receipt identifiers are
included.

Inventory digests use SHA-256 over UTF-8 JSON serialized with sorted object
keys, no insignificant whitespace, `ensure_ascii=False`, and `allow_nan=False`,
with no trailing newline. The canonical record order is queue `(mtime_ns,
filename)`, archive `event_key`, watcher outbox `event_key`, and receipts
`operation_key_sha256`. Each digest payload includes the inventory's snapshot
identity, capture boundary, and sorted records. The watcher digest also covers
the legacy cursor, watcher source-state SHA-256, and the sanitized operation
projection from the existing Channel Watch Delivery Handoff plan. Receipt
inventory scope is the watcher operation namespace
`bursawatch-wa-channel-watch`.

The operation projection contains the Delivery Handoff plan's source SHA-256,
operation count, operation-key hashes, payload hashes, and kinds. It includes
message-create legs and reconstructed Board-link edit legs. For a patched link,
the watcher handoff planner recreates the canonical rendered message, applies
the saved Board URL, and pairs that content with the saved text-message ID. It
fails closed if the number or identity of messages cannot be reconstructed.
The checker verifies array counts, digest formats, operation uniqueness,
source-hash equality, expected Board-edit count, and matches by operation-key
hash, payload digest, kind, delivered status, and receipt presence. Missing,
duplicate, mismatched, unexpected, or unresolved rows block.

The Delivery Owner's paginated `GET /v1/admin/operations` summaries include
the operation key, payload digest, kind, and status, but omit the receipt body.
The exact `GET /v1/operations/by-key/{operation_key}` response includes the
optional receipt. An exporter must bind both views to one stable snapshot to
produce `receipt_present`; the paginated summaries alone cannot establish it.
The admin listing is offset-paginated in pages of at most 100 and has no
snapshot token, so a shared capture boundary in this JSON is a declaration, not
proof that concurrent inserts or updates could not shift pages.

Counts and digests establish only that the supplied bundle matches its own
manifest. An omitted record can be undetectable if the exporter recomputes the
count and digest. Shared snapshot labels also do not prove that the exporter
captured all sources atomically or recently. Completeness and freshness always
remain `unproven`, so readiness for a history-preserving cursor migration
remains `blocked`, even when the supplied records and all derivable receipts
reconcile. The checker cannot recompute archive record checksums, media
checksums, or the exact marker from sanitized metadata; it validates the
corresponding source-process assertions and the bundle digest. A trusted
capture process must attest completeness, freshness, and correspondence to
canonical source state before a history-preserving handoff can be considered.
This is not required for the separately approved forward-only bootstrap,
which intentionally skips existing queue events and does not claim history
continuity.

This adapter crosswalk check is distinct from the watcher archive's existing
`cutover-plan`, which inventories a future-only archive baseline. It neither
replaces nor invokes that command.

The planner joins queue and archive rows by the stable
`channel_jid:message_id` event key, checks the queue filename derived from that
identity, compares observed `(published_at, event_key)` and `(mtime_ns,
filename)` order, reconciles media descriptors, and enforces the supplied
TechnicalReview marker plus exactly one verified archived image. It can report
that supplied rows agree, but it does not produce a cursor candidate while
inventory completeness and freshness are unattested. The existing
`adapter.plan_legacy_cursor_seed` remains blocked. This is not cutover approval
or production-state verification. BRI remains the only forwarding profile; INS
and Samuel remain observe-only.
