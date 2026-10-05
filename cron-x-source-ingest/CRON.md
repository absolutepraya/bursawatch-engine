# X platform source boundary

Runtime identity: `bursawatch-x-source-ingest`. Entry point:
`bin/runner.py`, installed by the release agent with
`bin/bursawatch-x-source-ingest.sh`. The existing Hermes X source-polling job
invokes this runtime. It is the sole production X source reader. The separate
X account-watch queue worker processes accepted work and must remain active.
Do not enable the legacy account-watch source-polling wrapper beside this
reader.

For deployment, configure the private Source Event API URL and token file
as `BURSAWATCH_X_SOURCE_CONTROL_PLANE_URL` and
`BURSAWATCH_X_SOURCE_CONTROL_PLANE_TOKEN_FILE`. Every enabled X endpoint must
also have a reviewed publisher binding; unknown bindings block intake rather
than being inferred from a handle. Keep credentials out of logs and source
control.

Every run sends a heartbeat through the shared
Discord Delivery Owner to `#hermes`, including empty polls. The format is
`🫀 bursawatch-x-source-ingest · HH:MM WIB · endpoints=N accepted=N work=N pending=N`
with `⚠️` for blocked source endpoints or pending work. Fatal runs use
`❌ bursawatch-x-source-ingest · HH:MM WIB · failed: source processing failed`.

Each verified configured X account has its own future-only cursor and
`SourceEventHandoff`. A nontruncated page, or a truncated page that still
contains the prior anchor, drains in at most 20-post batches, advancing only
through acknowledged posts. A truncated page without its prior anchor blocks
with `page_truncated` and retains the cursor. Inbox failure leaves the staged
request and cursor in place. A numeric ID cursor can be compared against a
complete page when its anchor has fallen off. Opaque IDs require migration
provenance with a timestamp boundary, otherwise a missing anchor blocks.
For `hybrid` source mode, the adapter passes the prior numeric anchor to the
shared X fetcher. That fetcher merges the RSSHub page with missing IDs visible
on the public X profile before the cursor advances. Either source failing
blocks intake. The public profile is a bounded window and cannot prove complete
historical coverage.
Post IDs set provider order; publication time
remains event metadata. At most the next 20 fresh events are considered for
media upload. The adapter reuses the live watcher's bounded, image-only
`pbs.twimg.com` fetch path, then uploads bytes through the shared Source Media
Owner before source-event acceptance. Accepted events contain validated
opaque media refs, never CDN URLs or bytes. Video URLs, unsupported image
types, unavailable media, and upload failures fall back to text for ordinary
news with authored text. Any usable images stay in source order and within
the existing bounds; raw media locators are removed even on fallback. The
existing specialized Swing path and image-only posts remain fail-closed in
`blocked-media.json` with the cursor held. The safe fetch path does not support
X video downloads. The ordinary-news boundary is the same per-event route
hint used for upfront Swing enrichment, with an unresolved hint retaining
required media whenever the effective event subscriptions allow Swing.
Profiles with Swing disabled may still fall back for unresolved news routes;
the watcher verifies this against frozen work capabilities before queueing.
The LLM retains relevance and final routing within those existing capabilities.
Partial preparation or upload failures retain healthy attachments in source
order with their original source labels and upload identities.
The runner reads one live watcher config revision and the effective catalog.
Verified X endpoints are compatible with `company_news`, `macro_news`, and
`swing_chart_context`; compatibility does not enable a subscription.
`swing_chart_context` is disabled by default, while its effective enabled
state and catalog revision are explicit in the snapshot. The three X
capabilities share the frozen `x_post_route` dispatch group: one publication
with any enabled group members creates one route-group work item, and the
existing X watcher classifies it once. Existing legacy `company_news` and
`macro_news` work remains drainable. Each work item freezes the complete
enabled capability set and per-capability configuration source for retries and
corrections; it does not re-evaluate current catalog settings.

## Source Catalog revision transition

The effective catalog and the X reader marker must agree before polling. The
reader accepts revision 8 only when its private journal directory contains the
completed historical 5 to 7 revision-only transition and the completed
package-owned 7 to 8 transition. The 7 to 8 journal records the reviewed hash
of all 30 effective X subscription rows, including disabled capabilities.
Missing, incomplete, malformed, or extra journal entries block the reader.

