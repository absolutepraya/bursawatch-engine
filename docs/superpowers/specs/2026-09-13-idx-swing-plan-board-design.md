# IDX Swing plan board design

**Date:** 2026-09-13

**Status:** User decisions incorporated, awaiting written-design review

**Owner:** Abhip / Yanto, Hermes agent on the VPS

## Goal

Keep `#id-stocks-swing` as the complete chronological All Swing feed, while
adding a read-only per-ticker board that lets members inspect one focused,
current cash-equity Swing thesis and its connected source history without
searching through unrelated alerts.

The board is informational. Neither a source update nor a price checkpoint
asserts that a member bought, holds, sold, took profit, or cut loss.

## Delivered Discord configuration

The forum already exists, is live, and is not a test surface:

| Item | Value |
| --- | --- |
| Forum | `#id-stocks-swing-board` (`1548273399069933720`) |
| Category | Invest & Trade (`1508875753473966150`) |
| Default layout | List View |
| Ordering | Latest activity |
| Inactivity archive | Three days |
| Member access | View-only: no posts, replies, or reactions |
| Bot access | Yanto can create, edit, reply, tag, and archive |

The pre-existing `#id-stocks-swing` (`1525102458253217803`) is unchanged.
The board receives only validated owner events and approved bootstrap data. It
must not receive test posts.

The configured forum tags are:

```text
Chart context, Supporting setup, Primary plan, Resolved,
Below entry, Entry zone, Above entry,
TP1 reached, TP2 reached, TP3 reached, TP4 reached, TP5 reached, TP6 reached,
Stop-loss breached
```

## Scope and non-goals

Included:

- Phintraco Daily cash-equity Swing plans as the board's authoritative Primary
  Plan source.
- Qualifying single-ticker cash-equity plans from existing social Swing
  sources as source-only context.
- Immediate Phintraco source-status updates and deterministic after-close
  Yahoo price reconciliation.
- A one-time, controlled reconstruction of unambiguous ongoing Phintraco
  plans from retained Telegram history.
- Source-faithful formatting changes to the All Swing Phintraco alerts.

Excluded:

- Phintraco SSF, which remains All-only and never opens, promotes, updates, or
  replies to a board post.
- News feeds, company-news forums, portfolio tracking, market orders, user
  trading advice, manual board conversation, or generated technical analysis.
- Historical price-checkpoint backfill, inferred plans, and artificial activity
  intended to keep a resolved post unarchived.

## Model and ownership

The board has three distinct concepts. They are deliberately not collapsed
into a single "status".

| Concept | Meaning | Authority | Timing |
| --- | --- | --- | --- |
| Primary Plan | The current full Phintraco Daily cash-equity setup: entry, stop loss, targets, chart, and source link | Phintraco | New complete setup, then later immediate updates |
| Source tier | The strongest non-primary context in the episode: `Supporting setup` for GTW or `Chart context` for X and other social/chart sources | The source adapter and board owner | Source arrival and replacement |
| Source Status | What the latest matching Phintraco source explicitly says, for example `Hold` or `Target 1 achieved` | Phintraco | Immediately on source arrival |
| Market Checkpoint | Latest factual closing-price position against the stored plan | Deterministic status owner using valid Yahoo session data | 16:30 WIB, with one 17:00 retry |

Only a complete Phintraco BUY setup can create or replace a Primary Plan.
Phintraco HOLD and REMINDER items update the matching plan's Source Status.
They do not overwrite plan levels, manufacture a new plan, or change an
episode title. A source-only event never changes the primary plan or its
market-state tag.

The board's deterministic status owner is the only process allowed to write
the board's SQLite database and mutate board Discord state. Existing watchers
retain their own cursor and source-state JSON. They submit idempotent source
events to the owner and never write the SQLite database directly.

```text
Phintraco Daily watcher ─┬─> All Swing source alert
                          └─> durable board-source event ─> board owner

qualifying social source ─┬─> All Swing source alert
                          └─> durable board-source event ─> board owner

SSF watcher ───────────────> All Swing source alert only

board owner ─> SQLite episode state ─> forum cards, replies, titles, tags
after-close status job ─────────────────────────────────────────┘
```

All Swing delivery remains independent and first-class. A board failure must
not cause an All Swing duplicate or suppress the source alert. A persisted
board event permits the owner to retry board work without reposting the All
alert.

## Forum episode lifecycle

