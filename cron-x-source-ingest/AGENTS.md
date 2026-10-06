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
event. Ordinary news with authored text uses optional media: unsupported media,
failed fetches or uploads, and missing upload access fall back to sanitized
text and any usable bounded images. A failed attachment does not discard its
healthy siblings; source positions and upload keys remain unchanged.
Image-only posts and Swing routes retain required-media handling. An unresolved
route also requires media when its effective subscriptions allow Swing. If
Swing is disabled for that event, unknown news routes may use fallback and the
existing frozen capability gate prevents a later Swing delivery. The
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
An own-author quote retains its inline quoted text and media when its original
is absent from the bounded page or outside the configured thread window. It
does not require historical fetching. Inline quote data is removed only when
the original is included in the retained thread. A missing reply parent or a
quote without visible inline context still holds the cursor.
Same-ID source changes create durable SourceEvent corrections. The owner leaves
work retriable when required context cannot be reconstructed. Accepted source
media is bounded to 16 refs per event, 8 MiB per object, and 25 MiB aggregate;
the watcher makes up to 16 accepted images available to Vision and supports
multi-image delivery through All and the Board.
Correction failures retain the existing `correction_handoff_failed` reason and
add a bounded `correction_error_code` identifying the failed stage. Never log
raw exceptions, source bodies, media locators, or credentials for diagnostics.

New optional-news payloads freeze `source_media_policy: optional_news` and a
hash of the observed source thread. The accepted index retains that hash so
an unchanged source does not trigger media reuploads or corrections when an
attachment fails or recovers. Genuine source edits inspect the accepted version
and its current-version work before preparing media. Claimed, executing, completed, or otherwise
nonpending work remains frozen and reports a bounded `deferred_frozen`
correction outcome without holding unrelated intake. Legacy records with
unchanged sanitized text retain their accepted media and report
`text_unchanged_media_unverified`; this is not proof that image bytes match.
For a genuine edit to pending legacy ordinary news, append a new optional-media
version under the original frozen capabilities. Swing, image-only, and
ambiguous Swing-capable events keep required images. Never retrofit a marker
into an accepted payload/index or rewrite a frozen delivery.

New correction requests carry `expected_pending_version`. The Control Plane
checks that version and all of its work atomically before appending. Retain
older staged request bytes and revision identities, adding the same atomic
guard when retrying them through the upgraded adapter. Retain
the same staged request on transport failure. If a competing claim or
settlement freezes that work, retire only the unsent correction spool entry
with a bounded `deferred_frozen` outcome; do not revise source state or send
Discord. A revision already accepted before an acknowledgement was lost still
reconciles its original revision identity, even after its work completes.
Correction inspection failures retain the existing warning fields but do not
stop subsequent publications' correction checks.
Retry saved corrections per request, retaining a failed request's bytes and
revision identity. Each request is attempted at most once in a run. A failed
event keeps its saved retry rather than staging another version from that
run's observation; other saved requests and observed publications continue.

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