Use `bin/compatible_catalog_transition.py preview` with the exact prior and
target effective catalog JSON and the current source state root. Review and
retain its private plan outside the state root. Applying requires that same
plan, unchanged catalogs and source files, the package apply guard
`BURSAWATCH_X_CATALOG_TRANSITION_ALLOW_APPLY=1`, and a paused source reader.
The shared planner advances only the marker and journal; all endpoint cursors,
accepted-event indexes, and pending handoffs remain unchanged. Do not use this
one-edge tool for later catalog revisions without a separately reviewed
package change.

Accepted source events carry an ordered self-chain snapshot. Own-author quotes
keep inline quoted text and media when the original is absent from the page
or outside the configured thread window. A missing reply parent or quote
without visible inline context still blocks intake. The reader does not fetch
historical originals to reconstruct these standalone quotes. Correction
failures include a bounded `correction_error_code` identifying the failed
stage alongside `correction_handoff_failed`, without raw exceptions or source
content in diagnostics. A private
accepted-event index detects same-ID source changes and stages durable
corrections with stable revision IDs. The Source Media Owner uses
`BURSAWATCH_SOURCE_MEDIA_URL`, the private upload token file
`BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE`, and an owner read token file
`BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE`. New ordinary-news events freeze
`source_media_policy: optional_news` and an observed-source hash in their
payload. Missing upload or owner read access can omit news images before the
watcher queue is frozen. The accepted index keeps the source hash, preventing
media recovery or outages from revising an unchanged accepted post. Genuine
text or source-media metadata edits still use the existing correction path.
Legacy accepted versions remain immutable. Inspect the accepted version and
its frozen current-version work before correction media preparation. Already
nonpending work is deferred without editing or resending it. Unchanged legacy
text retains accepted media without claiming to verify image equality. A
pending legacy news edit may append an optional-media correction under the
original frozen capabilities; image-only, Swing, and ambiguous Swing-capable
sources still require images. New requests carry `expected_pending_version`,
checked atomically by the Control Plane. Transport retries retain the same
revision identity. Older saved requests retain their bytes and receive the
same guard when retried by this adapter. A raced claim retires only the unsent
correction with a
bounded deferred outcome; a lost acknowledgement reconciles an already
accepted revision. Independent intake and other correction checks continue.
Saved correction failures report a per-event retry and retain the unchanged
request. Attempt each saved request at most once per run, continue later saved
requests, and check independent observed posts without staging a second edit
for an event whose saved correction failed.
The result's `corrections` array records bounded provider IDs and dispositions,
never source bodies, media locators, or raw exceptions.
Required Swing media or a required thread original still makes its work retry.
Accepted media remains bounded to 16
refs per event, 8 MiB per object, and 25 MiB aggregate. The adapter does not
enable a capability or change the effective X watcher configuration.

For a cursorless `direct_x` endpoint, the first poll reads the public profile
page and records the largest own-author status ID as a future-only boundary.
It does not download or publish posts already visible at setup time. If the
page has no verifiable own-author status link, the endpoint stays blocked and
no cursor is written. Later polls use the stored ID and normal post/thread
fetching. The bootstrap deliberately does not transfer or backfill legacy
history.

The existing X watcher retains its self-chain, edit/supersession, classifier,
rendering, outbox, Board, Delivery Owner, and heartbeat behavior. Do not
remove its queue worker; it processes accepted source work and may also have
pending deliveries from before the source-reader transition.

`adapter.plan_legacy_cursor_seed` previews a per-profile seed from an explicit
legacy JSON snapshot. The Python API defaults to preview. Applying uses its
explicit `apply=True` argument and requires
`BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY=1`, the unchanged preview, an empty
legacy outbox, and no initialized cursor or source handoff. It binds the
legacy SHA-256, endpoint identity, and catalog revision.

The X adapter marks its ordered page with
`id_order="numeric_provider_event_id"`. The shared cursor reader validates
that marker and the ascending numeric IDs before comparing a seed boundary
that has fallen off the page. Other adapters cannot infer numeric ordering
from ID shape and block when their anchor is absent without another proven
boundary. This is a synthetic migration aid, not production cutover approval.

Accepted work is handed to the existing watcher through `pipeline_owner.py`,
which resolves the same canonical `X_POST_WATCH_STATE_PATH` as the watcher
scanner. If unset, both use `state/state.json` inside the deployed watcher
package. Adapter cursors and its accepted-event index remain in the separate
source-ingest state root.
