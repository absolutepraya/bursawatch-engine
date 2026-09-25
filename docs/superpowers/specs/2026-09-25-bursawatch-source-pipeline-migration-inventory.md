# Bursawatch source-pipeline migration inventory

> **Status:** Read-only live inventory completed 2026-09-25. This is not a production cutover approval.
>
> **Design:** [Source Catalog and platform-pipeline architecture](2026-09-24-bursawatch-source-catalog-and-pipeline-architecture-design.md)
> **Plan:** [Source Catalog and platform-pipeline implementation plan](../plans/2026-09-24-bursawatch-source-catalog-and-pipeline.md)

## Evidence boundary

This inventory combines checked-in package contracts, source code, release metadata, synthetic tests, and a read-only VPS inspection at `2026-09-25T04:26:37Z`. No source payloads, credentials, Discord content, or image bytes were printed or copied. The endpoint IDs below are repository seed identities unless a live Control Plane selection is explicitly reported below.

This was not a frozen state snapshot: exact source cursors, payload digests, per-message delivery receipts, and per-object media references were not exported. The observed file sizes and database counts are a point-in-time inventory only. Before cutover, capture and checksum package-owned snapshots in the approved private backup location, then repeat the exact cursor, pending payload, receipt, and media crosswalk against that frozen snapshot.

## Known platform ownership

| Platform | Existing production reader/domain owner | New adapter in this branch | Seeded endpoint IDs | Known durable state contract |
|---|---|---|---|---|
| Telegram | Market News, Phintraco Swing, Kelas Investasi GTW | `cron-tg-source-ingest` (unscheduled) | `telegram:phintraprofits`, `telegram:phintasprofits`, `telegram:kelasinvestasiid`, `telegram:tuntunsekuritas` | Market News: `~/.hermes/state/idx-market-news.json`; Kelas: `~/.hermes/state/kelas-investasi-gtw-watch.json`; Phintraco: path selected by `IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH`, with package-local `state/state.json` fallback. Shared PolyCop control state: `~/.hermes/state/telegram-resilience-polyclop.json`. Tuntun is cataloged but explicitly outside the current Telegram adapter pilot. |
| X | `cron-x-account-watch` | `cron-x-source-ingest` (unscheduled) | `x:kutekians`, `x:rickyho_1989`, `x:writingtorch`, `x:arvinhonami`, `x:insidertrackx`, `x:doktermarket`, `x:txthariansaham`, `x:wavetiga`, `x:aldotjahjadi8`, `x:kobeissiletter` | Existing owner path is `X_POST_WATCH_STATE_PATH`; code fallback is package-local `state/state.json`. Capture the effective wrapper path and every endpoint cursor/outbox from the live host. |
| Instagram | `cron-ig-account-watch` | `cron-ig-source-ingest` (unscheduled) | `instagram:beyondthefundamental`, `instagram:investart_id`, `instagram:avenirresearch.id`, `instagram:acresresearch`, `instagram:sectorsapp`, `instagram:cukhurukuque`, `instagram:notintofinance` | Existing owner path is `INSTAGRAM_POST_WATCH_STATE_PATH`; also inventory its media root and per-publication delivery records. The effective production path is not established by the source fallback. |
| WhatsApp | `cron-wa-channel-watch` | `cron-wa-source-ingest` (unscheduled) | `whatsapp:0029Vb6qi96ISTkJcDn4op2z` (INS), `whatsapp:0029VbAjdnb60eBhwVdJxj1c` (BRI Danareksa), `whatsapp:0029VagNdGpFMqrXKEcdBb2U` (Samuel) | `~/.hermes/state/whatsapp-channel-watch/state.json`, `queue/`, `archive/`, and `media-staging/`. BRI has the implemented source handoff; INS and Samuel remain observe-only. Inventory archived source IDs and media hashes without copying media into Git. |
| RSS / Stockbit | `cron-stockbit-snips` | `cron-rss-source-ingest` (unscheduled) | `rss:stockbit:stockbit_commentary`, `rss:stockbit:unboxing`, `rss:stockbit:unboxing_ipo`, `rss:stockbit:ai_reports_stockbit` | `~/.hermes/state/stockbit-snips.json` plus the effective live configuration revision and four lane settings in the Control Plane. Preserve article IDs, validators, pending article queue, frozen settings, and Delivery Owner keys. |

