# Swing Board shared architecture design

**Date:** 2026-09-23

**Status:** User decisions incorporated, awaiting written-design review

**Owner:** Abhip / Yanto, Hermes agent on the VPS

## Goal

Unify Bursawatch Discord transport, Swing rendering, and Swing Board ownership
so every producer uses stable shared contracts. Keep source ingestion and
source cursors with each watcher, Discord delivery retries and receipts with
one shared Discord Delivery Owner, and Swing forum routing, episode state,
message projection, and lifecycle with one Board owner. Make current and
historical episodes accurate, attributable, retry-safe, and manageable without
manual Discord edits.

This document is the architecture contract for three separately planned
subprojects. A shared Discord Delivery Owner and transport is first,
Board-owner management and multi-forum routing is second, and shared Swing
rendering/client adoption is third. Each subproject requires its own
implementation plan and approval before implementation. This approval gate
applies to the design only.

## Verified current architecture

- `lib-swing-format` is a shared cash-Swing renderer used by the Phintraco and
  Kelas Investasi watchers and the Swing Board. It owns presentation grammar,
  not Discord HTTP delivery.
- There is no shared Bursawatch Discord delivery owner/transport today.
  `cron-tg-market-news/bin/delivery.py`, the Phintraco watcher, the Board
  owner's `discord_forum.py`, and other Discord clients contain their own
  HTTP/auth, retry, upload, or durable delivery code.
- `cron-dc-swing-board` is the sole writer of its SQLite episode database,
  private media, and Swing forum state. Other watchers submit durable source
  events through its wrapper; they do not write its database or directly
  mutate its forum.
- The existing Board forum is `#id-stocks-swing-board`
  (`1548273399069933720`). Its current implementation is single-forum and
  episode topics are ticker-only. Existing accepted records remain the
  migration baseline, while this design intentionally changes future behavior
  where specified below.

## Terms and boundaries

| Term | Meaning |
| --- | --- |
| Board | One Discord forum channel. |
| Episode | One ticker thread/post inside a Board, representing one setup history. |
| Source event | Immutable, validated source material submitted by its owning watcher. |
| Board owner | The deterministic service that persists events, routes them, owns episode state, and projects it to Discord. |
| Discord Delivery Owner | The single shared service that accepts outbound operations, durably owns Discord delivery state, performs Discord API mutations, and records receipts. |
| Shared transport | The low-level Discord API client used only by the Discord Delivery Owner. |
| Swing renderer | Shared provider-neutral presentation library for normalized cash-Swing content. |

The Discord Delivery Owner owns Discord-facing operation identity, durable
delivery queues, ordering, retries, ambiguous-result reconciliation,
Discord message/thread/channel IDs, and delivery receipts for every Bursawatch
Discord destination. It accepts explicit intents and does not choose source
content, ticker routes, episode identity, Board tags, or lifecycle decisions.
The Board owner owns canonical Swing Board state and decides which Board
operations are needed; it submits them to the Delivery Owner and applies the
resulting receipts to its state. Watchers own source cursors and source
validation; they submit rendered outbound intents and retain their source
handoff state until the Delivery Owner durably accepts each intent. Once
accepted, retry and Discord receipt ownership belongs to the Delivery Owner.
Shared rendering does not send messages.

## Subproject architecture and order

### 1. Shared Discord Delivery Owner and transport

Create one shared delivery service plus its reusable Python client/transport
for every Bursawatch Discord destination, including ordinary channel messages,
message edits/deletes, text plus media, forum/thread create/read/update/archive
operations, and required health heartbeats. All Discord API access used by
Bursawatch clients, including reads needed to verify or reconcile delivery,
must pass through the Delivery Owner. It centralizes durable operation
identity, idempotent acceptance, ordered queues, retry scheduling, remote
message/thread/channel IDs, receipts, and ambiguous-operation reconciliation.
Its low-level transport centralizes API version/base URL, authentication
injection, request timeouts, response/error normalization, rate-limit parsing,
and multipart handling. Clients supply stable idempotency keys, explicit
operation data, ordering keys, and domain context; they do not implement
Discord API retries or write their own Discord delivery receipts.

