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

Accept individual `Trading Buy`, `Hold/Trading Buy`, `Buy on Support`, and `Speculative Buy` calls with the required source fields, qualifying source-marked outcomes and status updates, and validated same-ticker reply updates. `Hold/Trading Buy` is a BUY subtype. Exclude sell calls, weekly bundles and PDFs, market reviews, media-only posts, and nearby inferred charts.

On first successful activation, bootstrap from the newest Telegram message ID and forward no history. Only later calls are eligible. A message ID is a one-time event, so Telegram edits are ignored and changed captions, targets, advisor names, or charts are never revisited.

Normalize header spacing around the separator and uppercase the ticker. Accept `Entry`, `Stop-loss` or `Stoploss`, and unnumbered or numbered targets; require one entry, one stop-loss, and at least one target. Render targets in numeric order, source ranges with `to`, and inequalities unchanged. Preserve the complete rationale except for transport-safe whitespace normalization. Do not summarize, translate, calculate, or interpret source values.

The Telegram source-post timestamp, converted to `Asia/Jakarta`, is authoritative for the signal date and weekday. A caption date is only a parser fallback outside the runtime message path. Canonical rendering comes from the shared `swing-format` module: ticker-first heading, outcome-first titles for Reminder and status follow-ups, `-# <analyst>, Phintraco Sekuritas` or the institution-only fallback, a space before inline emojis, source-specific fields, `Source status`, `Last updated`, and `[View in Telegram](<source-url>)`. All Swing initially adds the forum-channel marker directly below `Last updated`; after the board owner acknowledges the exact topic, the watcher edits that same message to a direct `**Board:** https://discord.com/channels/940285152335110204/<thread-id>` link. The board copy omits it. A failed or incomplete link edit remains in the board handoff retry and never repeats successful All text or chart. BUY uses `New setup` with the grey marker, target outcomes use green, stop-loss uses red, and active statuses use hold. Hold and Reminder events omit a Chart line when no photo exists; a chartless BUY retains `**Chart:** Unavailable from source`. The shared renderer owns the 2,000-character check. An outbox event is identified solely by Telegram source message ID. The phases are `pending_media_capture`, `pending_text`, `pending_chart`, `pending_board`, and `delivered`, with strict FIFO text/chart adjacency and retries that never repeat successful All text or chart.

After the All text and, when present, its same-message chart succeed, the watcher submits one normalized source event to the board owner through `IDX_SWING_PLAN_BOARD_WRAPPER` (default `$HOME/.hermes/scripts/bursawatch-dc-swing-board.sh`). It retains the event and cached source chart until the owner returns `{"accepted": true}` and, when a topic exists, its `board_url`. The watcher then edits the delivered All message to that direct topic link; a failed edit remains in the board handoff retry and never replays successful All legs. Board handoffs keep source order in a separate logical queue, so their failure or backoff never suppresses subsequent All text/chart pairs or replays successful All legs. Every normal run invokes the owner's `drain` once, even when already degraded. Nonzero exit, malformed health, pending, or failed work degrades the watcher heartbeat. The watcher never reads the board database, updates tags, posts forum content, or calculates prices.

## State, data, and credential ownership

State owns the observation cursor, outbox, cached source media, retry metadata, liveness, and rate-limited fatal fingerprints. Atomic writes and a nonblocking run lock prevent overlap. Corrupt state fails closed and must not be cleared as a recovery shortcut.

The wrapper loads `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `POLYCOP_SESSION_STRING`, the shared Discord Delivery Owner URL and client-token file path, and the narrowly named Phintraco control-plane values from VPS `~/.hermes/.env`; it exports the board wrapper path without loading board credentials. It adds `lib-bursawatch-discord-delivery/bin` to `PYTHONPATH` and defaults the client to `http://127.0.0.1:9120` with the private token file `~/.hermes/secrets/bursawatch-discord-delivery-client-token`. The scanner and watchdog use typed DeliveryClient operations for text, charts, message reads and Board-link edits, and heartbeats. Stable source event and leg keys are persisted before local delivery progress advances. Runtime paths do not load a Discord bot token or call Discord REST directly. The shared control-plane library remains optional until live mode is deliberately enabled. Source charts, logs, and credentials stay private.

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
fallback in this path. When a Swing event has a source chart, the owner retrieves
its opaque ref through `lib-bursawatch-source-media`, verifies the digest, and
places the bytes into the existing private source-chart handoff so All and Board
delivery keep their established text-then-chart behavior. The existing scheduled
reader stays active; this handler is not a cutover signal.

This is a Phintraco-specific parser. Future providers require independent source validation. Root `AGENTS.md` and `lib-telegram-resilience/README.md` define the shared session and control-plane contract.
