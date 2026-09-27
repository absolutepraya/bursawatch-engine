# X source ingest pilot

This package supplements the repository `AGENTS.md`. It is an installable,
unscheduled Task 5 source adapter. The release agent may install it and its
wrapper, but this package has no Hermes job or production cutover. Read
`CRON.md` before changing its intake.

`bin/adapter.py` uses the existing X watcher's RSSHub or direct X fetcher and
parser. The reviewed current endpoint to publisher bindings are fixed here;
an unknown People & Org endpoint cannot enter until its publisher and watcher
profile are reviewed. Only verified effective catalog subscriptions are read.

Endpoint cursors, blocked media records, accepted-event indexes, correction
handoff spools, and inbox handoff spools are private
to this package. Never copy or initialize them from the live X watcher state
without a separately approved cutover. When media storage is configured, the
adapter uploads bounded `pbs.twimg.com` images through the shared Source Media
Owner before inbox acceptance. It stores only validated opaque refs in the
event. Unsupported media and upload failures retain the endpoint cursor. The
existing watcher remains the sole live source reader, queue owner, agent wake
owner, renderer, Board handoff, and Discord Delivery Owner client. The pilot
claims compatible `company_news` and `macro_news` subscription work through
`PipelineRuntime` and passes it to the watcher owner. Events include ordered
self-chain context and opaque image references. Same-ID source changes create
durable SourceEvent corrections. The owner leaves work retriable when required
context cannot be reconstructed. The current Board chart path supports one
source image per event; multiple-image work remains unclaimed. This pilot has
no production schedule or cutover.

Run `../../../.venv/bin/python -m pytest -q tests` from this package in the
managed worktree. Tests use fakes and temporary state. Do not fetch live X
history or post during development validation.
