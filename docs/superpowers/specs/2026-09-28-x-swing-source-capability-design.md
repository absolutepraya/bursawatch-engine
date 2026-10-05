# X Swing source capability and shared Board integration

**Date:** 2026-09-28

**Status:** Approved by user 2026-09-28. The follow-on implementation plan is
complete and the X source adapter wrapper is active through the existing
production X schedule as of the 2026-09-30 snapshot. That snapshot confirms
scheduler entries, not installed runtime checksums or effective capability
settings. See the current [Control Plane contract](../../../service-bursawatch-control/README.md#x-swing-capability-and-state-transition-boundary)
for operating boundaries.

**Owner:** Bursawatch platform and Swing Board owners

## Goal

Add X Swing Chart Context as an explicit capability in the Source Catalog and
platform-pipeline architecture while preserving the current X classification,
thread/media handling, All Swing delivery, and Swing Board rules. Route X
context through the same Swing Board owner that receives Phintraco and other
source events. Do not create a second Board implementation or a universal
cross-platform classifier.

This document supplements the [Source Catalog and platform-pipeline
architecture](2026-09-24-bursawatch-source-catalog-and-pipeline-architecture-design.md),
the [X Swing handoff decision](../../adr/0021-x-swing-board-handoff-and-media-queue.md),
and the [shared Swing Board design](2026-09-23-swing-board-shared-architecture-design.md).
Those documents remain authoritative for their existing domain contracts.

## Current gap

The new X source-ingest package accepts `company_news` and `macro_news` work and
hands it to the existing X watcher owner. The existing X watcher still owns
the classifier, ordered X thread and media handling, All Swing output, and
source-only Board handoff. The platform pilot is not scheduled.

The shared Source Catalog already defines `swing_chart_context` for the BRI
source, but X is not yet compatible with that capability. The new X source
configuration therefore cannot explicitly select the existing Swing behavior.
The capability addition must bridge to the existing X domain behavior without
changing current output or bypassing the shared Board owner.

## Source configuration and classification

- Mark `swing_chart_context` as compatible with verified X account endpoints.
- Store the effective capability set and its revision in the Control Plane.
  The X adapter reads one versioned configuration snapshot per run. Publisher
  defaults and endpoint overrides follow the existing Source Catalog rules.
- Keep classification X-specific. Do not move X relevance, route precedence,
  or thread interpretation into a shared universal router.
- For each X publication, assemble its accepted source thread once and run the
  existing X classifier once. The classifier selects exactly one eligible
  route from that account's effective capabilities. It must not create one
  competing work item per matching X category.
- Represent this as an X-specific mutually exclusive route group in the
  capability compatibility and dispatch contract. Other sources may use the
  general independent-subscription fan-out where their contracts allow it.
- Preserve the existing classifier outcomes and precedence, including the
  rule that an IHSG or broad macro thesis takes precedence over Swing, and
  that a direct IDX technical or swing-trading thesis can select `id_stocks_swing`.
  This change does not revise relevance rules, prompts, titles, or summaries.
- When the selected route is `id_stocks_swing`, dispatch one durable
  `swing_chart_context` work item. Existing non-Swing X routes keep their
  current destinations and behavior.

The route model is:

~~~mermaid
flowchart LR
  Config[Effective X endpoint capabilities] --> Adapter[X platform adapter]
  Adapter --> Inbox[Durable source event and ordered thread snapshot]
  Inbox --> Classifier[X-specific classifier, one route per publication]
  Classifier -->|Swing chart context| Swing[X Swing workflow]
  Classifier -->|Other existing route| Existing[Existing X route workflow]
  Swing --> Gate{Strict single-ticker Board gate}
  Gate -->|Eligible| All[All Swing message with temporary Board marker]
  Gate -->|Ineligible| AllOnly[All-only message]
  All -->|Text and usable media durably delivered| Board[Shared Swing Board owner]
  Board -->|Accepted topic receipt| Link[Edit original All message with direct topic link]
  Telegram[Phintraco and Kelas source pipelines] --> Board
~~~

## X Swing delivery

For a publication classified as `id_stocks_swing`:

1. Preserve the current X self-chain assembly and settle behavior. Include all
   accepted authored thread text and images in source order. Feed every
   successfully acquired thread image to the LLM under the existing bounded
   X vision contract. A root-only fallback must not silently omit available
   continuation content.
2. Evaluate the existing strict Board handoff gate against the complete
   assembled thread and accepted title. The first source-visible
   line must be ticker-led, the accepted title must start with the same ticker,
   and the thread must contain no second ticker-led clause. A failed gate is
   rendered and delivered All-only, without a temporary Board marker, and must
   not create a Board episode.
3. Deliver the accepted X Swing message to chronological `#id-stocks-swing`
   first. An eligible message gets the temporary Board marker; an ineligible
   one does not. Deliver its text and usable media promptly in source order,
   without waiting for another platform polling or scheduled media-drain run.
   Track each delivery leg durably. A transient delivery failure follows the
   existing retry policy; a terminal media skip is recorded and excluded from
   the Board media set. A retry of the Board handoff must not replay successful
   All delivery legs.
4. Only after All text and usable media legs have durable success or an
   explicit terminal-skip outcome, submit one source-only event to the Swing
   Board owner. Preserve immutable X source identity, published time, accepted
   summary, attribution, ordered content, and stable media references.
5. The event is level 3 `Chart context` 🥉 with `plan: null`. Raw target or
   stop-loss phrases remain source context. X cannot create or change a
   structured plan, price state, target milestone, stop-loss state, lifecycle,
   tier policy, ticker route, or Discord forum topic.
6. The Board copy uses the same accepted rendered summary and durable Yanto
   delivery time as All, with the existing normalized `TICKER: ...` starter
   heading. The first chart is on the starter; later charts appear as ordered
   attachment replies. The Board copy omits the Board link line.
7. Once the Board owner returns its materialized topic, edit the same All
   message to replace its temporary marker with the direct topic URL. Retry
   only this edit if it fails.

The current X pilot's one-image Board path is insufficient for a multi-image
thread. Before X cutover, the handler must deliver every supported, accepted
thread image in order within the existing source-media and Discord delivery
bounds. The LLM's thread-image context and Discord media delivery both derive
from the same accepted thread snapshot. Unsupported or unavailable media must
follow the existing explicit blocked or terminal-skip contract; it must not
silently reorder images or block unrelated X events indefinitely.

## Shared Swing Board behavior with Phintraco

X submits source events to the existing Board owner. It does not search Discord
for a ticker title, select a forum, create topics directly, or maintain local
episode state. The owner uses the same durable ticker-to-forum route and open
episode state for X, Phintraco, Kelas Investasi, BRI Danareksa, and every other
configured source.

- There is one configured forum per ticker and at most one open episode for a
  ticker at a time. A Discord thread is one episode. A later episode gets a
  new thread in the same configured forum; resolved threads remain history.
  Titles retain the generated `TICKER - weekday, DD Mon YYYY` form, using the
  first accepted source timestamp converted to WIB. The weekday may be a
  weekend day.
- While a Primary Phintraco episode is open, eligible X Swing context is added
  to that episode as a normal attributed source reply. It does not replace the
  Phintraco plan, tier, price state, milestone, tags, or timers.
- While a level 2 or level 3 source-only episode is open, eligible X context
  joins that episode. If there is no open episode, the Board owner may start a
  source-only level 3 episode using the source-published-time and routing rules
  already defined by the shared Board design.
- When the first Phintraco BUY promotes an open source-only episode, promotion
  stays in the same thread and preserves its source history. The owner
  republishes the strongest prior level 2/3 starter as one normal attributed
  reply with its first chart or media; remaining source chunks stay in their
  ordered replies. The X handler does not back-search Discord or resend it.
- A distinct newer Phintraco BUY received during an open Primary episode
  supersedes that episode and creates a new episode thread. A late Phintraco
  BUY cannot rewind a newer active plan. These identity and timestamp rules
  remain owned by the Board, not X.
- A level 2/3 event published before an episode's resolution but delivered
  later is attached as dated history without reopening it. A qualifying event
  published after resolution follows the shared rule for a new source-only
  episode. The existing stale-event quarantine rules still apply.
- Phintraco remains level 1 `Primary plan` 🥇, Kelas Investasi remains level 2
  `Supporting setup` 🥈, and X, BRI Danareksa, and all other sources remain
  level 3 `Chart context` 🥉 unless a separately approved exception changes
  the catalog.

Board rendering, episode titles, source replies, lifecycle and close rules,
status tags, route assignment, archive timing, audit, suppression, and
management operations continue to follow the shared Swing Board design. The
existing source-message layout and shared Swing formatting remain in use; X
does not create a special card or free-form operator note. The X pipeline may
request an owner operation but cannot independently implement or override
those behaviors.

## Durable work, retries, and ownership

- The platform adapter durably accepts the normalized source event and media
  references before advancing its X cursor.
- The effective endpoint configuration revision and selected X route are
  frozen on the work item. Retries use that snapshot and stable idempotency
  keys; configuration changes apply only to new events.
- All-channel message delivery, Board event acceptance, Board thread creation,
  and All-message link editing are separate recorded effects. Retry
  only the incomplete effect. A repeated source event or handoff cannot create
  duplicate Board replies or duplicate All messages.
- X corrections preserve the immutable original source event and append an
  audited corrected version. Explicit message deletion records the owner
  tombstone so retries cannot recreate suppressed output.
- The Board owner remains the only writer of Board state. The Discord
  Delivery Owner remains the only Bursawatch Discord API path. The Source
  Media Owner remains the only Supabase Storage path. The Control Plane stores
  source and media metadata, not media bytes.
- Source work for X can fail or retry independently from Telegram work and
  from other subscriptions. An X failure cannot mutate or block a Phintraco
  plan; a Board owner outage retains the durable X work for retry.

## Migration and cutover

- Preserve the currently configured X endpoints and their existing enabled
  output behavior, including Swing routing for accounts where the current
  classifier routes qualifying posts to `id_stocks_swing`.
- Reconcile this mapping from reviewed current endpoint configuration and
  publisher bindings. Do not infer profile identity from a handle or silently
  enable newly added endpoints or capabilities.
- Keep new endpoints and capabilities disabled until explicitly configured.
  Their first activation is future-only; no historical replay is implied.
- Do not run the new X reader beside the existing X polling owner. The legacy
  watcher retains source ownership until one reviewed cutover proves endpoint,
  cursor, thread, media, outbox, Board, and Delivery Owner parity. The adapter
  remains unscheduled until that cutover is separately approved.
- Do not reset cursors, discard queued or ambiguous delivery, replay source
  history, or create duplicate Discord messages during migration. Pending
  work remains durable and is reconciled under stable event and operation IDs.

## Acceptance criteria for the implementation plan

1. The effective Source Catalog shows `swing_chart_context` as supported for
   verified X endpoints, with an explicit enabled state and configuration
   revision.
2. One X publication and thread are classified once. A post matching a
   mutually exclusive X route group creates only its selected route work;
   it cannot be duplicated by enabling multiple X capabilities.
3. Existing X route priority and outcomes are unchanged. IHSG/broad macro,
   company-news, Swing, and US-stock cases retain the existing classifier
   behavior.
4. A Swing event reaches All first. A strict-gate rejection is All-only. A
   successful eligible event reaches the shared Board owner once, and the
   original All message is patched with its topic URL without replaying All.
5. Every supported image from an assembled X thread is supplied to the LLM
   and delivered in accepted order within documented bounds. A failed image
   cannot indefinitely block unrelated queued X events.
6. X content joins the existing ticker episode when one is open, including a
   Phintraco Primary episode. X cannot change the plan, price state, tags,
   lifecycle, forum assignment, or archive timing.
7. Phintraco promotion, distinct BUY supersession, late-source history,
   source-only episode creation, and one-open-episode enforcement use the same
   Board rules for events from every platform.
8. During migration the previously enabled X output behavior is preserved;
   new endpoints remain off; no parallel X reader, cursor reset, implicit
   replay, or duplicate output occurs.
9. Tests use fake platform, media, Board, and Discord Delivery clients. No
   test sends production Discord messages or mutates live schedules.

## Non-goals

- A universal cross-platform content classifier or a shared X/Telegram routing
  policy.
- Changing X relevance, LLM prompts, route precedence, summary language,
  existing destinations, or chronological All Swing presentation.
- Changing Phintraco plan semantics, the Swing Board lifecycle, forum mapping,
  status language, or tier assignments.
- Direct X, Board, browser, or Control Plane access to Discord credentials.
- Scheduling the X adapter, switching production readers, migrating live
  state, replaying posts, changing cadence, or deploying any package.

## Implementation-plan decisions

The separate implementation plan must define the capability and exclusive
route-group schema, handler contract, multi-image Board operation shape,
focused tests, exact current X configuration and state reconciliation,
release sequence, and production cutover evidence. The plan must not broaden
scope to WhatsApp, RSS/Stockbit, or Instagram. Their rollout order remains
WhatsApp, then RSS/Stockbit, with Instagram deferred until its source is
available.
