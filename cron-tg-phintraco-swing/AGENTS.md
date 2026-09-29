# Bursawatch Telegram Phintraco Swing

This file supplements the repository root `AGENTS.md`. It is the canonical development and operations guide for this deterministic no-agent watcher.

## Identity and scope

The watcher forwards individual Phintraco IDX buy recommendations, qualifying outcome reminders, and verified active-plan status updates to Discord. It is a source-only parser and delivery pipeline. It never invokes an LLM, enriches with market data, calculates indicators, scores confidence, generates charts, or places trades.

## Runtime, scheduler, and ownership

The cutover renames active no-agent job `2b5c0a128652` to `bursawatch-tg-phintraco-swing`, retaining `* * * * *` (WIB). Hermes then runs `bursawatch-tg-phintraco-swing.sh` and delivers raw output to `#hermes` (`1505162000420835388`).

The source is Phintraco Sekuritas Official Telegram channel `1444713822`. Alerts go directly to `#id-stocks-swing` (`1525102458253217803`); the channel is also a destination for `cron-x-account-watch`'s `id_stock_swing` route, which delivers source-grounded X technical analyses in its own format. Operational heartbeats and fatal notices go directly to `#hermes`. Production state, media, lock, and watchdog notices retain their established locations through the first cutover.

When `IDX_SWING_WATCH_PHINTRACO_DAILY_CONTROL_PLANE_URL` is set, each
invocation fetches one validated, frozen control-plane snapshot before it
opens Telegram or watcher state. The snapshot may change the verified Telegram
source identity and the All and heartbeat Discord destinations. A failed live
read fails closed and never falls back to source defaults. Its revision drives
best-effort structured lifecycle, source-poll, and delivery events. Without
the URL, source defaults preserve the existing deployment behavior.

## Deterministic behavior and invariants

Accept individual `Trading Buy`, `Hold/Trading Buy`, `Buy on Support`, and `Speculative Buy` calls with the required source fields, qualifying source-marked outcomes and status updates, and validated same-ticker reply updates. `Hold/Trading Buy` is a BUY subtype.

Parse a standalone `On support` message as a status event. Route it to the Board as a Primary setup only when it identifies exactly one ticker, has a source timestamp, and includes an entry, stop-loss, and at least one target. Incomplete parsed messages remain status events, and the Discord notice retains the source status.

Also accept the exact Phintraco weekly Swing Ideas PDF attachment described below. Exclude sell calls, the PDF's separate companion text post, market reviews, media-only posts, and nearby inferred charts.

### Weekly Swing Ideas PDF batches

Read only Telegram document attachments named `PHINTAS Weekly Swing Trading Ideas_YYYYMMDD.pdf` with MIME type `application/pdf`. The adjacent Telegram text post is independent and is ignored completely. The source timestamp is the attachment message's Telegram `published_at`, converted to WIB; retain the printed report date as separate context. Do not use cron processing time or the companion post's timestamp.

`weekly_pdf.py` uses pinned `PyMuPDF==1.28.2` to extract selectable text and chart images by page geometry. It accepts at most 8 MiB, 12 pages, and 24 plans. A plan needs an explicit ticker, `ACTION: Buy`, entry, stop-loss, and at least one target, plus exactly one uniquely associated chart. It preserves source ranges, inequalities, target ordinals, descriptor, trend, MA indicator, potential ranges, report date, and page/section order. An ambiguous or malformed page is durably quarantined; independently valid pages can proceed, and the run is degraded while any page is held. Never guess a plan or chart association.

Each accepted ticker from one document is a distinct immutable event with key `pdf:<telegram-message-id>:<ticker>` and Board key `phintraco:<channel-id>:weekly:<telegram-message-id>:<ticker>`. Persist the PDF, chart files, batch, source-plan index, page quarantines, and child outbox events before advancing the Telegram cursor. Upload the PDF and each chart to the private Source Media Owner using their stable idempotency keys and persist returned refs before All delivery. Send one plan text followed immediately by its own chart to All Swing in PDF page/section order. When the Delivery Owner returns a nonterminal receipt, wait for up to the shared `DELIVERY_RECEIPT_WAIT_SECONDS` setting (10 seconds) before retrying that same stable operation, so normal delivery does not split the text and chart across scheduled runs. Submit the matching Board event only after both All legs succeed. Retries retain event order, stable keys, and successful legs.

