# Phintraco Daily IDX Swing Watch Specification

**Status:** Approved specification
**Date:** 2026-07-13
**Runtime:** Hermes deterministic no-agent cron on the VPS
**Initial Signal Provider:** Phintraco Sekuritas

## 1. Purpose

Phintraco Daily IDX Swing Watch forwards new individual IDX buy recommendations, outcome reminders, and verified active-plan status updates from the Phintraco Sekuritas Official Telegram channel to the Discord `#id-stocks-swing` channel.

Each qualifying source message becomes one Swing Alert. The watcher posts the formatted text first, then posts the Source Chart immediately afterward when a chart exists. If the source message has no chart, the watcher posts a text-only alert with an explicit chart-unavailable field.

The watcher performs deterministic parsing and delivery only. It calls no LLM, performs no market-data enrichment, calculates no indicators, assigns no confidence score, and generates no investment analysis.

The domain vocabulary is defined in [`CONTEXT.md`](./CONTEXT.md).

## 2. Scope

### 2.1 Included

The initial provider parser handles:

- Individual Phintraco buy recommendations with `Trading Buy`, `Buy on Support`, or `Speculative Buy`.
- Target-achieved and stop-loss-hit reminders with a Phintraco source marker.
- A source-marked `TICKER - On support` update, rendered using the canonical `STATUS` alert format.
- A footerless `TICKER on track` or `TICKER on trac` reply, only when it replies to a parsable Phintraco `BUY` or `STATUS` event for the same ticker.

A buy recommendation must contain one IDX ticker, an allowed Call Subtype, one Entry, one Stop-loss or Stoploss field, at least one Target field, and the Phintraco source marker.

A Source Chart is optional. When present, it must be attached to the same Telegram message as the qualifying event.

### 2.2 Excluded

The watcher must not forward:

- PHINTAS Weekly Swing Trading Ideas multi-stock text bundles
- Weekly Swing Trading Ideas PDFs
- Weekly SSF Review PDFs
- Reminder posts without a target-achieved or stop-loss-hit outcome
- Sell on Strength recommendations
- Composite or IHSG updates
- Research reports
- Daily or weekly market reviews
- Today's Selective Shares summary images
- Corporate-action notices
- Economic calendars
- Media-only posts not attached to a qualifying Swing Call
- Nearby media inferred only from posting time

Weekly multi-stock PDF recommendations are explicitly deferred.

### 2.3 Future providers

The first implementation is Phintraco-specific. It must carry a canonical `provider` value in the parsed Swing Call model so the alert heading can use the `:phintraco:` custom emoji.

No generic provider adapter framework is required before a real second provider is introduced. A future provider should add its own verified parser while reusing the shared call model, delivery outbox, Discord formatter contract, and provider-first headline convention.

## 3. External identifiers

| Purpose | Name | ID |
|---|---|---:|
| Telegram source | Phintraco Sekuritas Official | `1444713822` |
| Discord alerts | `#id-stocks-swing` | `1525102458253217803` |
| Discord operations | `#hermes` | `1505162000420835388` |

The Discord target has been verified to exist. The `yanto` bot has permission to view the channel, send messages, attach files, embed links, and read message history.

## 4. Runtime model

### 4.1 Execution mode

The watcher runs as a Hermes `no_agent` job:

```text
Schedule: * * * * *
Name: idx-swing-watch-phintraco-daily
Script: idx-swing-watch-phintraco-daily.sh
Mode: no_agent
Delivery fallback: discord:1505162000420835388
```

The cron fires every minute. No LLM process is started.

### 4.2 First activation

The first successful run bootstraps from the newest Telegram message ID and forwards nothing from history.

Only calls published after activation are eligible. There is no current-day or recent-history backfill.

### 4.3 Single-instance execution

A non-blocking process lock is mandatory because one-minute runs can overlap during network delays, Discord rate limits, or slow media transfers.

The lock must cover state loading, Telegram observation, outbox processing, heartbeat handling, and state persistence.

If the lock is already held, the new invocation must:

