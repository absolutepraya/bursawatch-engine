# IDX Swing plan board

Status: accepted

## Context

The regular `#id-stocks-swing` channel is the chronological All Swing feed.
The additional forum must make a focused ticker's current cash-equity Swing
plan and relevant source history readable without implying that a user traded
it. The forum must preserve Phintraco's complete setup and chart, tolerate
delayed Yahoo data, and not mix cash-equity plans with SSF derivatives calls.

## Decisions

- The live forum is `#id-stocks-swing-board` (`1548273399069933720`) under the
  Invest & Trade category. It is empty until the approved implementation and
  bootstrap are ready. It uses latest-activity ordering and Discord's maximum
  seven-day auto-archive duration.
- The forum is view-only for regular members. Yanto and server administrators
  retain the permissions required to create, edit, reply to, tag, and archive
  episodes. Members cannot create posts, reply, or react.
- `#id-stocks-swing` remains the All channel. Its current source alerts stay
  chronological. The new board is an additional per-ticker view.
- Each forum post is a ticker episode. Source-only episodes retain their
  source-exact title. Promoted and Phintraco-created episodes use ticker-first
  titles such as `DSSA: Buy`.
- Phintraco Daily is the only Primary Plan source. A qualifying cash-equity
  social plan can create source-only context and is promoted in place if a
  complete Phintraco setup arrives within 20 exchange trading sessions.
- The top card is always bot-managed. Social content is a normal source reply,
  so promotion never rewrites, deletes, or duplicates the source item. A
  source-only episode receives no market checkpoint.
- A Primary Plan tracks Source Status separately from a factual after-close
  Market Checkpoint. Phintraco changes Source Status immediately. The
  deterministic status owner checks valid same-day price data at 16:30 WIB on
  IDX trading days, retries once at 17:00 WIB, and otherwise preserves the
  prior state while rendering `Market check unavailable`.
- Market states are factual: `Below entry`, `Entry zone`, `Above entry`,
  `TP1 reached` through `TP6 reached`, and `Stop-loss breached`. They never
  imply user action such as buying, holding, cutting loss, or taking profit.
  A direct Phintraco status update changes the price-state tag immediately only
  when it explicitly confirms a mapped target or stop outcome.
- Every episode has one lifecycle tag: `Source plan`, `Primary plan`, or
  `Resolved`. A primary or resolved episode receives a market-state tag only
  after a reliable price checkpoint or explicit Phintraco outcome is known.
- A resolved episode gets no artificial retention update. Discord archives it
  after seven inactive days, where it remains retrievable history. A later
  complete Phintraco plan opens a fresh episode.
- Bootstrap once from retained Telegram Phintraco history. Reconstruct only
  unambiguous current plans and their original charts and relevant source
  status messages. Never infer missing setup fields or fabricate historical
  Market Checkpoints.
- Raw multi-ticker social posts stay in All Swing unless the source provides a
  distinct, source-exact plan per ticker. Phintraco SSF is excluded entirely.
- The deterministic Swing status owner exclusively writes
  `~/.hermes/state/idx-swing-board.sqlite3`. Existing watcher JSON state stays
  private to its owning watcher.
- Phintraco Swing renders ticker-first headings without redundant title bolding,
  uses an analyst byline such as `-# Alrich Paskalis T, Investment Advisor`,
  has an empty line before content and its `View in Telegram` footer, and keeps
  field labels bold.