Match a status or reminder that replies directly to a known PDF attachment only against that document's same-ticker plan. Otherwise require one unique candidate using ticker, source chronology, reported target ordinal/value, and every other supplied plan level. A value may match a source range only when that range is explicitly present; a single source value requires exact equality. No ticker-only match or invented tolerance is allowed. A unique match carries its immutable setup event key. Zero or multiple matches, conflicting levels, stale chronology, or an invalid target amendment become labeled source context and cannot change the active plan. The Board owner alone validates and applies an explicitly matched target amendment to its active plan projection.

Watcher state version 4 preserves existing state and stores per-ticker PDF event identity and retry state. Re-fetches do not duplicate a batch. Never rewind the live cursor or replay a historical PDF as part of ordinary polling.

On first successful activation, bootstrap from the newest Telegram message ID and forward no history. Only later calls are eligible. A message ID is a one-time event, so Telegram edits are ignored and changed captions, targets, advisor names, or charts are never revisited.

Normalize header spacing around the separator and uppercase the ticker. Accept `Entry`, `Stop-loss` or `Stoploss`, and unnumbered or numbered targets; require one entry, one stop-loss, and at least one target. Render targets in numeric order, source ranges with `to`, and inequalities unchanged. Preserve the complete rationale except for transport-safe whitespace normalization. Do not summarize, translate, calculate, or interpret source values.

The Telegram source-post timestamp, converted to `Asia/Jakarta`, is authoritative for the signal date and weekday. A caption date is only a parser fallback outside the runtime message path. Canonical rendering comes from the shared `swing-format` module: ticker-first heading, outcome-first titles for Reminder and status follow-ups, `-# <analyst>, Phintraco Sekuritas` or the institution-only fallback, a space before inline emojis, source-specific fields, `Source status`, `Last updated`, and `[View in Telegram](<source-url>)`. All Swing initially adds the forum-channel marker directly below `Last updated`; after the board owner acknowledges the exact topic, the watcher edits that same message to a direct `**Board:** https://discord.com/channels/940285152335110204/<thread-id>` link. The board copy omits it. A failed or incomplete link edit remains in the board handoff retry and never repeats successful All text or chart. BUY uses `New setup` with the grey marker, target outcomes use green, stop-loss uses red, and active statuses use hold. Hold and Reminder events omit a Chart line when no photo exists; a chartless BUY retains `**Chart:** Unavailable from source`. The shared renderer owns the 2,000-character check. Individual-call outbox events use the Telegram source message ID; each weekly PDF plan adds the ticker to its document message ID. PDF events move through `pending_source_media`, then the existing text, chart, Board, and delivered phases. Individual and PDF plan text/chart pairs remain adjacent, ordered, and retry-safe.

After the All text and, when present, its same-message chart succeed, the watcher submits one normalized source event to the board owner through `IDX_SWING_PLAN_BOARD_WRAPPER` (default `$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh`). It retains the event and cached source chart until the owner returns `{"accepted": true}` and, when a topic exists, its `board_url`. The watcher then edits the delivered All message to that direct topic link; a failed edit remains in the board handoff retry and never replays successful All legs. Board handoffs keep source order in a separate logical queue, so their failure or backoff never suppresses subsequent All text/chart pairs or replays successful All legs. Every normal run invokes the owner's `drain` once, even when already degraded. Nonzero exit, malformed health, pending, or failed work degrades the watcher heartbeat. The watcher never reads the board database, updates tags, posts forum content, or calculates prices.

## State, data, and credential ownership

State owns the observation cursor, outbox, cached source media, retry metadata, liveness, and rate-limited fatal fingerprints. Atomic writes and a nonblocking run lock prevent overlap. Corrupt state fails closed and must not be cleared as a recovery shortcut.