1. Make no state changes.
2. Make no Telegram or Discord calls.
3. Print `{"wakeAgent": false}`.
4. Exit successfully.

### 4.4 Time zone

All runtime timestamps, source date rendering, logs, heartbeat times, and retry schedules use `Asia/Jakarta`.

## 5. Telegram access

### 5.1 Session

The watcher reuses the existing `POLYCOP_SESSION_STRING` authorization.

Before it touches watcher state or opens its normal Telegram workflow, the
no-agent watcher asks `telegram-resilience` for a shared probe lease. The
control-plane state is `~/.hermes/state/telegram-resilience-polyclop.json`.
During a transport cooldown, active probe, or authorization hold, it exits
cleanly without advancing its source cursor or mutating its delivery outbox.
It does not authenticate through any other Telegram profile.

This authorization has been verified from the VPS to:

- Access Phintraco Sekuritas Official.
- Fetch recent source messages.
- Download the SCMA Source Chart from Telegram message `33655`.

### 5.2 Read-only safety

The IDX Swing Watch Telegram module must be structurally read-only.

Allowed Telegram operations:

- Connect and disconnect.
- Load dialogs to resolve the source channel.
- Read source messages.
- Fetch a source message by ID for retry.
- Download attached source media.

Prohibited Telegram operations:

- Sending messages.
- Replying to messages.
- Forwarding messages.
- Editing or deleting messages.
- Adding reactions.
- Joining or leaving chats.
- Marking messages as read.

There must be no `send_message` call site in IDX Swing Watch.

### 5.3 Incremental observation

The source message ID is the event identity and observation cursor.

The watcher must:

1. Read messages whose IDs are greater than `observed_message_id`.
2. Page through the complete unseen range.
3. Process messages in chronological order.
4. Classify each message deterministically.
5. Capture every qualifying Swing Call into durable state before advancing beyond it.
6. Advance past irrelevant messages after they have been inspected.

A fixed single-page fetch must not cause older unseen messages to be skipped after an outage.

### 5.4 Telegram edits

Telegram message edits are ignored.

A source message ID is processed as a one-time event. The watcher does not revisit recent messages to detect changed captions, entries, targets, advisor names, or charts.

New target/stop-loss outcome reminders, source-marked `On support` updates, and verified active-plan status replies are eligible. Other reminder posts remain excluded.

## 6. Swing Call parsing

### 6.1 Parsed model

A parsed Swing Call contains:

```text
source_message_id
provider
ticker
call_subtype
entry
stop_loss
targets[]
signal_datetime (Telegram source-posted timestamp)
rationale
advisor_name
advisor_role
source_chart_status
```

`provider` is `Phintraco` for the initial parser.

`source_chart_status` distinguishes:

- `absent`: no photo exists on the source message.
- `expected`: a photo exists but has not been captured durably.
- `captured`: source photo is cached durably.

### 6.2 Header recognition

The header parser must tolerate spacing differences around the separator, including forms equivalent to:

```text
SCMA - Trading Buy
PTRO -Trading Buy
MBMA- Trading Buy
```

The ticker is normalized to uppercase. The Call Subtype must match one of the allowed values case-insensitively, then be rendered using the canonical capitalization.

### 6.3 Required fields

The parser accepts source variations such as:

- `Entry` with varying spaces before the colon.
- `Stop-loss`.
- `Stoploss`.
- `Target`.
- `Target 1`, `Target 2`, and `Target 3`.

A qualifying call must have one Entry, one stop-loss, and at least one target.

Targets are stored by target number and rendered in ascending order. An unnumbered Target is rendered as `Target`.

### 6.4 Price notation

The watcher must preserve the source meaning of inequalities and values.

Presentation normalization:

- A source range is rendered using `to`, such as `208 to 212`.
- `>=216` remains `>=216`.
- `<200` remains `<200`.
- Values are not wrapped in Discord inline-code markers.
- The watcher does not calculate midpoint, upside, downside, reward-to-risk, or current-price distance.

### 6.5 Rationale

