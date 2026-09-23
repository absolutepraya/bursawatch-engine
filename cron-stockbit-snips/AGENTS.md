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
- The intended polling cadence is 15 minutes. The live Hermes schedule remains
  a separate operational approval.

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
  Discord. It is the required local verification control.
- The one-time first-page backfill is a later, separately approved operation.
- Do not add, enable, pause, or reschedule the live Hermes job from this
  package without explicit approval.

## Development

Run the focused package tests, then the repository package suite and
`bash scripts/test-all`. The runtime identity is
`bursawatch-stockbit-snips`; the deployed skill directory is
`~/.agents/skills/bursawatch-stockbit-snips/`; and the wrapper is
`~/.hermes/scripts/bursawatch-stockbit-snips.sh`.
