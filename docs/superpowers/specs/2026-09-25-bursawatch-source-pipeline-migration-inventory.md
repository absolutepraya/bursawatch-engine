# Bursawatch source-pipeline migration inventory

> **Status:** Local cutover preparation. This document is not a live production inventory or cutover approval.
>
> **Design:** [Source Catalog and platform-pipeline architecture](2026-09-24-bursawatch-source-catalog-and-pipeline-architecture-design.md)
> **Plan:** [Source Catalog and platform-pipeline implementation plan](../plans/2026-09-24-bursawatch-source-catalog-and-pipeline.md)

## Evidence boundary

This inventory was prepared from checked-in package contracts, source code, release metadata, and synthetic tests. It does not inspect VPS files, production databases, Supabase Storage, Discord, Hermes schedules, or live credentials. The endpoint IDs below are the repository's seeded catalog identities. They are not proof that an endpoint is currently enabled, subscribed, or being read in production.

Current production cursor positions, queued item counts and payload digests, accepted source event keys, pipeline-work states, Delivery Owner receipt IDs, media object references, effective catalog revision, and numeric Hermes job IDs/status are **not collected**. They require an explicitly approved read-only VPS inventory. Do not fill them from an old manifest or infer them from a cron name.

## Known platform ownership

| Platform | Existing production reader/domain owner | New adapter in this branch | Seeded endpoint IDs | Known durable state contract |
|---|---|---|---|---|
| Telegram | Market News, Phintraco Swing, Kelas Investasi GTW | `cron-tg-source-ingest` (unscheduled) | `telegram:phintraprofits`, `telegram:phintasprofits`, `telegram:kelasinvestasiid`, `telegram:tuntunsekuritas` | Market News: `~/.hermes/state/idx-market-news.json`; Kelas: `~/.hermes/state/kelas-investasi-gtw-watch.json`; Phintraco: path selected by `IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH`, with package-local `state/state.json` fallback. Shared PolyCop control state: `~/.hermes/state/telegram-resilience-polyclop.json`. Tuntun is cataloged but explicitly outside the current Telegram adapter pilot. |
| X | `cron-x-account-watch` | `cron-x-source-ingest` (unscheduled) | `x:kutekians`, `x:rickyho_1989`, `x:writingtorch`, `x:arvinhonami`, `x:insidertrackx`, `x:doktermarket`, `x:txthariansaham`, `x:wavetiga`, `x:aldotjahjadi8`, `x:kobeissiletter` | Existing owner path is `X_POST_WATCH_STATE_PATH`; code fallback is package-local `state/state.json`. Capture the effective wrapper path and every endpoint cursor/outbox from the live host. |
| Instagram | `cron-ig-account-watch` | `cron-ig-source-ingest` (unscheduled) | `instagram:beyondthefundamental`, `instagram:investart_id`, `instagram:avenirresearch.id`, `instagram:acresresearch`, `instagram:sectorsapp`, `instagram:cukhurukuque`, `instagram:notintofinance` | Existing owner path is `INSTAGRAM_POST_WATCH_STATE_PATH`; also inventory its media root and per-publication delivery records. The effective production path is not established by the source fallback. |
| WhatsApp | `cron-wa-channel-watch` | `cron-wa-source-ingest` (unscheduled) | `whatsapp:0029Vb6qi96ISTkJcDn4op2z` (INS), `whatsapp:0029VbAjdnb60eBhwVdJxj1c` (BRI Danareksa), `whatsapp:0029VagNdGpFMqrXKEcdBb2U` (Samuel) | `~/.hermes/state/whatsapp-channel-watch/state.json`, `queue/`, `archive/`, and `media-staging/`. BRI has the implemented source handoff; INS and Samuel remain observe-only. Inventory archived source IDs and media hashes without copying media into Git. |
| RSS / Stockbit | `cron-stockbit-snips` | `cron-rss-source-ingest` (unscheduled) | `rss:stockbit:stockbit_commentary`, `rss:stockbit:unboxing`, `rss:stockbit:unboxing_ipo`, `rss:stockbit:ai_reports_stockbit` | `~/.hermes/state/stockbit-snips.json` plus the effective live configuration revision and four lane settings in the Control Plane. Preserve article IDs, validators, pending article queue, frozen settings, and Delivery Owner keys. |

The endpoints in each row are catalog seed identities, not a claim that the platform adapter currently owns their production reads. The Control Plane's effective enabled-subscription snapshot is the source of truth for the actual configured selection and must be captured at inventory time.

## Shared downstream state to inventory