The complete Phintraco rationale is preserved verbatim except for transport-safe whitespace normalization.

Allowed normalization:

- Convert non-breaking spaces to normal spaces.
- Convert line endings consistently.
- Collapse accidental repeated spaces.
- Trim leading and trailing whitespace.
- Escape Discord formatting characters only when necessary to preserve the visible source text.

The watcher must not summarize, translate, score, rewrite, shorten, or interpret the rationale.

### 6.6 Source-post timestamp

The watcher renders the Telegram message publication timestamp, converted to `Asia/Jakarta`. It does not render the date and time written inside the Phintraco caption.

The caption date may be stale, copied from an earlier plan, or otherwise disagree with Telegram's authoritative message timestamp. The watcher may parse the caption date only as a parser fallback outside the runtime message path.

The displayed weekday is derived from the Telegram publication timestamp.

Canonical display format:

```text
Fri, Jul 10 2026, 07:00 WIB
```

### 6.7 Advisor attribution

When present, retain the named advisor and role from the source message.

Canonical source line:

```text
**Source:** Phintraco Sekuritas | Alrich Paskalis T, Investment Advisor
```

If the advisor name cannot be parsed, fall back to:

```text
**Source:** Phintraco Sekuritas
```

A missing advisor does not invalidate an otherwise qualifying Swing Call.

### 6.8 Source Chart association

A Source Chart belongs to a Swing Call only when the chart photo is attached to the same Telegram message object.

The watcher must not associate:

- A later media-only message.
- A nearby daily summary image.
- A reply image.
- A weekly PDF.
- An image selected only because its timestamp is close to the call.

## 7. Swing Alert format

### 7.1 Canonical chart-backed alert

```text
### <:phintraco:1531272488645038091> BUY: **SCMA**

**Type:** Trading Buy<:up:1531285100346740766>
**Entry:** 208 to 212
**Stop-loss:** <200
**Target:** 230
**Signal date:** Fri, Jul 10 2026, 07:00 WIB

**Reasons:** Konsolidasi bertahan di atas support area 200 menjaga peluang rebound hingga minor uptrend lanjutan. MACD yang konsisten membentuk histogram positif sejalan dengan peluang tersebut.

**Source:** Phintraco Sekuritas | Alrich Paskalis T, Investment Advisor
```

The Source Chart is posted immediately afterward as a separate Discord attachment.

### 7.2 Canonical multi-target alert

```text
### <:phintraco:1531272488645038091> BUY: **BBRI**

**Type:** Buy on Support<:up:1531285100346740766>
**Entry:** 2710 to 2780
**Stop-loss:** <2670
**Target 1:** 2900
**Target 2:** 3000
**Signal date:** Fri, Jul 10 2026, 07:00 WIB

**Reasons:** Spinning bottom yang terbentuk menjadi indikasi awal rebound seiring golden cross pada MACD. Jika mampu breakout resistance 2860, menjadi konfirmasi rebound.

**Source:** Phintraco Sekuritas | Alrich Paskalis T, Investment Advisor
```

### 7.3 Canonical chartless alert

When no photo exists on the qualifying source message, post the normal text alert and append:

```text
**Chart:** Unavailable from source
```

No replacement chart is generated.

### 7.4 Formatting rules

- The first line is a Discord level-three Markdown heading: `###` followed by one space.
- The `:phintraco:` custom emoji comes first.
- BUY, SELL, and HOLD are uppercase in the heading with no status emoji. BUY and SELL place their custom direction emoji directly beside the source Type value: `Trading Buy:up:` or `Sell:down:`. HOLD places `:hold:` directly beside the source Status value.
- Ticker is bold.
- Every field label is bold.
- Field values are plain text.
- No field value uses inline code formatting.
- Signal date appears after all targets and is the Telegram source-posted timestamp.
- Reasons appear after the signal date block.
- Source appears after Reasons.
- The `Read:` line is omitted.
- No confidence, score, RSI, EMA, pullback, trend, news, execution note, or data caveat fields are generated.
- One Swing Alert must fit into one Discord text message. It must not be split into multiple text chunks.