The submission API must distinguish rejected input from durably accepted work.
An accepted intent returns an operation ID immediately; operation status and
its receipt include resulting message/thread/channel IDs and whether work is
pending, delivered, retrying, definitely rejected, or unresolved/ambiguous.
Credentials remain runtime configuration and are never logged. The Delivery
Owner may retry safe read-only calls and definite rate limits; it must not
blindly repeat an ambiguous create. It persists the exact operation snapshot
and bounded read-back boundary before a create, then reconciles by reading
Discord after timeout or interruption. An inconclusive result stays pending
and alerts instead of creating again.

The Market News sender is currently local to its cron, not a shared sender.
Move its sends, edits, uploads, delivery records, sequencing, and Discord
retry/recovery to the Delivery Owner while leaving classification, canonical
news rendering, and the source watcher cursor in the news package. Apply the
same ownership boundary to every other Bursawatch Discord client, including
Swing All destinations and Board operations. The Board owner supplies stable
operation keys and canonical desired changes; the Delivery Owner owns the
forum-create snapshot and bounded read-back recovery. Stable Discord nonces
remain a short-window aid, not durable idempotency. A producer may keep a
durable handoff queue so accepted source work is not lost before the service
acknowledges it, but that queue is not a second Discord delivery authority.

The host-bound release agent's `#hermes` heartbeat is included in the
destination scope, but its code, token file, service, and privilege boundary
remain subject to the separate release-agent bootstrap contract. It may submit
only its existing heartbeat operation through the Delivery Owner; this design
does not widen its release or host authority.

### 2. Board owner and management API/CLI

The Board owner remains the single writer for its database, Board media,
canonical Board operation intents, and episode projections. It durably records
the desired operation and stable operation key with its Board state, then
submits that intent to the Delivery Owner. The Delivery Owner is the only
process that performs Discord API operations. Expose a shared Board management
interface, with a versioned API and/or CLI, that calls the Board owner rather
than letting clients or operators write storage or Discord directly. The
interface must support read-only inspection and explicit, validated
management operations for forums, ticker routes, episodes, and source-backed
messages.

### 3. Shared Swing rendering and client adoption

Keep `lib-swing-format` focused on normalized source presentation and make its
shared cash-Swing contracts reusable by all approved sources. The Board owner
uses Board-specific projections for the managed episode card, generated
lifecycle/status content, and normal source-history replies. Formatting,
transport, and Board ownership remain separate modules. Phintraco, Kelas,
other qualifying sources, and Board rendering consume the shared contracts
without implementing their own Board mutation behavior.

## Source tiers and Board content

Default tiers are fixed as follows unless a separately approved source
exception changes the catalog:

| Source | Tier | Board label |
| --- | --- | --- |
| Phintraco | 1 | `Primary plan` 🥇 |
| Kelas Investasi | 2 | `Supporting setup` 🥈 |
| Every other source, explicitly including BRI Danareksa | 3 | `Chart context` 🥉 |

This supersedes older wording in ADR 0022 that described BRI Danareksa as a
possible level-1 source. The existing `Resolved` lifecycle tag continues to
use the current `check_big` emoji. `Resolved` replaces the episode's source
tier tag; the episode card/history identifies its sources.

Board content is source-derived or generated by the deterministic owner. There
are no free-form operator notes or arbitrary operator-created messages.
Messages may be created only from validated immutable source events or
generated lifecycle/status transitions. Source events and correction history
remain locally attributable.

## Forum registry and routing

The Board owner's database is authoritative for the durable forum registry and
ticker-to-forum assignment. Manage both only through the owner management
interface. A registered forum can host many tickers. A ticker can have only
one configured forum at a time. An open episode retains its selected forum ID
until it closes; changing the ticker route affects only the next episode.
Persist Discord forum/channel IDs on route changes, episodes, source routing
records, outbox operations, and create-recovery snapshots. Never select a
forum by searching for a ticker title, because historical episodes repeat
titles.

Every source tier for a ticker routes to that ticker's configured forum. No
fan-out is implicit. If no route exists, the owner durably accepts the event
as unrouted/pending, reports degraded health through the owning cron's normal
health path, and does not guess a forum, search Discord, or silently drop the
event. When an operator later configures the route, the owner automatically
drains eligible immutable events once, ordered by source-published timestamp
and a stable tie-breaker. If the newly routed event is already more than 20
IDX trading sessions old, quarantine it as expired, report it, and retain it
for audit and deduplication rather than creating a misleading current episode.