One forum post is one ticker episode, not one news item and not one permanent
company record. Its forum topic title is always the ticker only, while its
managed starter message is the top card and carries the descriptive heading.

### New Phintraco plan

A complete eligible Phintraco BUY setup opens a Primary Plan episode unless an
open, nonterminal episode for that ticker is eligible for replacement. Its
forum title is `<TICKER>`, for example `DSSA`. The top card contains
the full source setup and original chart. The same source alert also appears
in All Swing.

A subsequent complete Phintraco BUY setup supersedes the currently active
Primary Plan only when the existing episode is not terminal and is within the
connected-material window. The owner replaces the bot-managed top card and
chart in that same forum post, while retaining existing normal source replies.

### Social source-only plan and promotion

A qualifying social item must be a cash-equity Swing plan with exactly one
clear ticker and a source-supported actionable thesis. It creates a
source-only post whose forum title is the ticker, while the starter message
retains the source's exact title, for example:

```text
KPIG: Wave IV diproyeksikan menuju area 97 sampai 108
```

The source event itself owns the Yanto-managed top card, including its accepted
summary and first chart. Additional source chunks and later media remain normal
thread replies.

If a complete Phintraco BUY setup for that ticker arrives within 20 IDX
exchange trading sessions, while that source-only episode remains open and
nonterminal, the owner promotes it in place:

1. edit the Yanto-owned top card to the full Phintraco plan and its original
   chart;
2. keep the forum title as `<TICKER>`;
3. replace the lifecycle tag with `Primary plan`; and
4. preserve the superseded social starter card and first chart once as a
   normal source-context history reply below the new Phintraco starter.

The source-context history is board-only and does not replay the All Swing feed. No
source message is rewritten, copied to quoted history, or deleted. If the
matching setup arrives after 20 exchange sessions, or after the old episode
resolved, it begins a fresh Phintraco episode and does not preserve stale social
context. It does not backfill unrelated or stale social context.

### Status and checkpoint updates

Phintraco source updates affect Source Status immediately. An update that
explicitly states a target was achieved or stop loss was hit may immediately
apply the corresponding factual price-state tag. A HOLD, reminder, or other
non-threshold source status does not invent a price-state tag and leaves the
last factual market state intact.

On every IDX trading day, the deterministic owner attempts one valid
after-close price checkpoint at 16:30 WIB. If the session's Yahoo data is
missing, stale, or not clearly for that Indonesian exchange session, it makes
exactly one retry at 17:00 WIB. A second unsuccessful attempt does not change
the stored state, does not add history, and renders `Market check unavailable`
on the top card. On a nontrading day there is no checkpoint attempt or forum
activity.

For a BUY plan, the classified state is computed from the latest valid closing
price and the plan's stated values:

| Condition, evaluated in order | Market state |
| --- | --- |
| At or below the stop-loss threshold | `Stop-loss breached` |
| At or above one or more targets | Highest reached `TP1` through `TP6` |
| Within the stated entry range | `Entry zone` |
| Between stop loss and the lower entry boundary | `Below entry` |
| Above the entry range but below the first unreached target | `Above entry` |

The terms are price facts, not action instructions. Before any reliable
checkpoint or explicit source-confirmed target or stop outcome, a Primary Plan
has only its lifecycle tag. It receives a market-state tag once a factual state
is known.

The card always preserves every source-supplied target, even when there are
more than six. Tags represent the highest reached target only through TP6.
For a plan with a seventh target or higher, the card can state that higher target
in text, while the tag remains `TP6 reached` as the highest available tag.

### Resolution and retention

A plan becomes terminal when a valid close or explicit Phintraco outcome
breaches its stop loss or reaches its final source-supplied target. The owner:

- preserves the final Primary Plan card and chart;
- changes lifecycle to `Resolved` while retaining the final factual market tag;
- updates the managed card and tags without emitting a quoted history reply; and
- stops all future source-status and price updates for that episode.

No artificial reply, card edit, or tag churn is used to keep it visible.
Discord automatically archives the inactive resolved post after three days.
It remains Discord history, and any later complete Phintraco plan for that
ticker opens a fresh episode.

## Discord rendering

### All Swing Phintraco source alert

All Swing remains the immutable chronological source feed. Every relevant
Phintraco Daily source alert renders in ticker-first form and includes the
source chart where the source provides one:

```md
### <:phintraco:1531272488645038091> DSSA: Hold
-# Alrich Paskalis T, Investment Advisor

**Type:** Trading Buy <:up:...>
**Entry:** Rp...
**Stop-loss:** Rp...
**Target 1:** Rp...
**Target 2:** Rp...
**Signal date:** 19 Sep 2026 09:05 WIB

**Reasons:** ...

[View in Telegram](<https://t.me/...>)
```

The heading contains no redundant bold markers. The analyst byline uses a
comma, not a period. There is one empty line after the byline and before the
footer. When the named analyst is absent, the renderer uses
`-# Phintraco Sekuritas` rather than inventing an analyst or job title.

### Board top card

The board top card uses the same source-faithful heading, byline, fields,
reason text, chart, and Telegram footer, then adds board-owned current state:

```md
**Source status:** Hold
**Market checkpoint:** TP1 reached
**Closing price:** Rp...
**Last checked:** 19 Sep 2026 16:30 WIB
```

`Market checkpoint`, `Closing price`, and `Last checked` are absent from a
source-only card. If no valid current session check is available, the card
shows `**Market checkpoint:** Market check unavailable` and preserves the last
successful closing price and check time, if any.

The top card is always Yanto-authored. This is required because Discord allows
a bot to edit its own message and manage its own uploaded attachment, but the
bot must not treat source messages from other authors as editable records.

### Normal source replies and managed board history

The complete Phintraco setup represented by the top card is not duplicated as
a reply. A source-only starter contains the accepted source summary and first
chart, while later source chunks and media are delivered as normal thread
replies that preserve their source content and link. When a stronger or newer
source replaces a source-only starter, the superseded starter card and first
chart are preserved once as one normal source-context history reply. Board-owned
lifecycle history is never rendered as a quoted reply.

The owner updates the managed card for material transitions such as:

- a new or replacement Primary Plan;
- a changed Phintraco Source Status;
- a changed factual Market Checkpoint; or
- resolution.

Source replies are split losslessly into ordered normal replies when needed to
stay within Discord's 2,000 UTF-16-unit limit. Every chunk has its own durable
outbox and Discord message identity.

An unchanged daily check updates the top card's displayed `Last checked` time
only. It creates no reply and therefore does not create artificial forum
activity.

## Tag policy

Each active post has exactly one lifecycle tag:

| Episode state | Tag |
| --- | --- |
| GTW source-only context | `Supporting setup` |
| X or other chart-only context | `Chart context` |
| Active Phintraco Primary Plan | `Primary plan` |
| Terminal plan | `Resolved` |

Once known, one additional factual market-state tag is applied. It is one of
`Below entry`, `Entry zone`, `Above entry`, `TP1 reached`, `TP2 reached`,
`TP3 reached`, `TP4 reached`, `TP5 reached`, `TP6 reached`, or `Stop-loss breached`. The
owner resolves configured tag IDs by their exact reviewed names and fails
closed if a required tag is missing or ambiguous. It never creates tags during
normal processing.

No tag is used for a subjective bullish, sideways, or bearish opinion.

## Durable state and idempotency

The board SQLite database is exclusively owned by the deterministic board
owner at:

```text
~/.hermes/state/idx-swing-board.sqlite3
```

It stores at least the following durable records:

| Record | Purpose |
| --- | --- |
| `source_events` | Immutable provider and source-message identity, normalized ticker, eligibility, event kind, and board-delivery state |
| `episodes` | Ticker, lifecycle, 20-session window, forum thread ID, title, top-card message ID, and tag state |
| `plans` | Complete Phintraco setup values, analyst, source link, attachment identity, source status, and terminal boundary |
| `checkpoints` | Session date, checked time, Yahoo source freshness, closing price, classified state, and failed-attempt result |
| `history_events` | Material transitions and their Discord reply identity |
| `bootstrap` | One-time run identity, source range, item decisions, and completion state |
| `outbox` | Intent to create or edit a Discord post, reply, attachment, title, or tag, with retry-safe completion identity |

Source identity is immutable and deduplicated before Discord work. The owner
records an outbound intention before a Discord API call and records the
returned message or thread identity before marking it complete. A process
restart retries only unfinished work and never requires reposting the All
alert.

Existing watcher JSON stays the source of truth for each watcher's Telegram
cursor and source delivery. No watcher reads or mutates another watcher's
state, and none writes this database.

## Intake boundaries