## 8. Durable delivery outbox

### 8.1 Reason

Discord text and chart upload are two independent requests. They are not transactional.

The watcher must not copy these unsafe precedents:

- Marking a call processed before the Discord text succeeds.
- Treating text success as complete when a Source Chart upload fails.

### 8.2 State phases

Outbox phases:

```text
pending_media_capture
pending_text
pending_chart
delivered
```

Transitions:

```text
pending_media_capture -> pending_text -> pending_chart -> delivered
```

For a chartless call:

```text
pending_text -> delivered
```

### 8.3 Discovery persistence

For each qualifying call:

1. Atomically add the parsed event to the outbox.
2. If a Source Chart exists, mark it `pending_media_capture`.
3. If no Source Chart exists, mark it `pending_text` and include the chart-unavailable field.
4. Persist the source event before advancing `observed_message_id` beyond it.

If media capture succeeds, store the chart in durable runtime media storage and transition to `pending_text`.

A media download failure must not be treated as a chartless source. It remains `pending_media_capture` and is retried.

### 8.4 Text delivery

For the oldest outbox item in `pending_text`:

1. Post exactly one Discord text message.
2. Require HTTP success.
3. Record the returned Discord message ID.
4. Atomically persist the transition.
5. If a chart was captured, transition to `pending_chart`.
6. If the source had no chart, transition to `delivered`.

If text delivery fails, do not attempt a chart upload.

### 8.5 Chart delivery

For an item in `pending_chart`:

1. Upload the cached source image as a separate Discord message.
2. Require HTTP success.
3. On success, transition to `delivered`.
4. Remove the cached media only after the delivered state is durable.

If chart upload fails:

- Keep the event in `pending_chart`.
- Retry only the chart.
- Never repeat the text.
- Apply bounded exponential backoff with a reasonable maximum interval.

### 8.6 Strict FIFO adjacency

Outbox delivery is strict first-in, first-out.

The watcher must fully resolve the oldest event before posting a newer event. This preserves:

```text
text for call 1
chart for call 1
text for call 2
chart for call 2
```

A failing chart can delay newer calls. This is an accepted trade-off to preserve alert and chart adjacency.

### 8.7 Event identity

The Telegram source message ID is the sole duplicate identity.

- Reprocessing the same source message ID is suppressed.
- Two different source message IDs are two different Swing Calls, even if ticker, date, entry, stop-loss, and targets match.
- There is no one-ticker-per-day suppression.

## 9. State and storage

### 9.1 State location

```text
~/.agents/skills/idx-swing-watch-phintraco-daily/state/state.json
~/.agents/skills/idx-swing-watch-phintraco-daily/state/media/
~/.agents/skills/idx-swing-watch-phintraco-daily/state/run.lock
~/.agents/skills/idx-swing-watch-phintraco-daily/state/watchdog-notices.json
```


### 9.1.1 Clean rename migration

The rename from `idx-swing-watch` is a clean cutover, not a compatibility layer. With the daily Hermes job paused and its process lock unavailable, move the complete private state directory from the old runtime path to the new path before enabling `idx-swing-watch-phintraco-daily`. The migrated `state.json`, cached media, and watchdog metadata retain their existing cursor, outbox, retry, and deduplication values. The old runtime directory and cron entry are removed only after the new named job completes a dry run against the migrated state.
Runtime state and media are excluded from deployment synchronization.

### 9.2 State shape

```json
{
  "version": 1,
  "observed_message_id": 0,
  "outbox": {},
  "last_poll_success": null,
  "last_delivery_success": null,
  "last_heartbeat_hour": null,
  "last_error_notice": null,
  "stats": {
    "runs": 0,
    "messages": 0,
    "calls": 0,
    "delivered": 0
  }
}
```

`last_error_notice` remains `null` until a fatal notice succeeds. Version 1 state accepts
that deployed `null` value. After a successful fatal notice it stores the current WIB
hour and a bounded set of reported fingerprints:

