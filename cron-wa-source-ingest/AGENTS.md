# WhatsApp source ingest

This package supplements the repository `AGENTS.md`. It is the WhatsApp
platform queue reader with a watcher-owned domain handoff. Read `SKILL.md` before
changing its queue, inbox, media, or wake contract.

The adapter reads the existing bridge queue through the Channel watcher's
validator. It does not pair WhatsApp, follow a Channel, fetch history, or
delete queue files. Its fresh cursor starts at the observed queue high-water
mark and accepts only later arrivals. It does not replay the retained queue or
import the legacy cursor. Only BRI's reviewed forwarding endpoint has source
capabilities. INS and Samuel remain observe-only. New forwarding publishers
fail closed until explicitly reviewed.

The existing watcher remains the canonical owner of archive, agent analysis,
BRI Chart context, Board handoff, rendering, Delivery Owner handoff, and
heartbeat. `PipelineRuntime` passes accepted Source Inbox work to
`cron-wa-channel-watch/bin/pipeline_owner.py`, which persists it in the
existing watcher outbox before acknowledging work. The owner's scheduled
claim also retries ready message and Board deliveries. The adapter sends its
`#hermes` heartbeat through the shared Discord Delivery Owner. Do not run the
adapter beside the legacy source reader. For media-bearing items, read only the
watcher's immutable archive and use the Source Media Owner client. Never read
the queue's disposable staging path or call Storage directly. Missing archive
bytes, an unsupported MIME, absent Owner configuration, or an invalid upload
response must leave the event blocked and its cursor unchanged.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use a fake queue, isolated state, and no bridge or Discord calls.