If a registered forum is renamed outside the manager, deleted, or missing
required permissions, pause delivery and alert. Preserve events until the
destination is repaired or an explicit route change occurs. Never silently
recreate a forum or choose another destination.

## Episode identity, history, and ordering

Each Discord forum post/thread is one ticker episode. A ticker can have at
most one open episode globally. A ticker may have multiple historical episodes
in its configured forum, but cannot have concurrent open episodes or be routed
to concurrent forums. When an episode closes, retain its thread as history and
create a new thread for a later qualifying setup.

Generated episode titles use `TICKER - weekday, DD Mon YYYY`, for example:

```text
CPIN - Wed, 23 Sep 2026
```

Use the first accepted source event's published timestamp converted to WIB.
The weekday reflects the actual calendar date and may be Saturday or Sunday.
The title is fixed after creation and does not use cron processing or retry
time. Forum channel names remain editable via management. A title repair may
only regenerate the canonical ticker and opening timestamp; a source event
cannot silently change episode identity.

### Primary and source-only episodes

- A qualifying Phintraco BUY creates a primary episode when no episode is
  open, unless it promotes an already-open source-only episode.
- A qualifying level-2/3 source event with no open episode creates a
  source-only episode whose lifecycle label is its strongest accepted source
  tier. Multiple lower-tier source events can contribute source replies to
  that episode; they never set structured plan levels, price state, or target
  milestones.
- If a Phintraco BUY first arrives during an open source-only episode, promote
  that same episode/thread, preserve its source context, and render the
  strongest level-2/3 starter as one attributed normal reply with its first
  chart/media. Use persisted source data and a stable deduplication key; do not
  search Discord or resend the All Swing event. Existing remaining chunks
  remain in their ordered replies.
- A distinct Phintraco BUY source event newer than the active primary BUY
  supersedes the active episode, marks its reason `superseded`, resolves it,
  and creates a new episode/thread. This remains true when plan levels match.
  A retry or redelivery with the same event identity is deduplicated.
- A late Phintraco BUY published before the active primary BUY cannot rewind
  the plan or timers. Publish a generated, dated `Historical source event`
  reply in the current thread. It does not change the card's current plan,
  tags, or timers.
- A level-2/3 event published before an episode's resolution time but delivered
  after resolution is attached to that resolved episode as a dated historical
  reply. It neither reopens the episode nor creates a new one. A level-2/3
  event published after resolution starts a new source-only episode. A
  Phintraco status event without a new BUY never starts a primary episode.
- Lower-tier context received while a primary episode is open is delivered as
  a normal attributed source reply and does not replace the Primary plan,
  alter market status, or reset the primary inactivity timer.

Source-published time determines late-versus-new event ordering. Stable source
event identities deduplicate retries. Each accepted source event remains
immutable; it is not rewritten when the displayed interpretation is corrected.

## Plan status, market state, and resolution

Only complete Phintraco level-1 primary plans receive automated after-close
price/status updates. Kelas Investasi and other lower tiers remain source
context, even when their text includes buy areas, targets, or stops. The Kelas
Board adapter continues to submit no structured plan. No intraday price
polling is introduced. Daily session-close data and explicit Phintraco status
confirmations remain authoritative.

Retain the current tag catalog names exactly:

```text
Below entry
Entry zone
Above entry
TP1 reached ... TP6 reached
Stop-loss breached
```

Do not rename the live `Stop-loss breached` tag without a deliberate catalog
migration. Plain card wording may explain that the stop loss was reached.

Track two separate facts:

1. **Current close position:** the latest valid close classified against the
   plan as `Below entry`, `Entry zone`, `Above entry`, or `Stop-loss breached`.
2. **Furthest target milestone:** the highest target ever confirmed by a valid
   daily close at or above the target, or an explicit Phintraco confirmation.
   It is monotonic and never regresses. Lower-tier sources cannot assert it.

