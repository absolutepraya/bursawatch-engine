# Instagram source ingest pilot

This package supplements the repository `AGENTS.md`. It is an unscheduled,
metadata-only Task 5 source adapter. Read `CRON.md` before changing intake.

`bin/adapter.py` reuses the current Instagram watcher's universal RSSHub
fetcher and parser, including its route-specific authentication boundary. It
requires the reviewed endpoint to publisher map and verified effective
catalog subscriptions. Unknown People & Org endpoints fail closed.

Private cursor, blocked media metadata, and handoff spool paths must never be
initialized from, merged into, or used to replay the live watcher state. The
existing watcher remains the live source reader and owner of OCR, vision,
agent analysis, rendering, outbox, Delivery Owner handoff, and heartbeat.
There is no production job or pipeline handler here. Supabase Storage is the
selected future media provider, with no reviewed object references yet.

Run `../../../.venv/bin/python -m pytest -q tests` from this package in the
managed worktree. Tests use fakes and no source network or Discord writes.
