# Stockbit Snips watcher

This package supplements the repository `AGENTS.md` and owns the development
source for the agent-backed `cron-stockbit-snips` watcher.

`cron-rss-source-ingest` is the active source adapter for the same four fixed
lanes. The existing Hermes job `cron-stockbit-snips` (job `0c6b17e4c944`,
every 15 minutes at the 2026-09-29 live check) runs that adapter's wrapper.
There is no second RSS schedule. Accepted source events carry a validated
frozen configuration snapshot. `bin/pipeline_owner.py` admits text-only
articles to this watcher's article queue with durable source-work provenance.
It rejects a conflicting legacy article or revision and claims only
source-backed articles for the RSS runner's agent wake. Its `drain-delivery`
command settles up to three due, already accepted articles without fetching
RSS or claiming an agent item. It preserves the frozen target and stable
Delivery Owner operation, persists the delivered or retry phase, and retries
publication intents. This package retains the domain queue, routes, rendering,
Delivery Owner path, and heartbeat. Do not re-enable the legacy direct RSS
poller beside the active adapter.

## Boundary

- The source is public RSS from `https://snips.stockbit.com/`.
- The four configured lanes are Stockbit Commentary, Unboxing, Unboxing IPO,
  and AI Reports Stockbit.
- The scanner owns RSS fetching, conditional requests, cursoring, deduplication,
  bounded agent input, durable outbox state, rendering, Discord delivery, and
  heartbeats.
- Hermes receives one source-grounded article at a time and returns only the
  closed analysis schema documented in `SKILL.md`.
- The agent must not browse, fetch URLs, inspect state, or add outside facts.
- A fresh live cursor is future-only. It must not backfill history.
- Each run requires one validated live control-plane configuration revision.
  A missing or invalid revision blocks new RSS intake; there is no static
  configuration fallback. The four RSS URLs and lane IDs remain source-owned.
- The database owns each lane's enabled switch, the two Discord destinations,
  and the bounded additional operator instruction. The heartbeat destination,
  output schema, and agent safety rules stay fixed.
- State version 2 upgrades version 1 in place without dropping cursors,
  articles, leases, or retries. Each dispatched article binds its config
  revision, operator instruction, and destination IDs. Later edits do not
  rewrite that article's frozen settings.
- The initial polling cadence is 15 minutes. Operators may request intervals
  from 5 to 60 minutes; the live Hermes schedule changes only after the
  separately approved reconciler applies a desired schedule revision.

## Rendering contract

- The visible provider byline is `Stockbit`.
- The provider marker is `<:stockbit:1552220036557578311>`.
- Titles are regenerated in natural Bahasa Indonesia and sentence case. They
  preserve tickers, acronyms, proper nouns, and official names where needed.
- The first summary paragraph starts with `*(Ringkasan)* `, added by the
  renderer rather than the agent.
- A central single IDX issuer routes to `id_stocks_news` and receives the
  standard latest price, 1D, 1W, 1M, and 3M card.
- A connected multi-issuer, sector, or macro thesis routes once to `macro_news` without
  a price card. Supporting ticker mentions do not create issuer cards.
- Missing market data renders `-` with the existing grey direction marker. It
  is not rendered as zero and does not fail the article.
- AI Reports does not receive an additional AI disclaimer in the Discord copy.

## Safe operation

- `preview` fetches the first RSS page from every lane without state or Discord
  mutation.
- `STOCKBIT_SNIPS_NO_POST=1` requires a temporary state path and never calls
  Discord or writes control-plane run events. It still performs the required
  live config GET. Release verification uses a fresh temporary state, so it
  cannot submit an article for agent analysis.
- The wrapper imports the Stockbit control-plane URL, watcher ID, token, and
  timeout plus the Delivery Owner URL and client/admin token-file paths from
  Hermes's `.env`. It also imports the optional Published Feed URL, enable
  switch, and owner token-file path. It unsets `DISCORD_BOT_TOKEN`, requires the deployed
  `lib-bursawatch-control` client and the shared Discord delivery client, and
  never sets an event spool path. It imports the live Stockbit configuration
  settings even in release no-post mode; missing or invalid live configuration
  blocks RSS intake, with no static fallback.
- Discord article sends and heartbeats go through the shared Delivery Owner
  client. Once accepted, the owner's durable retry state is authoritative and
  the local article stays pending until the owner returns a delivered receipt.
  The operator-only `delivery-handoff --plan <path>` command reconstructs
  pending operations from their saved rendered content and frozen live
  configuration snapshot. Its gated `--apply <path>` requires
  `BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY=1` and the admin token-file setting.
  It never runs during RSS polling, agent submission, or state migration.
