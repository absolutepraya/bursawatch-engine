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
- Focused source-ingest and Market News test suites pass; no live config,
  schedule, cursor, source inbox, media store, or Discord state is changed.
