# X platform source boundary

Runtime identity: `bursawatch-x-source-ingest`. Entry point:
`bin/runner.py`, installed by the release agent with
`bin/bursawatch-x-source-ingest.sh`. No Hermes job is registered. Do not
invoke this runtime beside the current X source polling job; production
cutover requires a separate reviewed one-reader scheduler transition.

When separately scheduled, every run sends a heartbeat through the shared
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
types, unavailable media, and upload failures remain fail-closed in
`blocked-media.json` with the cursor held. The current safe fetch path does
not support X video downloads.
The runner reads one live watcher config revision and the effective catalog.
It claims `company_news` and `macro_news` work independently through
`PipelineRuntime` and hands each item to the existing X watcher owner.
Accepted source events carry an ordered self-chain snapshot. A private
accepted-event index detects same-ID source changes and stages durable
corrections with stable revision IDs. The Source Media Owner uses
`BURSAWATCH_SOURCE_MEDIA_URL`, the private upload token file
`BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE`, and an owner read token file
`BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE`. If upload access is absent, media
events remain blocked. If owner read access or a required thread original is
absent, its subscription work retries. The Board chart path currently allows
one image; multi-image source work stays unclaimed. These settings do not
change the live X watcher.

The existing X watcher retains its self-chain, edit/supersession, classifier,
rendering, outbox, Board, Delivery Owner, and heartbeat behavior. Do not
remove its source job or queue worker before a reviewed state and scheduler
transition proves parity and accounts for pending output.

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