| Owner | Durable store | Required migration evidence |
|---|---|---|
| Control Plane source inbox | Postgres tables `bursawatch_source_events`, `bursawatch_source_event_versions`, `bursawatch_source_work`, and `bursawatch_source_work_audit` | Effective catalog revision; accepted event keys and immutable versions grouped by endpoint; event publication boundaries; each work key, capability/config snapshot, status, lease, retry/dead-letter state, and replay/suppression audit record. No event payloads or database credentials in the committed report. |
| Domain owners | Existing package state listed above | Source cursor/high-water position; durable source handoff and exact pending payload; completed, pending, blocked, or ambiguous domain effects; source and media identity; package snapshot checksum. |
| Swing Board | `~/.hermes/state/idx-swing-board.sqlite3` and `~/.hermes/state/idx-swing-board-media/` | Ticker routes, open and resolved episode IDs, source event bindings, queued Board effects, stable operation keys, and media hashes. Capture only when a platform route reaches the Board. |
| Discord Delivery Owner | Documented intended paths are `/home/praya/.hermes/state/bursawatch-discord-delivery.sqlite3` and `/home/praya/.hermes/state/bursawatch-discord-delivery-media/`; live deployment and configured paths are unverified. | Sanitized operation key, ordering key, payload digest, state, attempt count, and exact Discord receipt IDs. Preserve `pending`, `ambiguous`, and blocked work. Never infer absence from a missing caller-local receipt. |
| Source Media Owner | Private Supabase Storage, mediated by the owner | Opaque refs, source identity, byte length, media kind, and digest needed by pending work. Do not export object bytes or signed URLs into the inventory. Live bucket and object state were not inspected. |
| Hermes scheduler | VPS Hermes job registry | Numeric job ID, exact name, enabled/paused state, cadence/time zone, wrapper command, and current owner for every existing reader, watchdog, Board reconciler, and worker. Checked-in runtime identities are not live scheduler evidence. |

## Required read-only inventory packet

For each endpoint, record one row per configured subscription and preserve the effective Control Plane revision used for the read:

| Field | Required value |
|---|---|
| Platform and endpoint ID | Canonical ID from the effective snapshot |
| Publisher, provider identity, capabilities | Effective verified identity and enabled subscriptions |
| Current reader | Package, exact live Hermes job ID, wrapper, enabled state, and cadence |
| Source boundary | Provider cursor/high-water ID and publication timestamp, plus the snapshot checksum |
| Existing pending work | Count and oldest/newest source IDs; exact payload digest and media refs remain in the private snapshot |
| Accepted inbox state | Event keys and publication-time range, grouped by endpoint |
| Pipeline work | Work keys, capability/config revisions, and counts by pending, leased, complete, retry, dead-letter, or suppressed state |
| Domain handoff | Durable pending source items and exact operation keys; count completed, blocked, and ambiguous |
| Discord receipts | Operation keys and payload digests matched to returned channel/thread/message IDs |
| Snapshot provenance | Capture time in UTC, tool/package revision, source-state checksum, and private backup location |

Keep payload-bearing snapshots and source media on the VPS in the approved private backup area. Commit only the sanitized inventory and hashes. Never put credentials, raw source text, image bytes, signed URLs, or full runtime databases in Git.

## Migration and rollback rehearsal

1. Use package-owned snapshot and checksum logic. Run a read-only plan against an isolated copy; never let a test resolve the default production path.
2. Use fake Control Plane, Source Media, and Discord Delivery services. Keep source IDs, endpoint revisions, cursor boundaries, payloads, attachment bytes, and completed receipts synthetic.
3. Confirm the candidate cutover imports no item at or before the captured cursor unless a durable pending handoff explicitly requires it.
4. Confirm every accepted event and pipeline work key is idempotent, every completed Discord operation retains its exact receipt, and retries retain the original payload digest and attachment bytes.
5. Confirm an unknown Discord create outcome remains `ambiguous` and is reconciled by the Delivery Owner. The caller must not create a replacement thread or message.
6. Exercise rollback using the synthetic pre-cutover snapshot. Restore the old reader's cursor and pending queue without deleting accepted events or receipts, then prove repeated handoff cannot duplicate a domain effect.
7. Run each package's `delivery_handoff.py` fixture suite and `bash scripts/test-all`. These local results prove code behavior only, not production inventory or cutover readiness.

The existing package handoff plans are useful inputs, but they cover Discord delivery state, not the whole source/event/pipeline inventory. Any mismatch, missing cursor boundary, unreadable state, checksum change, unknown delivery outcome, or missing media bytes blocks that endpoint's cutover. Do not initialize a new source cursor from zero or replay historical provider content to repair an incomplete inventory.

## Separate operational approval gate

This branch does not authorize production state reads, migrations, scheduler edits, deployments, source replay, or Discord writes. Before any endpoint is cut over, present the sanitized live packet and proposed exact transition for review. Then obtain separate approval for the bounded production state cutover and any Hermes schedule change. Pause the old writer and watchdog, snapshot and checksum its state, apply the reviewed mapping once, verify source acceptance, pipeline receipt, domain effect, Discord receipt, and `#hermes` heartbeat separately, and retain the prior state until unattended evidence is stable.

Until that sequence is approved and verified, existing watchers remain the production source readers and the platform adapters remain unscheduled development code.
