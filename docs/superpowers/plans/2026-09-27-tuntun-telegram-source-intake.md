# Tuntun Telegram Source Intake

## Goal

Route Tuntun Sekuritas Telegram posts through the shared Telegram source
adapter and the existing Market News owner. Preserve its forum-topic boundary,
multi-candidate posts, source provenance, and legacy cursor boundary.

## Implementation scope

- Recognize the verified `telegram:tuntunsekuritas` endpoint for
  `company_news` and `macro_news`.
- Carry the Telegram forum topic ID in the immutable source event. The existing
  Tuntun parser remains responsible for accepting only topic `3743` and
  extracting one or more candidates.
- Accept Tuntun work in the Market News owner, recording each extracted
  candidate under the same event, sibling capability keys, and frozen config.
- Preview the old Tuntun cursor from
  `providers.tuntun.observed_message_id`; block a seed if Tuntun itself still
  has active legacy candidates. Other providers' work does not block it.
- Add synthetic tests and update the source-intake and Market News contracts.

## Cutover boundary

The implementation adds code and a coordinated cutover tool, but does not
change live source subscriptions or Hermes schedules by itself. The legacy
Market News reader polls Phintraco News and Tuntun as one indivisible job, so
they move together. The paired tool permits only the consecutive effective
catalog change that activates Phintraco `company_news`, `macro_news`, and
`stock_status`, and Tuntun `company_news` and `macro_news`; all other effective
subscriptions and selected securities must remain unchanged.

The operator must pause the legacy Market News job, its watchdog, and the
shared Telegram source-ingest job, wait for in-flight work, reconcile both
providers' legacy effects and receipts, and capture a fresh checksummed legacy
state snapshot. After the desired catalog revision is written and verified,
the tool previews against the exact old and new effective snapshots. Apply
requires that unchanged preview and snapshot, verifies the prior state marker
and state-file inventory, creates both future-only provider cursors, then
advances the state marker. A durable journal makes interrupted apply resumable.
Resume shared ingestion only after the target revision and both cursor seeds
verify, then keep the legacy Market News job and watchdog paused. This cutover
does not backfill or replay Telegram history.

## Acceptance

- The shared adapter emits Tuntun topic identity and rejects unsupported
  enabled endpoint/capability combinations.
- The Market News owner accepts supported topic-3743 Tuntun candidates,
  including multiple ticker candidates from one Corporate post, and ignores
  other topics.
- Tuntun cursor previews use the Tuntun legacy boundary and isolate pending
  work by provider.
- Focused source-ingest and Market News test suites pass. Implementation tests
  did not mutate production; the separately approved production cutover is
  recorded below.

## Production execution record

The paired cutover completed on 2026-09-27 after commit
`374824276a6a2aa06d3e5ea5ba3ca35df79caae9` passed `CI / validate` and the
VPS release agent deployed the source-ingest, Market News, and shared source
ingest runtime units.

- Effective source catalog revision moved from 2 to 3. The only changes enabled
  Phintraco News `company_news`, `macro_news`, and `stock_status`, plus Tuntun
  `company_news` and `macro_news`. All other subscriptions and selected
  securities remained unchanged.
- The legacy Market News Hermes job `6a0b4f895b07` and watchdog
  `d34dc79771b0` remain paused. Desired schedule revision 6 is disabled and
  confirmed effective by the reconciler. Shared Telegram source ingest
  `262b25371e83` is active at its existing one-minute cadence.
- The paired cursor transition moved source-ingest state revision 2 to 3 using
  the frozen legacy high-water marks: Phintraco 35444 and Tuntun 15006. The
  transition journal is complete. It created no historical candidates and did
  not replay Telegram history.
- The private, checksummed snapshot bundle is retained at
  `~/backup/hermes/runtime-cutovers/2026-09-27/bursawatch-tg-market-news-handoff/`.
  It contains the pre-transition legacy and source-ingest state, prior and
  target catalog snapshots, the exact preview plan, and post-transition
  source-ingest state. The checksum manifest passed verification; the bundle
  is about 1.9 MB.
- The first natural source-ingest run after resume, execution
  `3e3e489070fe43ed8519d472b1a65cb9`, completed successfully at 13:15 WIB.
  It polled all four configured Telegram endpoints without a block, accepted
  zero new messages, and had no pending work or agent dispatch. Successful
  completion also confirms the run's required heartbeat receipt from the
  Delivery Owner. No News content post was made by that run.
- Two immediately preceding legacy Market News run records, at 13:02 and
  13:04 WIB, were marked failed with `delivery service returned an invalid
  response`; both reported zero source messages, candidates, and content
  deliveries. The shared source-ingest heartbeat succeeded after cutover, but
  News content delivery was not exercised by the first natural run. Observe
  the first naturally occurring News event through the new owner before
  treating that content-delivery path as live-verified.