Discord tags show the current close position or terminal resolution state. A
close at or above a target uses the highest reached target tag for that close.
The existing episode card layout shows both the current position and furthest
milestone, retaining earlier TP facts after price retreats. For example, after
TP1 confirmation followed by a close below entry, the tag is `Below entry`
and the card still shows TP1 reached. At or below stop, or an explicit
Phintraco stop confirmation, resolve the episode with `Stop-loss breached`
while retaining prior target milestones in the card/history. The final target
resolves the episode as all targets reached while retaining the highest
available target tag, clamped at TP6 when the plan has more targets.

Close classification is ordered: at/below stop means stop-loss breached;
inside the entry range means entry zone; below entry but above stop means
below entry; above entry and below the first target means above entry; at or
above one or more targets advances the highest confirmed target milestone.
Terminal stop/final-target facts resolve the episode. Source confirmation can
update a mapped stop/target milestone during the day, but a later valid close
updates current close position independently.

The close schedule remains 16:30 WIB with one eligible 17:00 WIB retry on IDX
trading sessions and uses the reviewed exchange calendar. Source status
confirmation is handled when the event arrives. No price poll is added.

The 20-session rule is an inactivity timer for both primary and source-only
episodes. A primary timer resets only for a newer Phintraco BUY or material
Phintraco status/progress confirmation. Level-2/3 context does not extend it.
A source-only timer resets for a qualifying new source event. The owner job
must resolve an episode automatically at 20 IDX trading sessions of
inactivity, even when no new source message arrives. Resolution reasons use
the existing `Resolved` lifecycle tag and are stated in the card/history as
`stale`, `superseded`, `stop loss`, or `all targets`.

For stale or superseded closure, remove the market-state tag and show
`last checked: <date> · <state>` in the existing card layout. For stop loss or
all-target closure, retain the terminal market tag. `Resolved` replaces the
source-tier tag; do not add reason-specific tags.

After resolution card/tag changes are delivered and every already-queued
episode message is successfully delivered or explicitly tombstoned, begin a
48-hour quiet period. Archive the Discord thread after 48 hours without
further activity. A later episode is a different thread and does not delay
this archive. Late historical replies count as activity and restart the quiet
period.

## Managed messages, correction, and deletion

The manager can inspect canonical state and manage forum channels, ticker
routes, episodes, and source-backed messages. Supported operations include
read canonical state and the registered tag catalog; create/register, rename,
and edit a forum's name, topic, or tag catalog through validated catalog
migrations; assign, change, or remove ticker routes; create generated
episodes only from validated source events; correct canonical source
interpretation; rerender managed messages; close or archive episodes; retire
or permanently delete a forum; and permanently delete a closed episode or
message subject to preview/apply safeguards.

There is no arbitrary free-text message creation or Discord-side canonical
editing. Corrections append a version to the verified source view while
preserving the original immutable source event. Rerender from that corrected
view. Each correction audit record includes actor/service identity, timestamp,
affected event/message, before and after values, and a required reason. Audit
metadata stays internal and does not appear as an operator note on the Board.

Explicit message deletion writes a durable tombstone and audit record before
or atomically with Discord deletion, so retries cannot recreate the message.
Repair/regeneration is derived from corrected canonical state, not a
free-form patch to Discord.

### Forum retirement and permanent deletion

Retiring a forum makes it read-only history and removes it from new routing.
Retirement is blocked until all episodes routed to it are closed and all
outbox work is delivered or explicitly tombstoned. Existing history remains.

Permanent forum deletion is a distinct preview-and-apply operation. It is
blocked while any ticker routes to it, any routed episode is open, or any
outbox work remains pending. First retire the forum, close active episodes,
and drain or tombstone pending work. Preview must enumerate routes,
episode/history counts, and affected messages; a separate explicit apply may
then delete the forum and its posts.

Permanent deletion of an individual episode is blocked while the episode is
open. After it is resolved, deletion requires preview and explicit apply.
Retain a local tombstone and audit record so retries cannot recreate the
thread or its messages.

## Owner failures and durable operations

The Board owner must persist every accepted source event and its resulting
canonical state before acknowledging it. It stores desired Board operations
and stable operation keys in its local intent outbox, then submits each intent
to the Delivery Owner. The Delivery Owner durably accepts each key once and
owns the authoritative Discord operation record, queue, retry state, create
snapshot, and delivery receipt. If the Board owner restarts before learning
whether submission was accepted, it resubmits the same key; the Delivery Owner
returns the existing operation instead of creating another. The Board owner
applies receipts to its canonical operation status and continues ordered
episode projection.