The wrapper loads `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `POLYCOP_SESSION_STRING`, the shared Discord Delivery Owner URL and client-token file path, and the narrowly named Phintraco control-plane values from VPS `~/.hermes/.env`; it exports the board wrapper path without loading board credentials. It adds `lib-bursawatch-discord-delivery/bin` to `PYTHONPATH` and defaults the client to `http://127.0.0.1:9140` with the private token file `~/.hermes/secrets/bursawatch-discord-delivery-client-token`. The scanner and watchdog use typed DeliveryClient operations for text, charts, message reads and Board-link edits, and heartbeats. Stable source event and leg keys are persisted before local delivery progress advances. Runtime paths do not load a Discord bot token or call Discord REST directly. The shared control-plane library remains optional until live mode is deliberately enabled. Source PDFs, charts, logs, and credentials stay private.

The release agent does not install cron package dependencies. Before releasing PDF intake to production, provision the pinned PyMuPDF dependency in the private Phintraco package directory through a separately reviewed host operation. Set `IDX_SWING_WATCH_PHINTRACO_DAILY_PYTHONPATH` in VPS `~/.hermes/.env` to that package directory. The wrapper validates and prepends it while retaining the existing Yahoo Finance MCP interpreter and its dependencies. Do not extend automated release behavior to install package dependencies or alter the shared Yahoo Finance MCP Python environment. The release manifest classifies `requirements.txt` as metadata only.

`bin/delivery_handoff.py --plan <private-plan-path>` creates a read-only plan for paused-writer state import. Apply requires `--apply`, `BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY=1`, the admin client token, and a separately approved cutover while the scanner is paused. Handoff acknowledgments are written only after the Delivery Owner accepts a matching operation receipt.

## Delivery contract and failure semantics

One text alert fits in one Discord message, followed by its source chart when available, then one accepted board handoff. The watcher posts at most one `idx-swing-phintraco-daily` heartbeat per WIB hour and marks degraded work with `⚠️`, including a failed owner drain. Fatal notices are sanitized and rate-limited by fingerprint and hour. The watchdog detects an overdue successful poll without overwriting scanner state.

## Safety, approval, and no-post rules

This watcher shares `POLYCOP_SESSION_STRING` and the `lib-telegram-resilience` control plane at `~/.hermes/state/telegram-resilience-polyclop.json`. It calls `acquire_probe_after_active_lease` before creating a Telegram client. A shared cooldown, active probe, transport failure, or authorization hold exits without advancing the cursor or mutating the outbox.

For no-post verification set `IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST=1`, an isolated `IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH`, and `IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT=1` if required. Never manually invoke the production schedule, backfill calls, or reset live state.

## Development commands and behavioral tests

Run from the repository root:

```bash
../.venv/bin/python -m pytest -q cron-tg-phintraco-swing/tests
```

The suite covers parsing and rejections, timestamp and source-chart rules, durable media and outbox transitions, FIFO and retry safety, rate limiting, shared-resilience exits, heartbeat behavior, watchdog isolation, and wrapper setup.

## Deployment and live verification

Deploy only a clean published commit with `./deploy.sh cron-tg-phintraco-swing`, synchronize the wrapper and `CRON.md` separately after approval, and compare changed VPS checksums. Deploy `lib-bursawatch-control` before enabling live mode. Use isolated no-post verification through the actual wrapper, then inspect the natural scheduler record and target delivery path. State, media, logs, and the dotfiles mirror are not source to change.

## Historical references and related projects

The Telegram source-ingest pilot adds `bin/pipeline_owner.py` for source work. It
reuses this watcher's parser, outbox, renderer, and Board handoff. The owner
requires a validated live watch-config revision and activates that frozen source
and route snapshot before opening its ledger or delivering. Its source identity
must still match the canonical pilot endpoint; there is no default-config
fallback in this path. For individual charts and weekly PDF documents, the owner
retrieves opaque refs through `lib-bursawatch-source-media`, verifies size and
digest, and places the bytes into the existing private source-media handoff.
Weekly PDF work uses the attachment's original publication timestamp and the
existing adjacent All text/chart and accepted Board delivery sequence. Durable
effect receipts are written only after the relevant All and Board work is
complete. The existing scheduled reader stays active; this handler is not a
cutover signal.

This is a Phintraco-specific parser. Future providers require independent source validation. Root `AGENTS.md` and `lib-telegram-resilience/README.md` define the shared session and control-plane contract.
