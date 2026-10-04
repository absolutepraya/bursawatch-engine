# Phintas Swing Route Canonicalization

**Date:** 2026-10-01
**Status:** Implemented through PR #35 and released. The catalog and owner
configuration transition is complete; no new post-boundary source-to-delivery
event has yet been observed.

## Goal

Route future Phintraco swing plans and status replies through the canonical
`@phintasprofits` Telegram endpoint, while keeping source reply IDs, the
existing Swing owner ledger, and the Board handoff intact. The cutover must
preserve the already advanced Phintas cursor so it cannot replay old messages.

## Evidence and corrected diagnosis

- Telegram resolves `@phintasprofits` to channel `1444713822`, titled
  `Phintraco Sekuritas Official`. Resolving the old `@phintraprofits` handle
  returned an error, although its catalog endpoint carries the same numeric
  channel ID and the legacy reader could access it by provider ID.
- At Source Catalog revision 7, `telegram:phintasprofits` has the three News
  capabilities. `trading_plans` is enabled on `telegram:phintraprofits`.
  Separate cursor files existed for both endpoint names and were both at
  message `35556` during the read on 2026-10-01.
- Source message `35530` is an INDF first-target reminder. It replies to
  companion post `35447` for the September 28 weekly swing report. Its event
  was accepted under `telegram:phintraprofits`, and its `swing_plan` work and
  Delivery Owner operation reached `done` and `delivered`.
- The bot posted that reminder to `#id-stocks-swing` at 09:25 WIB on
  2026-10-01, roughly 20 hours after the source timestamp. The lag came from
  Telegram intake resuming old work after the earlier catalog-revision block;
  the legacy endpoint was capable of reading the same numeric channel ID.
  Therefore the missing News capability on the Phintas-named row did not
  explain this particular late delivery.
- The stale All-channel message was deleted and Discord verified its removal.
  The Swing Board retains the dated `Source context` entry in its INDF topic.
  That record belongs to the Board owner and remains historical context.
- Current read-only checks found no pending, leased, or executing source work.
  The source reader is active at one minute, and the direct legacy Swing
  scanner remains paused.

## Design

1. Treat `telegram:phintasprofits` as the canonical source endpoint. Add its
   reviewed `trading_plans` compatibility row and adapter capability.
2. Move the live `trading_plans` subscription from
   `telegram:phintraprofits` to `telegram:phintasprofits` in one catalog
   revision. Keep the old endpoint definition and accept already accepted old
   endpoint work during the transition, but disable its new subscription.
3. Change the Swing owner's canonical username to `phintasprofits`, retaining
   channel ID `1444713822`. During code rollout, accept the old configured
   handle for that same verified channel so the automatic release can precede
   the live config edit without blocking owner work. Render Telegram links with
   the canonical `phintasprofits` handle throughout.
4. Add a package-owned catalog transition that accepts only this exact
   subscription move. It must require consecutive snapshots, unchanged
   securities and unrelated subscriptions, the existing Phintas cursor, an
   unchanged state fingerprint, and an explicit apply guard. It writes a
   journal and advances only the catalog revision marker. It never resets,
   seeds, copies, or advances a cursor.
5. Before applying the live revision, pause the source writer through the
   Control Plane desired schedule, confirm it is quiescent, and confirm no
   active source work remains. Update the owner config and catalog while
   paused, apply the exact preview, then resume through the desired schedule.
6. The already initialized Phintas cursor is the forward-only boundary. The
   route accepts only messages after the cursor observed during the paused
   cutover. Message `35530` and all other historical messages remain
   ineligible; do not replay or backfill them.

## Boundaries

- Preserve parsing, target matching, Delivery Owner idempotency, and Board
  ownership. The adapter already carries `reply_to_message_id`; the owner
  matches a reply against known plans and sends a source-context Board event
  when a companion-text reply cannot be linked to a known attachment plan.
- Do not change delivery destinations, add a second reader, manually trigger a
  production job, send a test message, or resume the direct legacy scanner.
- A healthy natural run proves the reader resumed and retained the new
  catalog. It does not prove a new source-to-Discord delivery. Report that
  separately until a naturally arriving, post-boundary swing event completes.

## Acceptance

- Tests prove the new Phintas endpoint accepts `trading_plans`, preserves reply
  IDs, produces links using `phintasprofits`, and still accepts already
  accepted work on the old endpoint.
- Transition tests prove only the exact two-row move is allowed, the existing
  cursor and all other state are byte-for-byte preserved, and changed snapshots
  or state fail closed.
- The Control Plane registry and migration expose the Phintas compatibility
  row without making it enabled by default.
- After the merged release, a fresh production snapshot, paused-writer check,
  zero-active-work check, catalog preview, apply receipt, and natural schedule
  run confirm the future-only transition. No new delivery claim is made in the
  absence of a new eligible event.

## Operator authorization

The user has authorized the necessary code and documentation changes, managed
worktree, production schedule pause and resume, approved catalog and owner
config updates, release, and pull-request open and merge. The user's
no-backfill instruction remains in force. This approval does not authorize a
synthetic Discord post or a manual production schedule run.
