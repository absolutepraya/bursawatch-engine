# Bursawatch control-plane implementation plan

## Goal

Give Bursawatch crons a versioned live-configuration and observability
boundary without moving watcher-owned runtime state or touching the separate
web repository.

## Architecture

`service-bursawatch-control` owns the API, Postgres migrations, config and
desired-schedule revisions, audit records, run summaries, structured events,
and the OpenAPI contract. `lib-bursawatch-control` owns the cron-side client
and local-first event spool. The web application calls the service API and
never receives database credentials. Existing cron packages keep their source
and state contracts until each one is migrated deliberately. Desired schedules
remain ineffective until a separate trusted VPS reconciler applies them through
the Hermes CLI.

## Delivery order

1. Add the service package contract, database schema, and OpenAPI document.
2. Add the shared client with strict response validation and bounded local
   event buffering.
3. Add opt-in live configuration to the JSON-backed X Account Watch,
   Instagram Account Watch, and WhatsApp Channel Watch packages. Their
   existing JSON paths remain the default until a reviewed runtime cutover.
4. Add service repository and API tests using a fake store, then add the
   production Postgres adapter behind `DATABASE_URL`.
5. Add X run and event reporting without changing Hermes stdout control
   protocols. Extend the same reporter seam to the remaining watchers before
   removing Discord heartbeat writes.
6. Validate the local slice and document the VPS deployment boundary. Do not
   deploy, retarget a scheduler, remove Discord writes, or move production
   state in this change.
7. Add catalogued desired schedule revisions for supported interval jobs. Keep
   fixed calendar and queue schedules read-only, and expose reconciliation
   state before building or deploying a scheduler reconciler.
8. Reuse the strict source-controlled config parsers for the initial X,
   Instagram, and WhatsApp JSON watchers through isolated subprocess
   validators. Do not enable a web write for a watcher until its validator
   directory is configured.
9. Add Phintraco's small typed source and destination snapshot, frozen
   revision lifecycle events, and isolated validator. Keep parser policy,
   board handoff, retries, media, and state outside web configuration.
10. Add Kelas Investasi's small typed source, destination, and bounded prompt
    snapshot, frozen lifecycle events for both scan and agent submission, and
    isolated validator. Keep the output schema, parser policy, board handoff,
    retries, media, and state outside web configuration.

## Non-goals for this slice

- Changing live Hermes jobs or schedules.
- Moving watcher JSON, SQLite, cursor, outbox, media, or resilience state.
- Migrating every watcher in one release.
- Deleting the current Discord heartbeat path before the web control plane is
  deployed and verified.
- Giving the web repository direct Supabase service-role access.