The Delivery Owner persists the exact create snapshot and bounded read-back
boundary before issuing a Discord create. Definite rejection may clear a
create snapshot; timeout or interruption requires read-back recovery. If
reconciliation is ambiguous, keep the operation pending and alert instead of
issuing another create. Per-destination and per-episode ordering prevent
conflicting writes. Delivery-owner tombstones, suppression state, and
accepted-operation deduplication survive process restart. Source-event
deduplication remains with the source and Board owners. The shared transport
provides normalized API outcomes; it does not decide whether to recreate,
suppress, supersede, or expire Board work. The Delivery Owner decides only
safe Discord operation retry and reconciliation mechanics. Outbox and watcher
errors use existing cron health/heartbeat paths. Do not emit test messages to
live destinations.

## Initial migration

Register the current live forum as the first managed Board. Link existing
episodes, thread IDs, starter-message IDs, routes, source events, and delivery
records using stored IDs. Preserve existing history and current ownership.
The migration must not search by repeated ticker title, replay source events,
or create duplicate forum posts. Events that have no explicit valid route
after migration remain pending under the unrouted-event rule. Migration must
be restart-safe, auditable, and have a reviewed rollback snapshot before any
production state migration is proposed.

This design authorizes documentation only. Production state migration,
schedule changes, destination changes, deployments, replay, and posting remain
separate approval gates.

## Acceptance invariants

The later implementation is acceptable only when all of these can be proven:

1. Every Bursawatch Discord mutation passes through the shared Discord
   Delivery Owner; there is one durable delivery authority for operation
   identity, retries, reconciliation, and Discord receipts.
2. Source clients keep source cursors/validation, and the Board owner keeps
   canonical episode state and desired Board operations. Their handoff queues
   cannot become competing Discord delivery authorities.
3. `lib-swing-format` remains a renderer, not a sender; the Board projection
   is deterministic and renders from canonical persisted data.
4. A ticker has no more than one route and one open episode globally. Every
   episode remains pinned to the forum ID selected at its creation.
5. No route is guessed, no event is silently dropped, and eligible pending
   events drain once in deterministic source-published order after routing is
   configured.
6. A retry, restart, ambiguous Discord response, duplicate source event, or
   explicit tombstone cannot create a duplicate post/message or resurrect
   deleted content.
7. Episode title, tier, card, replies, current close state, furthest target,
   lifecycle reason, and archive timing follow the rules above without
   rewriting immutable source events.
8. Historical late events and stale BUYs never rewind/reopen current plans;
   promoted source context remains visible exactly once.
9. Retirement/deletion gates are enforced by the management interface and
   retain auditable local tombstones.
10. Initial migration preserves current IDs and history without source replay
   or duplicate Discord creation.
11. Operations report pending, expired, quarantined, or failed work through
    the relevant owning cron's health path.

## Non-goals

- Changing the chronological All Swing channel into a Board or making All
  delivery depend on successful Board delivery.
- Multiple open episodes for one ticker, fan-out routing, or title-based
  routing.
- Manual trading annotations, free-form operator notes, arbitrary message
  creation, or human edits to canonical Discord content.
- Intraday price polling or lower-tier sources asserting structured price
  milestones.
- Automatically recreating an externally removed/renamed forum or guessing a
  replacement destination.
- Production migration, Discord posts for testing, scheduler changes,
  release, or deployment as part of spec approval.

## Open implementation details

These details are intentionally delegated to each subproject's reviewed
implementation plan and may not weaken the invariants above:

- the shared delivery service/package names, public Python API, and supported
  Python runtime compatibility;
- the durable transport between producers and the Delivery Owner, including
  acknowledgement/receipt polling or callback shape;
- exact Board management API/CLI command names and authorization boundary;
- database schema/migration strategy for registries, routes, correction
  versions, tombstones, expiration quarantine, and multi-forum history;
- exact owner job/scheduler integration for automatic inactivity resolution
  and 48-hour archive checks;
- exact correction field schemas and permission model;
- bounded queue sizes, delivery timeouts, and operational thresholds.
