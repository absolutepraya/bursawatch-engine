# Telegram source ingest

This package is the active Telegram source-intake pilot with an automatic
release unit and deployable runtime wrapper. Hermes job
`bursawatch-tg-source-ingest` runs every minute. Its live scope includes
Phintraco Swing `trading_plans`, Kelas Investasi `swing_support`, Phintraco News
`company_news`, `macro_news`, and `stock_status`, plus Tuntun News
`company_news` and `macro_news`. The paired Phintraco and Tuntun News cutover
completed on 2026-09-27. Its production record is in
[`docs/superpowers/plans/2026-09-27-tuntun-telegram-source-intake.md`](../docs/superpowers/plans/2026-09-27-tuntun-telegram-source-intake.md).

`bin/runner.py` reads one authenticated effective source catalog snapshot, then
`bin/adapter.py` groups enabled verified subscriptions by canonical endpoint.
It reads each supported endpoint in batches of at most 20, uses one private
cursor and handoff spool per endpoint, and advances a cursor only after the
source inbox confirms durable acceptance. First contact records the newest
message ID without replaying source history. Enabled Telegram identities and
capabilities must match the exact publisher or intake fails closed. Tuntun
events include their Telegram forum topic ID so the Market News owner can
apply its existing thread-3743 parser without searching Telegram history.

`adapter.plan_legacy_cursor_seed` previews a seed from an explicit Phintraco,
Tuntun, or Kelas JSON snapshot. It records the snapshot SHA-256, endpoint
identity, and catalog revision. The Python function's `apply=True` argument is the explicit
apply interface and requires the unchanged preview plan plus
`BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY=1`; it refuses initialized
cursors or pending handoffs and blocks legacy pending domain work. Kelas maps
its current cursor to both the new cursor and future-only bootstrap boundary.
For `telegram:phintasprofits` and `telegram:tuntunsekuritas`, the Market News
provider cursor is previewable from `providers.phintraco.observed_message_id`
or `providers.tuntun.observed_message_id` in a version 1 snapshot. The preview
fails closed on malformed state. Preview and apply block while that provider
has candidates in `pending_analysis`, `awaiting_agent`, `pending_selection`, or
`pending_delivery`. Phintraco seeding also blocks on a stock-status event in
`pending_delivery`. Pending work from the other provider does not block its
cursor seed; reconcile each provider's old domain effects against inbox events
and owner receipts before seeding it.

The Market News legacy reader polls Phintraco News and Tuntun as one indivisible
job. Its paired cutover uses `bin/catalog_transition.py`, which permits only
activation of Phintraco `company_news`, `macro_news`, and `stock_status`, plus
Tuntun `company_news` and `macro_news`. It requires unchanged identities and
settings, one consecutive catalog revision, reconciled legacy work for both
providers, and a fresh state snapshot. Pause the Market News job, its watchdog,
and this source-ingest job before taking that snapshot or applying the cursor
transition. Preview and apply require the same prior and target effective
catalog snapshots and legacy state file. The tool journals the paired cursor
creation and advances the state revision last, so an interrupted apply can
resume from the exact preview. Keep its private plan outside the source state
root. Never hand-edit `catalog-revision.json` or either cursor.

When a catalog revision changes only non-Telegram configuration, a separate
cursor-preserving transition is allowed only if selected securities and every
enabled Telegram subscription row is identical after canonical JSON
normalization, including identity, capability, settings, credentials, and
dispatch metadata. Pause this source-ingest writer first. Capture the prior and
target effective catalog snapshots, then use
`bin/compatible_catalog_transition.py preview` and `apply`
with a private plan outside the state root. Apply requires
`BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY=1`; it fingerprints all
other state files and journals before advancing only the revision marker. It
never creates, resets, or moves cursors. Any Telegram row or selected-security
change requires a separately reviewed transition. This is not a News backfill
path; keep News future-only and do not replay source history.

The inbox owns source events and independent subscription work. The adapter
never submits Discord or Board operations. `service-bursawatch-source-media`
owns private Supabase Storage access; `lib-bursawatch-source-media` uploads
bounded media before event acceptance and returns opaque durable refs. The
adapter never receives Storage credentials or stores signed/public media URLs.
`lib-bursawatch-pipeline-runtime`
claims only registered handler pipelines. The pilot registers the existing
Phintraco Swing owner for plans, Kelas Investasi for supporting setups, and
Market News for Stock Information plus Phintraco and Tuntun news. Each owner
retains its own state and uses the Discord Delivery Owner. Market News and
Kelas analysis use the existing owner lease and submission contracts. When both have ready
agent work, the runner claims at most one oldest candidate, using a persisted
round-robin tie break for equal publication times. Kelas inbox work is claimed
in Telegram message order; a failed earlier message blocks later messages
until it succeeds or an admin explicitly suppresses it. Telegram media
blocks the endpoint before cursor advancement only for an actual photo or
document attachment when its type is unsupported, the media service is
unavailable, or durable upload fails. Web-page link previews
(`MessageMediaWebPage`) remain part of the text event and are not treated as
file attachments. A local
`blocked-media.json` records only source identity and media type to diagnose a
blocked handoff; it is private state, never Git. If upload succeeds but inbox
acceptance fails, the private handoff spool retains the opaque reference and
retries it without reuploading or advancing the Telegram cursor.

Keep live subscriptions within the reviewed catalog scope above. Do not enable
other Telegram subscriptions or change the pilot schedule without an approved
rollout. News cursors were seeded from the legacy high-water marks and are
future-only; do not backfill or replay source history. The legacy Market News
scanner and watchdog remain paused, and the legacy scanner's desired schedule
is disabled. Do not resume either while shared source ingest polls these
publishers. The source owner must emit a heartbeat to #hermes on every scheduled
run, including no-hit runs, using the shared Discord Delivery Owner and the
package contract's fixed heartbeat format.

The release wrapper is `bin/bursawatch-tg-source-ingest.sh`. Its normal entry
point reads only `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`,
`POLYCOP_SESSION_STRING`, `BURSAWATCH_TG_SOURCE_CONTROL_PLANE_URL`,
`BURSAWATCH_TG_SOURCE_CONTROL_PLANE_TOKEN_FILE`, and, when media is enabled,
`BURSAWATCH_SOURCE_MEDIA_URL`, `BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE`,
and `BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE`, plus the two
`BURSAWATCH_DISCORD_DELIVERY_*` settings from
`~/.hermes/.env`. It also passes the Phintraco Swing owner's
`IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_URL`, `_WATCHER_ID`, `_TOKEN`,
and `_TIMEOUT_SECONDS` settings so the owner subprocess can load its revisioned
live config. The source wrapper validates `IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH`
and prepends it to `PYTHONPATH` because the source runner invokes the owner
directly, without the Phintraco cron shell wrapper. This lets the owner import
the privately provisioned pinned PDF parser without changing the shared Yahoo
Finance environment. Credential contents stay in their
existing private files and never enter logs. The release-agent
`BURSAWATCH_RELEASE_NO_POST=1`
path does not open `.env` or credential files. It invokes only the synthetic
in-memory contract check, passes a scrubbed environment, and keeps its log in
the release agent's disposable `BURSAWATCH_RELEASE_NO_POST_TEMP` directory.
The source adapter uses the media upload token; domain owners use the read
token to download accepted private media through Source Media.

Run focused synthetic tests from the repository root with
`.venv/bin/python -m pytest -q cron-tg-source-ingest/tests`.
