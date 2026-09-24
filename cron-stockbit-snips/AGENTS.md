# Stockbit Snips watcher

This package supplements the repository `AGENTS.md` and owns the development
source for the agent-backed `cron-stockbit-snips` watcher.

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
- A multi-issuer, sector, or macro thesis routes once to `macro_news` without
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
- The wrapper imports only the Stockbit control-plane URL, watcher ID, token,
  and timeout from Hermes's `.env`, even in release no-post. It requires the
  deployed `lib-bursawatch-control` client and never sets an event spool path.
- The one-time first-page backfill is a later, separately approved operation.
- Do not add, enable, pause, or reschedule the live Hermes job from this
  package without explicit approval.

## Development

Run the focused package tests, then the repository package suite and
`bash scripts/test-all`. The runtime identity is
`bursawatch-stockbit-snips`; the deployed skill directory is
`~/.agents/skills/bursawatch-stockbit-snips/`; and the wrapper is
`~/.hermes/scripts/bursawatch-stockbit-snips.sh`.
