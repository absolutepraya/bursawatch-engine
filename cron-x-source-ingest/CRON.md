# X platform source boundary

Runtime identity reserved: `bursawatch-x-source-ingest`. Entry point:
`bin/runner.py`. No Hermes job is registered. The adapter is release metadata
only and must not be run beside the current source polling job.

Each verified configured X account has its own future-only cursor and
`SourceEventHandoff`. A nontruncated page, or a truncated page that still
contains the prior anchor, drains in at most 20-post batches, advancing only
through acknowledged posts. A truncated page without its prior anchor blocks
with `page_truncated` and retains the cursor. Inbox failure leaves the staged
request and cursor in place. Post IDs set provider order; publication time
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
