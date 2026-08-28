# X Post Watch: Insider Tracker and bounded thread settling

## Purpose

Add `@InsiderTrackX` to the configuration-driven X Post Watch and make self-authored thread collection prompt without repeatedly delaying a developing thread. The watcher will poll every minute, while remaining responsible for deterministic ingestion, state, rendering, media, heartbeats, and Discord delivery.

## Scope

The change applies to the existing `x-post-watch` cron only. It adds one profile and changes the shared semantics used by profiles whose `thread_handling.mode` is `self_chain`.

It does not backfill past Insider Tracker posts, alter live state, change Discord channels, create Discord assets, or change the immediate behavior of `disabled` profiles.

## Profile contract

The new `insidertracker` profile will use:

- `https://x.com/InsiderTrackX` and handle `InsiderTrackX`.
- Display name `Insider Tracker` and custom emoji `<:insidertracker:1537444489134604448>`.
- Existing macro, Indonesia stock, and US stock destinations.
- LLM relevance filtering, Indonesian title and summary generation, and three-way routing.
- Normal and quote posts, source media, and no external replies or reposts.
- `self_chain` handling with a 20-post cap, four-hour source age boundary, and a 15-minute maximum settling window.
- First-observation cursor initialization without historical delivery.

## Bounded thread-settling semantics

`self_chain` collects ordered, same-author reply or quote continuations. A self-authored reply remains a continuation even though ordinary replies are not forwarded.

The first observation of a thread creates one durable event and one fixed settling deadline, 15 minutes after that observation. A later continuation updates the same event's latest post and ordered thread posts. It never extends the fixed deadline.

An observably multi-post chain is ready immediately: when collection resolves two or more linked same-author posts, the event may proceed to deterministic delivery or the bounded LLM analysis stage without waiting for the deadline. A lone post remains pending until its original deadline. Thus, a seven-post chain found together is processed once, immediately, rather than waiting once per post or restarting a 15-minute wait for every continuation.

The 20-post cap and four-hour age boundary apply from the latest collected post. Thread text and media keep root-to-latest order. Existing events retain their persisted readiness deadline during rollout, preventing replays and state resets.

`disabled` profiles remain immediately ready and bypass both aggregation and settling.

## Scheduling and delivery

The existing Hermes job is rescheduled from every five minutes to every minute using the supported Hermes cron command. It continues to emit the standard `#hermes` heartbeat on every execution, including no-hit runs.

All configured profiles are fetched on each run. The thread-settling rule applies only to a profile explicitly configured with `self_chain`; it does not implicitly turn immediate profiles into threaded profiles.

The public and VPS-local RSSHub feeds for Insider Tracker currently return valid empty feeds. That is route health, not evidence of a deliverable post. The profile first cursor therefore remains the no-backfill boundary when source items become available.

## Error handling

Source failures leave a profile cursor unchanged and appear as sanitized degraded-heartbeat reasons. A missing thread parent remains a bounded single-post candidate until another feed poll supplies the relation or its deadline elapses. The watcher must never delay a multi-post event beyond its original deadline, and it must not duplicate an event while continuations update it.

## Verification

Regression coverage will prove:

1. Thread configuration accepts up to 20 posts and rejects 21.
2. A multi-post chain found in one poll is immediately ready.
3. A lone post gets one 15-minute deadline that later continuations cannot restart.
4. A continuation that joins the pending root makes the combined event immediately ready.
5. The event uses the newest post, root-to-latest text and media order, and only one durable outbox entry.
6. `disabled` profiles remain immediately ready.
7. The Insider Tracker configuration, no-backfill first cursor, and supplied emoji validate.

Before deployment, run focused and complete tests, compare local and VPS checksums after deployment, and run the documented isolated-state VPS no-post control. Do not manually invoke a live posting run as a smoke test.
