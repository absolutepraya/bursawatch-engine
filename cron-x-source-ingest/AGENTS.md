# X source ingest pilot

This package supplements the repository `AGENTS.md`. It is an installable,
unscheduled Task 5 source adapter. The release agent may install it and its
wrapper, but this package has no Hermes job or production cutover. Read
`CRON.md` before changing its intake.

`bin/adapter.py` uses the existing X watcher's RSSHub, hybrid, or direct X fetcher and
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
owner, renderer, Board handoff, and Discord Delivery Owner client. For verified
X endpoints, `company_news`, `macro_news`, and `swing_chart_context` are
compatible members of the exclusive `x_post_route` dispatch group; compatibility
does not enable a subscription, and `swing_chart_context` is disabled by default.
Any enabled group member creates one route-group work item per publication, which
the existing watcher classifies once. Each item freezes the full enabled
capability set, per-capability configuration source, and catalog revision for
retries and corrections instead of re-evaluating current catalog settings.
Existing legacy `company_news` and `macro_news` work remains compatible and
drainable. Events include ordered self-chain context and opaque image references.
Same-ID source changes create durable SourceEvent corrections. The owner leaves
work retriable when required context cannot be reconstructed. Accepted source
media is bounded to 16 refs per event, 8 MiB per object, and 25 MiB aggregate;
the watcher makes up to 16 accepted images available to Vision and supports
multi-image delivery through All and the Board. This pilot has no production
schedule or cutover.

The X watcher owns one state file for scanning, accepted source work, and
Delivery Owner handoff. All watcher processes resolve it through
`state.state_path()`: `X_POST_WATCH_STATE_PATH` when configured, otherwise
`state/state.json` inside the deployed watcher package. The source adapter's
endpoint cursors and accepted-event index remain under its separate state root.

Run `../../../.venv/bin/python -m pytest -q tests` from this package in the
managed worktree. Tests use fakes and temporary state. Do not fetch live X
history or post during development validation.
