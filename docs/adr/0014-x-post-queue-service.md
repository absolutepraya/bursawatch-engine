# Separate X source polling from queue servicing

Status: accepted and deployed

## Context

The X watcher currently combines source polling, durable outbox processing, and
one bounded Hermes agent claim in a single invocation. Each invocation polls all
enabled profiles, then claims only the oldest ready LLM event. The live poller
runs every 10 minutes. Increasing that cadence would reduce queue wait, but it
would also increase RSSHub and direct-X requests and could consume X
authentication or rate-limit budget.

The missing IDNFinancials post demonstrated queue latency rather than source
loss: the post entered the durable outbox, waited behind older LLM events, and
was eventually delivered. The source log also contains a direct X HTTP 429, so
polling frequency must remain independent from queue service frequency.

## Decision

Keep the existing X source-polling job at its current cadence. Add a companion
queue-only wrapper that sets `X_POST_WATCH_QUEUE_ONLY=1`. Queue-only runs use the
same state lock and durable state, skip every RSSHub and direct-X fetch, drain
ready deliveries, send the standard heartbeat, and claim at most one oldest
ready LLM event.

Expose the active LLM outbox count and oldest ready-event age in the heartbeat.
Implement and verify this for X first. Do not change Instagram as part of this
first rollout. Do not reset, replay, or backfill live state.

The live companion job is registered as `x-post-queue-worker` with job ID
`ca1839ba1dcf`, a minute-level cadence, the `x-post-watch` skill, and
`x-post-watch-queue.sh`.

## Consequences

- Queue service can run more frequently without increasing source requests.
- The poller and queue worker share the existing lock, cursor, outbox, leases,
  delivery ledger, and no-post verification model.
- The heartbeat stream becomes more frequent after worker registration and
  reports queue pressure directly.
- Only one LLM event is claimed per worker invocation. Sustained input above
  agent throughput still produces visible backlog growth instead of silent
  loss.
- The worker is live only as a queue service. The source poller remains on its
  existing cadence.