```json
{
  "hour": "2026-07-10T08+07:00",
  "fingerprints": ["0123456789abcdef"]
}
```

The scanner retains at most 64 fingerprints for the current hour so alternating
failures are each reported once without allowing the collection to grow without bound.
The watchdog keeps equivalent notice metadata in `watchdog-notices.json`, written by
atomic replacement. It reads `state.json` without modifying scanner cursor, outbox, or
delivery fields.

Each outbox entry stores enough parsed source data to render text without reparsing a changed source message. A media retry may fetch the original Telegram message by ID when capture has not completed.

### 9.3 Atomic writes

State writes use a sibling temporary file followed by atomic replacement.

The state must be persisted after each externally visible delivery transition, especially immediately after Discord text success.

### 9.4 Corrupt state

Missing state is a valid first-run condition.

Corrupt existing state must:

1. Be backed up with a timestamped corrupt filename.
2. Fail closed.
3. Post or attempt a canonical fatal notice to `#hermes`.
4. Avoid bootstrapping past potentially pending deliveries.

It must not silently reset to empty state.

### 9.5 Runtime media

Captured Source Charts use deterministic filenames derived from provider and source message ID.

Example:

```text
phintraco-33655.jpg
```

Runtime directories should be private to the service account. Secrets and media bytes must never be printed in logs.

## 10. Discord behavior

### 10.1 API

Use Discord API v10 with the bot token from `~/.hermes/.env`.

The helper must:

- Bound every request with a timeout.
- Honor HTTP 429 `retry_after` values.
- Retry transient network failures with bounded backoff.
- Treat non-success responses as delivery failures.
- Return the created Discord message ID on success.
- Log sanitized response details without exposing the bot token.

### 10.2 Text length

The formatter must enforce one Discord text message per Swing Alert.

If an unexpected source rationale would exceed the Discord message limit, treat the call as degraded and report it operationally. Do not split the alert because splitting breaks the text-and-chart contract.

### 10.3 Attachment type

Telegram photo messages are uploaded to Discord as source image attachments. The watcher does not modify, annotate, regenerate, crop, or compress the Source Chart unless Discord rejects the original solely because of platform constraints.

## 11. Heartbeat and failure reporting

### 11.1 Heartbeat destination

All operational heartbeats go to Discord `#hermes`:

```text
1505162000420835388
```

They do not go to `#id-stocks-swing`.

### 11.2 Heartbeat cadence

The one-minute cron posts at most one heartbeat per WIB hour.

Use persisted `last_heartbeat_hour`, not an exact `minute == 0` condition. If the current WIB hour differs from the stored hour, attempt the heartbeat. Persist the hour only after the Discord post succeeds.

### 11.3 Healthy heartbeat

```text
🫀 idx-swing-phintraco-daily · 08:00 WIB · 42 messages · 3 calls · 3 delivered · 0 pending
```

### 11.4 Degraded heartbeat

```text
🫀 idx-swing-phintraco-daily · 08:00 WIB · 42 messages · 3 calls · 2 delivered · 1 pending ⚠️
```

A run is degraded when any of these are true:

- Telegram polling partially fails.
- A source media capture is pending because of an error.
- Discord text delivery is pending because of an error.
- Discord chart delivery is pending because of an error.
- A qualifying source message is malformed.
- A chart expected from Telegram cannot currently be downloaded.
- Target permissions or authentication fail.

A chartless call whose source genuinely has no photo is not a failure after its text-only alert is delivered.

### 11.5 Fatal format

```text
❌ idx-swing-phintraco-daily · 08:01 WIB · failed: <sanitized short reason>
```

Repeated fatal notices from a one-minute cron must be rate-limited by error fingerprint and hour so an outage does not flood `#hermes`.

### 11.6 No-agent output

Successful run:

```json
{"wakeAgent": false}
```

Handled fatal run:

```json
{"wakeAgent": false, "error": "<sanitized reason>"}
```

The scanner exits successfully after a handled fatal because it has already reported the failure and must not wake an LLM agent.

## 12. Wrapper