The endpoints in each row are catalog seed identities, not a claim that the platform adapter currently owns their production reads. The Control Plane's effective enabled-subscription snapshot is the source of truth for the actual configured selection and must be captured at inventory time.

## Read-only live observation

### Control Plane and catalog

| Check | Live observation |
|---|---|
| `bursawatch-control-plane.service` | Loaded, active, running; `GET /healthz` returned HTTP 200. The API listens on loopback port 9120. |
| Applied database migrations | `001` to `012` are present. Source Catalog and inbox migrations `013_source_catalog.sql` to `016_source_execution_fence.sql` are absent. |
| Source Catalog API | Authenticated `/v1/source-catalog/effective` returned HTTP 404. Catalog revision, endpoint selections, source event inbox, and pipeline work tables do not exist in the live database. |
| Existing watcher configuration revisions | Swing Board 1; Instagram 1; Stockbit 1; Kelas Investasi 1; Market News 1; Phintraco Swing 1; WhatsApp 4; X 7. |
| Stockbit | The live database config is revision 1 with the four existing fixed lanes enabled: `stockbit_commentary`, `unboxing`, `unboxing_ipo`, and `ai_reports_stockbit`. |

The new source catalog is not live. The checked-in seeds do not describe effective live subscriptions. Stockbit's existing live database configuration remains authoritative and must be preserved by any later migration.

### Hermes readers and Board jobs

These are current registry observations, not proposed replacement schedules. There were 21 registered Hermes jobs in total. No platform `*-source-ingest` job was registered.

| Owner/job | Hermes ID | Enabled | Schedule |
|---|---:|---:|---|
| Phintraco Swing | `2b5c0a128652` | yes | every minute |
| Market News | `6a0b4f895b07` | yes | every minute |
| Market News watchdog | `d34dc79771b0` | yes | every minute |
| X account watch | `bc519bd9abc0` | yes | every 10 minutes |
| X account queue | `ca1839ba1dcf` | yes | every minute |
| Kelas Investasi GTW | `c5844b3c21a0` | yes | hourly |
| Instagram account watch | `c2869d60502b` | no, paused 2026-09-10 | hourly |
| WhatsApp channel watch | `b0e11d17b784` | yes | every minute |
| Swing Board close reconcile | `5c0b79e08fae` | yes | weekdays, 16:30 WIB |
| Swing Board retry reconcile | `71c4f9a32acd` | yes | weekdays, 17:00 WIB |
| Stockbit Snips | `0c6b17e4c944` | yes | every 15 minutes |

Current readers and Board reconciler jobs remain the production owners. The exact live command strings and secret-bearing environment values were not copied into this committed report.

### Existing runtime state

| Owner | Live state observation |
|---|---|
| Phintraco Swing | `state.json`, mode `0600`, 498 bytes; observed-message cursor present; local outbox empty. |
| X account watch | `state.json`, mode `0644`, 2,032,664 bytes; 944 delivery records, 12 profile cursors, empty outbox. Review the permissive file mode before any approved state handoff. |
| Instagram account watch | `state.json`, mode `0600`, 5,454 bytes; 16 delivery records, 5 profile cursors, empty outbox. Its Hermes job is paused. |
| Market News | `idx-market-news.json`, mode `0600`, 1,500,376 bytes; 635 candidates, 36 dedupe entries, 6 digest windows, and 2 provider cursors. |
| Kelas Investasi GTW | `kelas-investasi-gtw-watch.json`, mode `0600`, 80 bytes; cursor present, empty local outbox and pending queue. |
| Stockbit Snips | `stockbit-snips.json`, mode `0600`, 16,286 bytes; 4 feed states and 3 article records, all 3 currently marked delivered. |
| WhatsApp channel watch | `state.json`, mode `0600`, 194,735 bytes; 90 durable outbox records: 35 delivered, 42 filtered, 11 pending, and 2 ready. Preserve these records and their ordering; do not replay or rebuild them from the queue. |

### Swing Board state

The live Board database is `~/.hermes/state/idx-swing-board.sqlite3`, mode `0644`, 811,008 bytes. It contains 69 episodes (22 `primary`, 9 `source`, 38 `resolved`), 61 plan rows, 106 source events, 10 history events, 119 close checkpoints, 119 close attempts, and 531 Board outbox operations, all marked complete. All 69 episodes have a thread ID and starter-message ID; all 10 history rows have Discord message IDs. No unprocessed source event was found. The current Board client uses one code-owned forum ID; the episode rows do not store a forum ID or a per-ticker route assignment.

