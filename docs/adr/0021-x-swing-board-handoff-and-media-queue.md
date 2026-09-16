# X Swing board handoff and media queue behavior

Status: accepted

## Context

The three X profiles routed to `id_stocks_swing` already produce useful
chronological alerts in `#id-stocks-swing`. The per-ticker Swing Plan Board
should expose that context without treating an X chart, target, or stop-loss
phrase as a complete Phintraco trading plan. The existing X outbox also uses
ordered text and media delivery, so a permanently deleted X image must not
starve unrelated events behind it.

## Decisions

- Deliver the accepted X event to All Swing first. After every All text and
  usable media leg is durable, submit at most one source-only `social` event to
  the Swing Plan Board. X board events have `plan: null` and never own prices,
  target checkpoints, stop-loss state, tags, or episode lifecycle.
- Add the generic Swing forum `Board` link to the All Swing X rendering only.
  The board copy omits that line. Normalize only the board starter title to
  `TICKER: ...`; keep the raw ordered X text in the source reply.
- Accept a board handoff only when the first source-visible line is led by one
  ticker followed by a colon or whitespace, the accepted title begins with the
  same ticker, and the complete assembled thread has no second ticker-led
  clause. Otherwise keep the event All-only.
- Preserve the existing board promotion contract. A later complete Phintraco
  plan remains the only Primary Plan source, and the board engine keeps its
  one-time GTW promotion resend where applicable. The X watcher does not issue
  a duplicate X resend.
- Treat confirmed HTTP 404 or 410 while downloading one source media URL as a
  terminal failure for that item only. Record the skipped URL and degraded
  error, preserve accepted text and other media, advance the media cursor, and
  continue the queue. Retry transient HTTP and transport failures.
- Preserve queue order and do not prioritize Swing routes. Existing queued
  Swing events complete naturally after deployment. Do not backfill historical
  delivered X posts or reset live state.

## Consequences

The board gains focused X context without weakening its Primary Plan boundary,
and a missing X image cannot permanently block later deliveries. A board
episode may contain X source context before Phintraco promotion, but it has no
market checkpoint until a Primary Plan exists. The delivery ledger records
media skips for operational review, while source and board ownership remain
separate.