`idx-swing-watch-phintraco-daily.sh` must:

1. Set `TZ=Asia/Jakarta`.
2. Set a deterministic locale and PATH.
3. Self-load only these required secrets from `~/.hermes/.env`:
   - `DISCORD_BOT_TOKEN`
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`
   - `POLYCOP_SESSION_STRING`
4. Use the shared VPS Python environment that already contains Telethon and Requests.
5. Run the scanner.
6. Append diagnostics to `~/.logs/idx-swing-watch-phintraco-daily.log`.
7. Pass the scanner stdout contract back to Hermes unchanged.
8. Preserve the scanner return code.

The wrapper must not print secret values.

## 13. File layout

Mac source-of-truth development directory:

```text
~/Documents/Projects/Hermes/idx-swing-watch-phintraco-daily/
  CONTEXT.md
  SPEC.md
  SKILL.md
  bin/
    scan.py
    idx-swing-watch-phintraco-daily.sh
    watchdog.py
  tests/
    conftest.py
    test_scan.py
    fixtures/
```

VPS runtime:

```text
~/.agents/skills/idx-swing-watch-phintraco-daily/
  SKILL.md
  bin/
    scan.py
    watchdog.py
  state/
    state.json
    media/
    run.lock

~/.hermes/scripts/idx-swing-watch-phintraco-daily.sh
~/.logs/idx-swing-watch-phintraco-daily.log
```

The project is authored on the Mac, deployed to the VPS, verified there, and then mirrored back through the established backup workflow. Runtime state must never be overwritten during deployment.

## 14. Dry-run and operations controls

Required controls:

```text
IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST=1
IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH=<path>
IDX_SWING_WATCH_PHINTRACO_DAILY_FORCE_HEARTBEAT=1
```

Dry-run behavior:

- Connect and read Telegram when credentials are available.
- Parse real messages.
- Download media when needed for verification.
- Print sanitized intended Discord operations.
- Never post to Discord.
- Use an explicitly overridden temporary state path during tests or manual verification.

Recommended health probe output:

- Last successful poll.
- Last successful delivery.
- Observation cursor.
- Outbox counts by phase.
- Oldest pending event age.
- Last heartbeat hour.
- Total calls and delivered calls.

## 15. Test requirements

### 15.1 Parser tests

- Trading Buy parses successfully.
- Buy on Support parses successfully.
- Speculative Buy parses successfully.
- Header spacing variations parse successfully.
- Entry spacing variations parse successfully.
- Stop-loss and Stoploss both parse.
- Unnumbered Target parses.
- Target 1, Target 2, and Target 3 parse.
- Targets render in ascending order even when source order is reversed.
- Source range renders with `to`.
- Inequality operators preserve meaning.
- Telegram source-post timestamp overrides the stated source-caption date and renders with the correct WIB weekday.
- Source-caption dates remain a non-runtime parser fallback only.
- A source-marked `On support` update parses as `STATUS`, including any supplied Entry, Stop-loss, and Targets.
- A same-ticker `on track` reply to a parsable `BUY` or `STATUS` parent parses as `STATUS`.
- A same-ticker `on trac` reply normalizes to `on track` only after the same parent validation.
- Full rationale is preserved with whitespace normalization only.
- Advisor name and role parse when present.
- Missing advisor falls back to source-only attribution.

### 15.2 Rejection tests

- Reminder posts without a target-achieved or stop-loss-hit outcome are rejected.
- Sell on Strength is rejected.
- Composite update is rejected.
- Daily summary image is rejected.
- Weekly multi-stock text bundle is rejected.
- Weekly PDF is rejected.
- Media-only message is rejected.
- Buy-like text missing Entry is rejected.
- A footerless reply status is rejected unless it matches its parsable parent ticker and parent event type.
- Buy-like text missing stop-loss is rejected.
- Buy-like text missing every target is rejected.

### 15.3 Source Chart tests

- Same-message photo is recognized as a Source Chart.
- Nearby media-only message is never associated.
- No-photo qualifying call produces a text-only alert with `Chart: Unavailable from source`.
- Existing photo download failure enters `pending_media_capture` rather than chartless delivery.
- Captured media survives process restart.

### 15.4 Bootstrap and observation tests

- Missing state bootstraps at the newest message without forwarding history.
- Messages are processed chronologically.
- Complete unseen ranges are paginated without gaps.
- Irrelevant messages advance the observation cursor safely.
- Qualifying calls enter durable outbox state before cursor advancement.
- Telegram edits are ignored.
- Two different source message IDs for the same ticker are both eligible.
- The same source message ID is never redelivered after completion.

### 15.5 Delivery state tests

- Text failure does not attempt chart upload.
- Text success stores the Discord text message ID.
- Text success with a chart transitions to `pending_chart`.
- Chart upload failure remains `pending_chart`.
- A later run retries chart only and never repeats text.
- Text success without a source chart transitions directly to delivered.
- Successful chart upload transitions to delivered and removes cached media.
- Strict FIFO produces text 1, chart 1, text 2, chart 2.
- A failing older chart blocks newer alert delivery.
- Discord HTTP 429 respects retry timing.
- Discord timeout preserves the correct pending phase.

### 15.6 State and lock tests

- State roundtrip is atomic.
- Corrupt state is backed up and fails closed.
- Pending delivery survives restart.
- Lock contention makes no state or network changes.
- Successful lock owner releases the lock on every exit path.

### 15.7 Heartbeat tests

- Heartbeat uses `idx-swing-phintraco-daily` and the canonical separators.
- Heartbeat posts once per WIB hour.
- A delayed run in a new hour still posts a heartbeat.
- Failed heartbeat does not persist the hour key.
- Pending delivery adds the degraded marker.
- Genuine chart absence after text-only delivery is not degraded.
- Fatal notice is rate-limited.
- Normal and handled-fatal paths both emit `wakeAgent: false`.

## 16. Acceptance criteria

The implementation is accepted when all of the following are demonstrated:

1. Hermes runs `idx-swing-watch-phintraco-daily` every minute in no-agent mode.
2. The runtime calls no LLM.
3. First activation does not replay historical calls.
4. A new Trading Buy, Buy on Support, Speculative Buy, qualifying outcome reminder, source-marked `On support` update, or verified same-ticker reply status is detected within the next successful polling cycle.
5. The alert uses the exact provider-first plain Markdown format specified here.
6. Labels are bold and values are plain text without inline-code formatting.
7. Displayed event dates use Telegram source-post timestamps in the specified English date format and WIB time.
8. Full source rationale is retained without generated analysis.
9. Source and advisor attribution are retained when available.
10. A same-message Source Chart is posted immediately after the text.
11. A genuinely chartless call is posted text-only with the chart-unavailable field.
12. A failed existing-chart upload retries only the chart and never duplicates the text.
13. Strict FIFO ordering prevents later calls from interleaving ahead of a pending chart.
14. Weekly multi-stock text and PDF recommendations are not forwarded.
15. Unqualified reminder posts, sell calls, summary posts, and unrelated research are not forwarded.
16. Event deduplication uses Telegram source message ID only.
17. Telegram edits are ignored.
18. The existing PolyCop Telegram session is reused without any Telegram write operation.
19. One hourly heartbeat reports liveness to `#hermes`, including no-call runs.
20. Runtime state, cached charts, secrets, and logs are not overwritten by deployment.
21. Focused parser, delivery, state, lock, and heartbeat tests pass.
22. A VPS dry run proves source access, parsing, media download, and intended Discord ordering without posting.
23. A controlled live smoke test proves text followed by chart in `#id-stocks-swing`.

## 17. Deferred work

Explicitly deferred:

- Weekly multi-stock PDF parsing.
- Extracting individual charts from weekly PDFs.
- Detecting or propagating Telegram edits.
- Calculating live IDX prices.
- Calculating confidence, score, RSI, EMA, pullback, or trend.
- Fetching news context.
- LLM summarization or classification.
- Generic provider adapter framework.
- Trade execution or broker integration.
