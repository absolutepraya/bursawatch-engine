# X platform source boundary

Runtime identity reserved: `bursawatch-x-source-ingest`. Entry point:
`bin/runner.py`. No Hermes job is registered. The adapter is release metadata
only and must not be run beside the current source polling job.

Each verified configured X account has its own future-only cursor and
`SourceEventHandoff`. A page above 20 new posts blocks the endpoint; inbox
failure leaves the staged request and cursor in place. A full RSSHub page
whose prior anchor is absent blocks with `page_truncated`
and retain the cursor. Post IDs set provider order; publication time remains
event metadata. Media-bearing posts leave bounded text and identity in
`blocked-media.json` with the cursor held.
The media bytes are not retained and upstream availability remains a blocker.
The runner reads one live watcher config revision and the effective catalog.
It does not claim `company_news` or `macro_news` pipeline work.

The existing X watcher retains its self-chain, edit/supersession, classifier,
rendering, outbox, Board, Delivery Owner, and heartbeat behavior. Do not
remove its source job or queue worker before a reviewed state and scheduler
transition proves parity and accounts for pending output.
