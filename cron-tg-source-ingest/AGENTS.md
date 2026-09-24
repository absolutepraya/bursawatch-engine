# Telegram source ingest pilot

This package is a development pilot. It has no Hermes job, deployed wrapper, or
automatic release unit. The existing Telegram jobs remain the active readers.

`bin/runner.py` reads one authenticated effective source catalog snapshot, then
`bin/adapter.py` groups enabled verified subscriptions by canonical endpoint.
It reads each supported endpoint in batches of at most 20, uses one private
cursor and handoff spool per endpoint, and advances a cursor only after the
source inbox confirms durable acceptance. First contact records the newest
message ID without replaying source history. Tuntun is classified as an
existing News reader and is deliberately outside this pilot. Unknown enabled
Telegram identities or capabilities fail closed. Every canonical endpoint,
including unmigrated Tuntun, is checked against its exact publisher before
the pilot decides whether to poll it.

The inbox owns source events and independent subscription work. The adapter
never submits Discord or Board operations. `service-bursawatch-source-media`
owns private Supabase Storage access; `lib-bursawatch-source-media` uploads
bounded media before event acceptance and returns opaque durable refs. The
adapter never receives Storage credentials or stores signed/public media URLs.
`lib-bursawatch-pipeline-runtime`
claims only registered handler pipelines. The pilot registers the existing
Phintraco Swing owner for plans and the existing Market News owner
for deterministic Stock Information. Both retain their own state and route
through the Discord Delivery Owner. Agent News and Kelas work remain pending
in the inbox because they lack a bounded Hermes agent handoff. Telegram media
blocks the endpoint before cursor advancement only when its type is unsupported,
the media service is unavailable, or durable upload fails. A local
`blocked-media.json` records only source identity and media type to diagnose a
blocked handoff; it is private state, never Git. If upload succeeds but inbox
acceptance fails, the private handoff spool retains the opaque reference and
retries it without reuploading or advancing the Telegram cursor.

Do not register or invoke this package against live Telegram, inbox, or
Discord under the development plan. It cannot replace the current readers
until media and agent paths have exact output parity, an approved state
cutover, and separate scheduler approval. No production cursor should be
bootstrapped by this pilot.

Run focused synthetic tests from the repository root with
`../../.venv/bin/python -m pytest -q cron-tg-source-ingest/tests`.
