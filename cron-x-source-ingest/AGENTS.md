# X source ingest pilot

This package supplements the repository `AGENTS.md`. It is an unscheduled,
metadata-only Task 5 source adapter. Read `CRON.md` before changing its intake.

`bin/adapter.py` uses the existing X watcher's RSSHub or direct X fetcher and
parser. The reviewed current endpoint to publisher bindings are fixed here;
an unknown People & Org endpoint cannot enter until its publisher and watcher
profile are reviewed. Only verified effective catalog subscriptions are read.

Endpoint cursors, blocked media records, and inbox handoff spools are private
to this package. Never copy or initialize them from the live X watcher state
without a separately approved cutover. The existing watcher remains the sole
live source reader, queue owner, agent wake owner, renderer, Board handoff, and
Discord Delivery Owner client. This pilot has no production schedule or
pipeline handler. Self-chain assembly, supersession, linked articles, media,
and agent analysis remain unresolved parity work.

Run `../../../.venv/bin/python -m pytest -q tests` from this package in the
managed worktree. Tests use fakes and temporary state. Do not fetch live X
history or post during development validation.
