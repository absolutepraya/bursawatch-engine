# WhatsApp source ingest pilot

This package supplements the repository `AGENTS.md`. It is an unscheduled,
metadata-only Task 5 adapter. Read `CRON.md` before changing its queue read.

The adapter reads the existing bridge queue through the Channel watcher's
validator. It does not pair WhatsApp, follow a Channel, fetch history, delete
queue files, change the immutable archive, or write the old outbox. Only BRI's
reviewed forwarding endpoint has a source capability. INS and Samuel remain
observe-only under the current archive owner. New forwarding publishers fail
closed until explicitly reviewed.

The existing watcher owns live source intake, archive, agent analysis, BRI
Chart context, Board handoff, rendering, Delivery Owner handoff, and heartbeat.
This package has no production schedule or pipeline handler. Do not migrate
its cursor from old state without a reviewed queue and archive inventory.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use a fake queue, isolated state, and no bridge or Discord calls.