- The one-time first-page backfill is a later, separately approved operation.
- Do not add, enable, pause, or reschedule the live Hermes job from this
  package without explicit approval.

## Development

Run the focused package tests, then the repository package suite and
`bash scripts/test-all`. The runtime identity is
`bursawatch-stockbit-snips`; the deployed skill directory is
`~/.agents/skills/bursawatch-stockbit-snips/`; and the wrapper is
`~/.hermes/scripts/bursawatch-stockbit-snips.sh`.

## Discord delivery receipt wait

After an accepted operation returns a nonterminal receipt, the sender waits for up to the shared `DELIVERY_RECEIPT_WAIT_SECONDS` setting (10 seconds) on that same stable operation. If it remains pending, the existing durable retry path continues without a new operation key.

For `channel_message_create`, the shared receipt contract requires a valid
`message_id`; `channel_id` may be omitted. The operation key and digest must
match the stable operation for the article's frozen destination. If the receipt
includes `channel_id`, it must match that frozen destination. Persist the local
destination from the frozen configuration snapshot, and mark the article
delivered only after the shared client returns a delivered receipt.

## Published Feed projection

Eligible articles accepted from the shared RSS source adapter create one
Published Feed record only after the Stockbit text operation has a durable
Delivery Owner receipt with matching operation key and payload digest, delivered
status, destination, and Discord message ID. The article owner stores the exact
rendered text, source event identity, frozen config revision, receipt, and
pending projection intent before changing the article to `delivered`. Excluded
articles and articles without shared-source provenance do not enter the feed.

The projection accepts a message-only delivered receipt after the shared client
validates its key and digest against the operation for the frozen destination.
An explicit receipt channel must match that destination.

The projection drain retries only the saved snapshot through the shared
`PublicationClient`, then persists the accepted publication ID, version, and
digest. It never calls Discord. Outstanding intents remain in the owner ledger,
which reports the latest confirmed boundary, contiguous accepted boundary, and
outstanding count. Projection writes stay disabled unless
`BURSAWATCH_STOCKBIT_SNIPS_PUBLICATION_ENABLED=1`; the shared URL and this
owner's private token file are `BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL` and
`BURSAWATCH_STOCKBIT_SNIPS_PUBLICATION_TOKEN_FILE`. The forward-only feed
cutover is a separate activation boundary.

## Shared generated-news format

`lib-news-format` owns the common writing instruction, renderer, and
optional deterministic quote lookup. Report directly in Indonesian and
preserve research attribution, periods, units, and uncertainty. Prefer two
short paragraphs for longer summaries; concise or cohesive items may use one.
No fixed paragraph threshold or style-based relevance gate applies. Return
plain summary text without a Ringkasan marker. The renderer adds it once and
normalizes legacy markers. Existing structural, identity, capability, and
source-specific safety checks remain mandatory.

Split independent issuer developments into ordered items, including separate
issuer dividends and suspension reopenings. Keep a connected transaction or
one broad thesis as one story. Each generated issuer card has a ticker-led
headline, source byline, latest native-currency price and 1D/1W/1M/3M absolute
and percentage changes, plus the original source link. IDX uses IDR and US
uses USD. Missing quotes or individual horizons use grey `-` placeholders;
macro and industry cards omit the tracker. Prices are renderer enrichment,
never model-generated news facts. Forecasts and incomplete amounts must not
be made certain or filled in.

New generated cards freeze their rendered text and quote timestamp before
Discord delivery. X, Instagram, and WhatsApp also freeze each card's selected
destination. Retries and Published Feed projections use those saved cards and
stable operation identities. Existing pending records without new cards keep
their legacy path. Profiles with generated summaries disabled retain their
explicit raw-forwarding policy. Specialized Swing/Board and Stock Information
contracts remain owner-specific.

The LLM owns semantic relevance. Market-keyword signals are advisory and
cannot veto `is_relevant: false`. Generic investing education remains
excluded even when it mentions earnings, dividends, charting, or an issuer.
There is no deterministic education denylist.

Stockbit accepts the ordinary scalar schema or `{candidate_key, items}`.
Each item has the scalar fields except `candidate_key`. A split parent keeps
its source cursor and child identity list; each child has a separate durable
article record, frozen configuration, payload, receipt and publication key.
The parent is `split`, while children retain normal delivery phases.
