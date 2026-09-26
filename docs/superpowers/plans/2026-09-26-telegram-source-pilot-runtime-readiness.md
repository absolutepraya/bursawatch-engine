# Telegram Source Ingest Runtime Readiness

**Date:** 2026-09-26

**Status:** Approved implementation follow-on under the user-approved
[Source Catalog and platform-pipeline plan](2026-09-24-bursawatch-source-catalog-and-pipeline.md).

## Goal

Make the existing Telegram source-ingest pilot installable and verifiable by the
Bursawatch release agent, while keeping all existing Telegram jobs as the only
production readers until a separately approved source and scheduler cutover.

## Scope

1. Promote the required shared source-ingest code and Telegram pilot from
   metadata-only release-manifest entries to dependency-ordered runtime units.
2. Add the runtime wrapper and document its environment, private state, log,
   heartbeat, and shared-owner contracts. Do not create or enable a Hermes job.
3. Add a release-agent verification path that exercises the installed pilot
   with synthetic inputs only. It must not read secrets, contact Telegram, write
   the Control Plane or Source Media service, invoke a domain owner, or send to
   Discord. Use only disposable verification state.
4. Update the affected package, release, and implementation-plan documentation.

## Acceptance

- Every deployable source path maps to exactly one release-manifest unit, and
  the Telegram runtime declares the libraries and domain-owner runtimes it
  imports or invokes.
- The wrapper can run the release agent's no-post verification without loading
  production credentials or making network requests; the normal scheduled entry
  point remains dormant until separately approved.
- Tests cover manifest dependencies, wrapper safety, and the synthetic
  verification path. The existing Telegram adapter and repository checks pass.
- No production job, source subscription, cursor, inbox event, media object,
  Discord message, or schedule is changed by this work.

## Global constraints

- The current Telegram jobs remain production readers until a separately
  approved cutover.
- Do not backfill, reset cursors, replay source history, post test messages,
  manually trigger live jobs, alter schedules, deploy, or mutate production
  storage under this plan.
- Use the Source Media Owner for private media and the shared Discord Delivery
  Owner for messages. Never add direct provider or Discord credentials to the
  Control Plane or adapter source.
- Update package contracts and release metadata in the same change as runtime
  behavior.

## Task 1: Make the Telegram pilot runtime releasable but unscheduled

Implement the release-manifest runtime mapping, runtime wrapper, isolated
synthetic release verification, tests, and targeted documentation listed in
Scope. Keep source routing disabled and do not register, enable, invoke, or
reschedule the Hermes job. Finish with the focused Telegram/release tests and
the repository verification required by the root contract.

The runtime dependency graph must follow actual imports and owner invocations:
activate only `lib-bursawatch-source-ingest/bin/**` for this pilot while keeping
the X, Instagram, WhatsApp, and RSS pilot units metadata-only. Declare the
Control Plane, pipeline runtime, Source Media, Discord Delivery, Telegram
resilience, and the Market News, Phintraco Swing, and Kelas owner runtimes.
The wrapper's release verification uses synthetic in-memory data with a
scrubbed environment and cannot load credentials or perform network or pilot
state operations. Installing this runtime does not create a Hermes job.

Before the later Phintraco News cutover, prove that the existing Market News
reader no longer fetches Phintraco while Tuntun remains covered. The current
reader fetches both endpoints together, while this pilot intentionally skips
Tuntun. Either move the legacy reader to Tuntun-only or onboard Tuntun into the
shared adapter first, then verify there is neither a coverage gap nor a
double-read. This is a cutover prerequisite, not part of runtime installation.

The Phintraco News endpoint can preview its legacy boundary from the
Market News `providers.phintraco.observed_message_id` field. Its cursor seed
blocks while any Phintraco candidate remains in an active phase or any
stock-status event remains `pending_delivery`. Reconcile those old domain
effects against inbox events and owner receipts before retrying the preview.

## Verification

- Telegram source-ingest package tests.
- Release-agent and manifest tests.
- Shell syntax and executable-mode checks for the runtime wrapper.
- `bash scripts/test-all`.
