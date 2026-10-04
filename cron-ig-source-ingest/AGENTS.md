# Instagram source ingest pilot

This package supplements the repository `AGENTS.md`. It is an unscheduled
Task 5 source adapter with an agent-backed owner handoff. Read `SKILL.md`
before changing intake or the wake contract.

`bin/adapter.py` reuses the current Instagram watcher's universal RSSHub
fetcher and parser, including its route-specific authentication boundary. It
requires the reviewed endpoint to publisher map and verified effective
catalog subscriptions. Unknown People & Org endpoints fail closed.

Private cursor, blocked media metadata, and handoff spool paths must never be
initialized from, merged into, or used to replay the live watcher state. When
media storage is configured, this adapter reuses the live watcher's bounded
public-HTTPS media downloader, limits uploads to 8 MiB per object and 25 MiB
per publication, and stores only validated opaque refs in the source event.
This package has no registered production job. The legacy
`bursawatch-ig-account-watch` job is registered but paused at the 2026-09-29
live check. If resumed, that watcher remains the source reader until a
separately approved cutover. Accepted `company_news` and `macro_news` Source Inbox work enters that
watcher's state through `PipelineRuntime` and `pipeline_owner.py`. The owner
retrieves and checks every durable original through the Source Media Owner,
then reuses the watcher OCR, reel-frame, vision, prompt, rendering, outbox,
Delivery Owner receipt, and cleanup paths. A missing original keeps the work
retryable. The source runner drains owner deliveries and claims at most one
watcher agent event per run. It must not poll the live watcher a second time.
Frozen sibling capabilities select the routes that may receive a relevant
publication. The agent still classifies truthfully against both configured
routes; a relevant classification for an unsubscribed route gets an audited
`route_not_subscribed` no-delivery outcome. Market-word context is advisory; a valid false LLM relevance decision
remains authoritative, including educational posts. Do not describe this adapter as active
intake until a reviewed schedule change is applied. Supabase Storage is
accessed only through the shared Source Media Owner.

Run `../../../.venv/bin/python -m pytest -q tests` from this package in the
managed worktree. Tests use fakes and no source network or Discord writes.
