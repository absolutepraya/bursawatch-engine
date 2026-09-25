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
the existing source reader or migrate its cursor without an approved cutover
and a reviewed queue/archive inventory. For media-bearing items, read only the
watcher's immutable archive and use the Source Media Owner client. Never read
the queue's disposable staging path or call Storage directly. Missing archive
bytes, an unsupported MIME, absent Owner configuration, or an invalid upload
response must leave the event blocked and its cursor unchanged.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use a fake queue, isolated state, and no bridge or Discord calls.
