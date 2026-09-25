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
Phintraco Swing owner for plans, Kelas Investasi for supporting setups, and
Market News for Stock Information and Phintraco news. Each owner retains its
own state and uses the Discord Delivery Owner. Market News and Kelas analysis
use the existing owner lease and submission contracts. When both have ready
agent work, the runner claims at most one oldest candidate, using a persisted
round-robin tie break for equal publication times. Kelas inbox work is claimed
in Telegram message order; a failed earlier message blocks later messages
until it succeeds or an admin explicitly suppresses it. Telegram media
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
bootstrapped by this pilot. The source owner must emit a heartbeat to #hermes
on every future scheduled run, including no-hit runs, using the shared Discord
Delivery Owner and the package contract's fixed heartbeat format.

Run focused synthetic tests from the repository root with
`../../.venv/bin/python -m pytest -q cron-tg-source-ingest/tests`.
