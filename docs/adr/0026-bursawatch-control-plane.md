---
status: accepted
---

# Add a Bursawatch control plane

Bursawatch configuration and observability will be managed by a dedicated
control-plane service in this repository, while the user-facing web application
remains in a separate repository. The service uses Postgres as its durable
control-plane store, with managed Supabase as the first production provider.

## Decision

The deployable backend package is `service-bursawatch-control`. Its database
migrations and versioned OpenAPI contract live with the service. Shared cron
integration code lives in `lib-bursawatch-control`; scheduled packages remain
the owners of their source adapters, cursors, deduplication, outboxes, retry
state, and domain databases.

Each invocation loads one validated configuration snapshot at startup and
records its revision. Configuration fetch failure is fail-closed: the watcher
does not poll or deliver and preserves its runtime state. Routine and fatal
heartbeat output moves to the web control plane; cron stdout control protocols
remain unchanged where Hermes consumes them.

The control plane stores operator configuration, revisions, audit records, run
summaries, and structured events. Secrets, source-controlled safety invariants,
and watcher-owned runtime state remain outside the control-plane database.

## Consequences

The web repository needs only the versioned API contract and does not need
access to this cron repository. The service becomes the validation and audit
boundary for configuration changes. A local-first event spool is required so a
temporary API or database outage does not turn observability into a new cron
failure mode.

The existing `web-config/` and `web-landing/` directories are obsolete
placeholders once the separate web repository is confirmed as the UI owner and
may be removed in a separate cleanup change. A separate `db-*` package is not
introduced because migrations have one owner, the control-plane service.
