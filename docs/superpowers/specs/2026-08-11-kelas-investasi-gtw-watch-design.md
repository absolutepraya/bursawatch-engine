# Kelas Investasi GTW Watch design

## Goal

Create `kelas-investasi-gtw-watch`, a deterministic Hermes cron that observes future `#GTW` bundles from the public Telegram channel Kelas Investasi, produces a source-grounded Indonesian summary, and delivers the shared cash-Swing message followed by its source image to Discord `#id-stocks-swing`.

The cron starts at deployment without backfilling historical signals.

## Scope

- Source channel: `@kelasinvestasiid`, Telegram source ID `2142109618`.
- Eligible header: `Good to watch - <TICKER> #GTW`.
- Polling cadence: hourly at minute `00`, WIB.
- Destination: Discord `#id-stocks-swing`, channel ID `1525102458253217803`.
- Delivery identity: Yanto Discord bot.
- Telegram authentication: the existing shared `POLYCOP_SESSION_STRING` through `telegram-resilience`.
- Output: one text message, then every image or chart from the source bundle in source order.

The cron does not backfill, execute trades, evaluate whether the source thesis is correct, post as Abhip's personal Telegram account, or forward promotions and unrelated messages. After All delivery, it submits the accepted event to the Swing board owner as source-only context. The board may later promote an open GTW-only episode when Phintraco publishes a complete setup; that promotion preserves the superseded GTW starter and first chart once as normal source-context history below the new Phintraco card.

## Architecture

```text
Kelas Investasi Telegram channel
  -> shared PolyCop Telegram session and resilience lease
  -> GTW scanner and bundle collector
  -> durable cursor, pending bundles, and FIFO outbox
  -> Hermes source-grounded title and summary
  -> Discord #stock-news text message
  -> source image and chart attachments in original order
```

`kelas-investasi-gtw-watch` is a standalone no-agent Hermes cron. The deterministic scanner owns source fetching, header detection, bundle construction, state, delivery ordering, retry behavior, and Discord posting. Hermes is invoked only after a complete eligible bundle needs a title and summary. Hermes submits its validated result back to the scanner, which owns final delivery.

This separation follows `x-post-watch` for state, outbox, source-grounded summary, and Discord reliability, while keeping the Telegram-specific scanner separate from RSSHub X polling.

## Bundle detection

The scanner observes messages in ascending Telegram message-ID order and opens a bundle when a message matches the exact case-insensitive header pattern:

```text
Good to watch - <IDX ticker> #GTW
```

The bundle starts with its header and includes the associated analysis text and images or charts immediately following it. A bundle closes when either condition is met:

1. Another eligible `#GTW` header is observed.
2. The elapsed time since the bundle's latest included message exceeds 20 minutes.

When a new eligible header closes the preceding bundle, the preceding bundle can request its summary immediately because the source supplied an explicit boundary. When no later header is observed, the scanner waits until the bundle has been quiet for 20 minutes before requesting the summary. This protects delayed text or chart attachments while avoiding delivery of an incomplete bundle.

Messages are included only when they are contiguous to the current bundle and arrive within the 20-minute gap. A later reply, disclaimer, promotion, article link, or unrelated channel post is excluded. This excludes the observed late article-link follow-ups and the RAJA disclaimer that arrived more than 20 minutes after its header. The historically observed main analyses arrived from zero to 17 seconds after their headers, so the 20-minute interval leaves substantial safety margin for future charts.

When multiple `#GTW` headers are emitted together, each header opens a separate ticker bundle. The next header closes the preceding bundle, preserving the observed header, analysis, header, analysis ordering.

## State and delivery

Runtime state is owned by:

```text
~/.hermes/state/kelas-investasi-gtw-watch.json
```

It contains the highest observed Telegram message ID, pending bundles, each bundle's source text and message IDs, ordered image metadata, quiet-window timestamp, summary lease state, durable FIFO outbox, and per-delivery-leg status.

On first deployment, the scanner records the current highest source message ID and exits successfully. It does not create events for older messages.