| Source material | All Swing | Board |
| --- | --- | --- |
| Complete Phintraco Daily cash-equity BUY setup | Yes | Primary Plan or eligible promotion |
| Matching Phintraco Daily HOLD or REMINDER | Yes | Update active matching Primary Plan immediately |
| Qualifying one-ticker cash-equity social plan | Yes | New or active source-only episode |
| Raw multi-ticker social post | Yes | No, unless the source contains separable, source-exact per-ticker plans |
| Ambiguous matching Phintraco status | Yes | No change, emit one deduplicated `#hermes` operational warning |
| Phintraco SSF | Yes | Never |

No source is squeezed into a board episode by ticker mention alone. If a
social post has multiple tickers or cannot establish an actionable plan for
exactly one ticker, it stays in All Swing without board routing.

## One-time bootstrap

Bootstrap has a 20 IDX trading-session lookback, is dry-run capable, and is
idempotent. It reads retained Telegram Phintraco history to reconstruct only
plans that are unambiguously still active:

1. locate the original complete BUY setup, including its original chart;
2. create the Primary Plan top card from that source material;
3. append only distinct matching later Phintraco source-status messages as
   normal replies; and
4. record no historical price checkpoints or inferred daily transitions.

If retained history contains a HOLD or target-status message but not the
original complete BUY setup, bootstrap may retain the raw source item with a
transparent `Historical setup unavailable` notice. It must not infer entry,
stop-loss, targets, analyst, chart, or a current Market Checkpoint. That ticker
waits for a later valid complete BUY setup before becoming a live Primary Plan.

Bootstrap is an externally visible backfill. It is not run merely because code
is deployed. It requires explicit approval after the dry-run report identifies
each candidate and its intended Discord effect.

## Implementation boundary

Implementation will use the main Hermes worktree and preserves the current
watchers' delivery responsibilities.

Expected changes are:

1. create one deterministic no-agent board owner and after-close status cron,
   with a `CRON.md`, per-run `#hermes` heartbeat, SQLite/outbox ownership,
   explicit Jakarta/IDX-session logic, and no-post dry-run mode;
2. extend `idx-swing-watch-phintraco-daily` to render the agreed ticker-first
   All Swing source format and durably submit eligible Phintraco events to the
   board owner after independent All delivery;
3. add narrowly scoped board-event adapters to only the existing qualified
   cash-equity social sources; and
4. leave `idx-ssf-watch-phintraco-weekly` board-unaware and All-only.

Registering or enabling the new cron, changing live delivery, and running the
bootstrap are separate production actions. They occur only during the approved
implementation and deployment step, not during design review.

## Verification requirements

Tests and live no-post checks must prove observable behavior:

1. Phintraco BUY, HOLD, REMINDER, target, and stop scenarios render the All
   format exactly, including optional analyst fallback and attachment handling.
2. Social source-only creation, in-window promotion, out-of-window new
   episode, terminal new episode, and multi-ticker exclusion are deterministic.
3. SQLite transactions, outbox retry, process restart, duplicate source event,
   Discord failure, and All-success plus board-failure preserve exactly-once
   board intent without duplicating All Swing.
4. A valid same-day Yahoo close produces each threshold state, including target
   ladders beyond TP6. Missing, stale, holiday, and retry-failure data preserve
   prior state and produce no false transition.
5. Material transitions edit the managed card and tags without quoted history.
   Unchanged checks only edit the top card.
6. Tag resolution, lifecycle replacement, terminal resolution, and 3-day
   auto-archive behavior use only the reviewed forum configuration.
7. Bootstrap dry-run identifies every candidate, skipped ambiguous item, and
   planned external effect without making a Discord or Telegram write.
8. Focused suites, the cron suite, and `bash scripts/test-all` pass before any
   deploy. A no-post VPS verification exercises the real renderer and board
   outbox path without creating a forum post or message.

## Open implementation choices, deliberately bounded

- The implementation plan selects the cron and wrapper names, but the new
  deterministic owner remains separate from the minutely Phintraco watcher.
- The price adapter may use Yahoo only when it can prove the returned value is
  the current IDX session's closing data. It must otherwise take the documented
  unavailable path; it may not substitute a prior close silently.
- Exact Discord REST wrapper functions may vary with the existing Hermes
  utility layout, but all post, message, attachment, title, and tag mutations
  must pass through the owner outbox.