**Cutover blocker:** the database has one ticker with two open episodes, both `primary`; the maximum is two open episodes for one ticker. The ticker and Discord IDs are intentionally omitted here. This conflicts with the agreed invariant of at most one open episode per ticker. Do not merge, close, supersede, or recreate either episode automatically. A separately reviewed reconciliation must identify the canonical episode and preserve both histories before that ticker can cut over.

One hundred Board source events reference media; 91 retain a legacy local media path. The Board media directory contains 105 files totaling 14,309,875 bytes. The separate Source Media Owner and Discord Delivery Owner are not installed on the VPS, so these local bytes and the existing Board receipts have not been reconciled to durable object references or a Delivery Owner ledger. Do not delete or relocate the legacy files as part of this inventory.

### Runtime owner and Discord transport status

`bursawatch-control-plane.service` is installed and running. `bursawatch-discord-delivery.service` and `bursawatch-source-media.service` are not installed, and neither has a live owner state database or private environment/token files. Only the Control Plane listener was present among ports 9120, 9130, and 9140. A source scan of the deployed watcher packages found direct Discord REST implementations in the Swing Board, Instagram, Stockbit, Kelas, Market News, Phintraco, WhatsApp, and X runtimes. The shared Delivery Owner in this branch has not replaced those live paths.

The distinct local loopback port map is Control Plane `9120`, Source Media `9130`, Discord Delivery Owner `9140`. The checked-in Delivery Owner default had conflicted with the live Control Plane port; local defaults and contracts are corrected in this branch. The VPS configuration has not been changed.

### Remaining evidence before a cutover proposal

- Capture frozen, package-owned state snapshots and SHA-256 checksums under the approved private VPS backup path. No snapshots or backup writes were made during this read-only inspection.
- Record exact per-endpoint cursor boundaries, pending payload digests, source and event crosswalks, and `#hermes` health evidence from the frozen snapshots without adding payloads to Git.
- Reconcile the Board's duplicate open Primary episode before any Swing source migration.
- Verify each Discord completion against exact channel/thread/message receipts and the source event or operation key. The legacy SQLite Board outbox is complete, but a separate Delivery Owner receipt ledger is absent.
- Verify WhatsApp's 42 filtered, 11 pending, and 2 ready records against its immutable source/archive records and output receipts.
- Inspect the permissive X state and Swing Board database modes and approve any permission correction as a separate scoped production operation.
- Provision and validate private Supabase Storage, Source Media, and Discord Delivery Owner only after separate production approval. This inspection did not query Storage or Discord and does not claim the object references exist.

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

The repository also includes `service-bursawatch-control/tests/test_migration_rehearsal.py`. It uses the real shared source cursor writer, source handoff spool, in-memory Control Plane inbox, leased `PipelineRuntime`, and SQLite Delivery Owner. Its synthetic rollback restores the legacy reader snapshot while retaining accepted inbox work and Delivery Owner records, then verifies duplicate source delivery creates no new pipeline work and preserves both a delivered receipt and an ambiguous operation. This fixture is a contract rehearsal, not a Postgres migration test or proof that any live package-specific state has been mapped.

The existing package handoff plans are useful inputs, but they cover Discord delivery state, not the whole source/event/pipeline inventory. Any mismatch, missing cursor boundary, unreadable state, checksum change, unknown delivery outcome, or missing media bytes blocks that endpoint's cutover. Do not initialize a new source cursor from zero or replay historical provider content to repair an incomplete inventory.

## Separate operational approval gate

This branch does not authorize production state reads, migrations, scheduler edits, deployments, source replay, or Discord writes. Before any endpoint is cut over, present the sanitized live packet and proposed exact transition for review. Then obtain separate approval for the bounded production state cutover and any Hermes schedule change. Pause the old writer and watchdog, snapshot and checksum its state, apply the reviewed mapping once, verify source acceptance, pipeline receipt, domain effect, Discord receipt, and `#hermes` heartbeat separately, and retain the prior state until unattended evidence is stable.

Until that sequence is approved and verified, existing watchers remain the production source readers and the platform adapters remain unscheduled development code.