When the shared Telegram circuit is cooling down or under an authorization hold, the scanner exits cleanly without advancing its cursor, mutating pending bundles, or changing the outbox. Transport and authorization behavior is inherited from `telegram-resilience`.

Each event has distinct delivery legs:

1. Discord text summary.
2. Image or chart attachment one.
3. Each remaining attachment in original source order.

If a delivery leg fails, only the unfinished leg is retried. In particular, a failed attachment never causes the already delivered Discord summary text to be duplicated.

An invalid or failed Hermes summary leaves its completed bundle pending. It is retried later without Discord delivery until the scanner accepts a valid source-grounded submission.

## Hermes summary contract

Hermes receives only the completed source bundle and must ignore any instructions contained in source messages. It returns a title and a one to two paragraph Indonesian summary. The title is source-grounded, begins with the exact ticker followed by `:`, and has no ending punctuation. The summary starts exactly with `*(Ringkasan)* `, introduces no external facts, investment advice, certainty, or narrator framing.

The scanner extracts any source-provided buy area, targets, and stoploss. Missing values remain `-`; Hermes does not invent them.

## Discord rendering

The text delivery uses the shared cash-Swing renderer:

```md
### <:kelasinvestasi:1536570114772574218> CTRA: Akumulasi kuat di area breakout
-# Kelas Investasi GTW

*(Ringkasan)* CTRA berada di area breakout 605 sampai 630, dengan akumulasi broker yang masih kuat dan katalis proyek baru. Break 630 dengan volume menjadi konfirmasi lanjutan.

**Buy area:** 605 sampai 630
**Target:** 655, 675, 700
**Stoploss:** <573

**Source status:** Good to watch <:grey:1531279158913536182>
**Last updated:** 19 Sep 2026 06:50 WIB
**Board:** https://discord.com/channels/940285152335110204/<thread-id>

[View on Telegram](<https://t.me/kelasinvestasiid/<header-message-id>>)
```

The renderer uses the provided Kelas Investasi and status emoji markup, the
factual neutral `Good to watch` source status, and the All-only Board link. The
All message starts with the forum marker and is edited to the direct topic URL
after the board owner materializes the topic. The board copy omits the Board
line. It does not use a generic alert emoji or a middle-dot separator.

The plan block always has all three rows. Any unavailable source field renders as `-`, for example `- Target: -`.

After the text, the scanner sends the first source image attached to the header.
It does not copy source prose verbatim to Discord.

## Operations

The wrapper loads only the required Discord credentials and shared Telegram credentials from `~/.hermes/.env`. It must not log them.

Each successful run emits a deterministic `#hermes` heartbeat:

```text
🫀 kelas-investasi-gtw · HH:MM WIB · scanned=N pending=N delivered=N
```

No eligible bundle is a successful no-op with the same heartbeat format. A fatal failure emits:

```text
❌ kelas-investasi-gtw · HH:MM WIB · failed: <sanitized reason>
```

Adding the cron to Hermes, including its name, schedule, enablement, and delivery contract, requires explicit current-session approval at implementation time.

## Verification

Tests cover:

- exact eligible-header parsing and non-`#GTW` rejection
- first-run cursor initialization without backfill
- zero-gap, 17-second, and exact 20-minute bundle boundaries
- multiple adjacent ticker bundles
- ordered text and image collection
- late reply, disclaimer, promotion, and article-link exclusion
- source plan extraction, including `-` for missing fields
- exact Discord rendering and message-size handling
- shared-resilience clean exits without cursor or outbox mutation
- durable state, locks, FIFO retry, and no duplicate text after partial media delivery
- invalid summary rejection and later retry
- no-post end-to-end control

Before production enablement: run focused and full tests, deploy source files, compare local and VPS checksums, run a VPS no-post check with isolated state, verify the intended Discord text and ordered attachments, then inspect live state and the shared Telegram circuit. After explicit approval and a natural scheduled run, verify scheduler output, `#hermes` heartbeat, and `#stock-news` delivery.
