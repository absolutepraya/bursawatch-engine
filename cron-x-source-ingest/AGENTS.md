# X source ingest

This package supplements the repository `AGENTS.md`. It is an installable,
scheduled source adapter. The existing Hermes X polling job invokes its
wrapper; this package owns source polling and per-endpoint cursors. The
separate X account-watch queue worker owns accepted work and Discord delivery.
Read `CRON.md` before changing its intake or schedule contract.

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
existing watcher remains the queue owner, agent wake owner, renderer, Board
handoff, and Discord Delivery Owner client. For verified
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
multi-image delivery through All and the Board.

The first poll for a direct-X endpoint reads only the account page and stores
the newest own-post ID as a future-only boundary. It does not fetch or publish
visible history. Later polls fetch new posts after that boundary. If the page
does not expose a verifiable own-post link, intake fails closed and does not
write a cursor.

Catalog revision changes require the X package transition helper. For the
reviewed 7 to 8 edge, `bin/compatible_catalog_transition.py preview` must prove
the complete effective X subscription projection matches the pinned review
hash, then create a private preview with the shared source-state planner.
Apply requires that unchanged preview and
`BURSAWATCH_X_CATALOG_TRANSITION_ALLOW_APPLY=1`. The
transition changes only the catalog marker and journal. It does not seed or
rewrite endpoint cursors, accepted-event indexes, or handoff work. Runtime at
revision 8 requires the complete existing 5 to 7 journal followed by a
completed package-owned 7 to 8 journal. A marker change without this chain
blocks intake.

The X watcher owns one state file for scanning, accepted source work, and
Delivery Owner handoff. All watcher processes resolve it through
`state.state_path()`: `X_POST_WATCH_STATE_PATH` when configured, otherwise
`state/state.json` inside the deployed watcher package. The source adapter's
endpoint cursors and accepted-event index remain under its separate state root.

Run `../../../.venv/bin/python -m pytest -q tests` from this package in the
managed worktree. Tests use fakes and temporary state. Do not fetch live X
history or post during development validation.
