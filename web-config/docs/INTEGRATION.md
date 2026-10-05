# Web / automation contract

**Historical status, 20 September 2026:** this note recorded the first
Supabase-authenticated workspace implementation. Its deployment and access
claims describe that review only. The current authenticated operator contract
and production verification are in [CONTROL_PLANE.md](CONTROL_PLANE.md).
Everything below is the **legacy sample/consumer contract**. It describes the
pre-control-plane baseline, not the current authenticated operator interface.

## Ownership

`web-config` owns the workspace, local preference validation and previews.
`web-landing` owns the separate public website. Both now live in
`absolutepraya/bursawatch-engine`; the earlier source was the private
`dafandikri/bursawatch-web` repository. The backend packages own
intake, filtering, bounded model work, state, scheduling and actual delivery.
No backend checkout is required to run or validate either web application.
The web app must not
write watcher JSON, launch scanners, call SSH or handle provider sessions.

The teammate's `absolutepraya/bursawatch-control-plane` branch now implements
a configuration HTTP API backed by Postgres, using Supabase Auth user tokens.
This is a shared operator workspace, not a tenant-isolated consumer API.
Keep the database backend-owned; verify deployment and authorized audience
before replacing browser-local preferences. Do not add direct browser database
access or a duplicate scheduler while the backend is being unified.

## Intake is not delivery

The backend reviewed at `absolutepraya/bursawatch` commit
`ca8ff1af5c9aeecce3acfd941ccd281283293f3b` reads X,
Instagram, WhatsApp Channels and selected Telegram sources. Discord is its
established downstream surface in that snapshot. WhatsApp
intake does not establish WhatsApp outbound delivery; Telegram intake does not
establish a Telegram bot connection. Slack/email are future delivery preferences.

Discover projects public identity/topic fields only. Tests compare those fields
with a pinned allowlisted public fixture reviewed at `f36823f`, not with a
private backend checkout. This detects local catalog drift, not subsequent
backend changes; refresh the fixture through a reviewed public-field update
when the backend owner confirms changes. Runtime config is never imported
into the client.
Use initials when no portrait is reviewed. Never expose private destinations,
newsletter IDs, emoji IDs, credentials or state. Keep source URLs visible;
team selection is not a verification or performance guarantee.

Public URL validation covers X/Instagram profiles, WhatsApp Channels and
Telegram channels. OCR, poll limits, transport resilience, tokens and scheduler
controls stay backend-owned. X original/reply/thread preferences describe what
the user wants; they do not change a deployed profile. User-facing
topic/content/summary preferences are not the runtime JSON schema and must not
be copied directly into it.

## What the reviewed backend actually reads

X and Instagram load `config/watches.json` through their strict `bin/config.py`
validators. Their scanners accept operator-owned environment overrides for the
configuration path. WhatsApp also loads strict `config/watches.json`, with an
operator CLI/environment path override. These are file readers, not web save
endpoints. WhatsApp subscription activation is a separate approved operator
step; a valid public Channel URL is not proof of subscription.

The three Telegram packages use provider-specific parser/source contracts and
operator wrappers/environment settings; they do not expose generic user-editable
source profiles. The Discord Swing Board consumes validated internal source
events through its CLI and owns its SQLite state. Its database is not a shared
user-preference store. No package in this snapshot exposes an authenticated
configuration HTTP API or user-facing shared configuration schema.

The seven-package catalog and supporting components are described in
[CAPABILITIES.md](CAPABILITIES.md). The owner-facing
[WEB_API_HANDOFF.md](WEB_API_HANDOFF.md) is a proposed future boundary, not an
implemented API or permission to change the teammate's runtime.

## Current seams

- `src/lib/sample-workspace.ts`: fixed illustrative sources, watches, runs,
  activity and evidence; `synthetic-demo` provenance and dates stay explicit.
- `src/lib/research-sources.ts`: validated local source preferences/revisions.
  Source-editor drafts are isolated by source identity or new-source platform.
- `src/lib/broker-workspace.ts`: per-firm settings and local change history.
- `src/lib/browser-demo.ts`: local watches; names retained for compatibility.
- `src/lib/delivery-preferences.ts`: delivery/bot settings and unsaved drafts.
- `src/lib/workflow-catalog.ts`: allowlisted descriptions and contract paths for
  seven reviewed backend workflows, plus supporting tools and services.
- Workflows → Library: searchable descriptions with URL-backed filters and
  contextual Following links for X, Instagram and WhatsApp only. The three
  provider-specific Telegram workflows and Swing Board are read-only,
  owner-managed descriptions. No Library-to-Settings deep links or separate
  per-workflow draft store exist.
- `/api/sources`, `/api/automations`: sample reads; mutation handlers return 403.

The isolated Sectors client utility is retained and unit-tested but not called
by the sample provider. It is not proof of live Sectors integration. No second
scheduled worker or persistent SQLite database ships with this package.

## Required before connecting users

Agree a versioned authenticated API with per-user ownership checks on every
request, server validation and verified destination ownership. Configuration
saves need revision preconditions, idempotency, actionable errors and a redacted
audit trail. Tokens, cookies and webhook/session secrets never belong in local
preference fields. Server-reported capabilities govern which controls are enabled.

Distinguish draft, accepted, applied and rejected configurations; distinguish
prepared, queued, delivered and failed messages. Return timezone, next run,
last completed run, freshness and provider health. Market-session validation
belongs in the backend: weekday previews are not holiday-aware schedules. The
reviewed Swing Board requires a Yahoo daily bar dated exactly for the weekday
being reconciled; it does not use an annual holiday file. Its documented 16:30
WIB close check and 17:00 unavailable-data retry are contracts, not proof that
the frontend observed a scheduled execution.
Preserve bounded retries, deduplication and unattended-run evidence. Silence
alone must not imply a healthy source.

## Track 02

The submission needs Sectors REST/MCP as a core source and truly autonomous
schedule/trigger execution. Show its configuration beside real unattended-run
timestamps and evaluation/delivery outcomes. These sample logs are not
qualifying evidence. Automated trade execution is excluded. Verify all current
competition rules and disclose earlier work; fresh migration commits do not
change the original work's age.
