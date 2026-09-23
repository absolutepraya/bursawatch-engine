# Proposed web configuration API

**Historical proposal:** the teammate has since published a different operator
API on a development branch. Follow [CONTROL_PLANE.md](CONTROL_PLANE.md) for
the reviewed implementation. The tenant-scoped routes below remain proposals;
they must not be mistaken for implemented endpoints.

**Proposal only. Nothing in this document is an implemented endpoint, an agreed
database schema or permission to modify the teammate's repository or runtime.**
The backend owner must review the contract before either side implements it.

## Verified starting point

The read-only backend review is pinned to
`ca8ff1af5c9aeecce3acfd941ccd281283293f3b`. The seven packages and their public
contracts are mapped in [CAPABILITIES.md](CAPABILITIES.md). All seven deliver to
Discord. X, Instagram, WhatsApp Channels and Telegram are intake platforms;
their presence does not establish outbound adapters for those platforms.

X, Instagram and WhatsApp read strict static JSON configuration. Telegram
packages use operator wrappers, CLI and environment configuration. The Swing
Board's SQLite database is single-owner runtime state, not a shared user
configuration database. This snapshot supplies neither a web configuration API
nor a shared user-settings schema. Price context uses Yahoo; Sectors is not yet
a core backend data source in this reviewed implementation.

The web currently stores preferences locally, serves dated sample runs, and
rejects mutations on its sample `/api/sources` and `/api/automations` routes.
Do not point an HTTP client at the proposed routes below yet. Do not silently
upload existing browser preferences when a future connection becomes available.

## Ownership and trust boundary

- The web owns forms, accessible feedback, drafts and previews. It never opens
  a shared database, launches a scanner, calls SSH or reads provider sessions.
- The backend owns identity authorization, configuration validation, scheduling,
  provider access, event filtering, retries, state and actual delivery.
- Authenticate every request. Derive the active tenant from the authenticated
  session and verified membership, not a client-supplied owner field. Check
  resource ownership on every read, write, list and operation-status lookup.
- Prefer a same-origin web server boundary to keep backend credentials out of
  browser bundles. Cookie sessions require secure, HttpOnly cookies and CSRF
  protection for mutations; exact authentication is an owner decision.
- Return opaque application resource IDs and safe destination labels only.
  Do not expose Discord destination IDs, Telegram peer/session identifiers,
  WhatsApp newsletter IDs, cookies, webhooks, tokens or operational file paths.
- Separate ordinary configuration access from operator authority. A web save
  cannot change global schedulers, restart services, replay historical messages
  or reset cursors. Existing source contracts and future-only intake remain
  authoritative; custom instructions cannot override them.

## Proposed read surfaces

All paths use a proposed versioned `/api/v1` prefix. They are names for contract
discussion, not routes implemented by this frontend or the reviewed backend.

| Route                  | Required safe response                                                                                                                                                                                                                        |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /capabilities`    | API version, server time, capability revision, workflow IDs, supported input types, field constraints, available output adapters and permissions for this tenant. Distinguish repository support from connected or operational service state. |
| `GET /settings`        | Versioned user-facing source, workflow, delivery and bot preferences; current desired revision, applied revision and application status. Exclude runtime configuration and secrets.                                                           |
| `GET /connections`     | Opaque connection reference, provider, user-recognizable label, verified ownership, status, last successful check and safe recovery action.                                                                                                   |
| `GET /routes`          | Tenant-owned output routing rules: workflow/topic, opaque verified connection reference, destination label and enabled status. Source-follow settings are not delivery routes.                                                                |
| `GET /operations/{id}` | Application outcome for an accepted configuration revision, per-resource failures, safe next step and current applied revision.                                                                                                               |
| `GET /runs`            | Cursor-paginated real executions, filtered by authorized workflow/time window. Include timestamps, trigger, configuration revision and separate evaluation/delivery outcomes.                                                                 |
| `GET /runs/{id}`       | Tenant-scoped evidence, source attribution, data freshness and redacted failure details for one execution. Never raw provider payloads, prompts or private source content by default.                                                         |

Capabilities must gate server validation as well as controls. Planned WhatsApp,
Telegram, Slack and email outbound preferences remain local plans until a
backend adapter and verified ownership flow exist. Even Discord support in
source code is not evidence that the current user has a connected destination.
Unsupported fields must be explicitly rejected or marked non-applicable, never
silently accepted and ignored.

## Proposed save and application protocol

Use `PUT /settings` to submit one validated user-facing configuration document;
the exact schema and atomicity must be agreed before implementation. Public
source identities and user preferences are an allowlisted projection, not a
copy of watcher JSON. Route references must resolve to tenant-owned, verified
connections. A label alone never proves destination ownership.

1. Read settings and an opaque revision/ETag. Preserve an editable local draft.
2. Send `If-Match` for that revision and a new `Idempotency-Key` for the intended
   mutation. Reject missing preconditions (`428`) and stale revisions (`412`)
   without changing settings. Show a conflict review; do not overwrite or
   auto-retry the stale draft against a new revision.
3. Validate all fields server-side, including source eligibility, immutable
   constraints, destination ownership, quiet hours, timezone and any supported
   schedule. Return `422` field errors while preserving the draft. Unauthorized
   or unsupported operations do not create a new revision.
4. Accept a valid change durably before returning `202`, a desired revision and
   an opaque operation reference. This means accepted, not applied. A synchronous
   `200` may mean applied only when the backend can verify application.
5. Read the operation with bounded polling and backoff until the result is
   known. The backend reports the actual applied revision; a timeout leaves
   status unknown, not failed or successful by assumption.
6. The backend emits a redacted audit entry with actor, time, affected resource,
   desired/applied revisions and outcome. It must define atomic application or
   explicitly return partial results; the UI must not present partial application
   as complete success.

Scope idempotency records to tenant, actor and operation. A retry with the same
key and identical payload returns the original operation/result; the same key
with a different payload is a `409` conflict. Agree a retention period covering
the retry window. Never automatically retry a mutation with a new key after an
ambiguous network result. Define whether new revisions supersede queued work;
an older operation finishing late must never overwrite a newer applied revision.

## Status and readable feedback

Keep these independent dimensions; one green badge must not conflate them.

- **Configuration:** local draft → accepted → applying → applied, or rejected.
  Report desired and applied revisions independently. Retain last applied
  settings when the new revision fails. Example feedback: “Saved in this browser,”
  “Change accepted,” “Applied,” or “Could not apply — previous settings remain.”
- **Connection:** not connected, awaiting authorization, connected, degraded,
  authorization required, or unsupported. Include the time of the last verified
  observation; an old status is stale rather than automatically healthy.
- **Execution:** queued, running, completed or failed. A completed check may
  produce no eligible changes and therefore no delivery.
- **Delivery:** not required, prepared, queued, delivered or failed. A provider's
  acceptance is not a read receipt; never claim a recipient read the message.

Errors need a stable code, concise message, field errors where relevant, retry
guidance and an opaque request reference. Sanitize provider failures. Use `401`
for authentication expiry, `403` for forbidden operations, and a consistent
non-disclosing response for inaccessible resource IDs. Rate limits include a
bounded `Retry-After`; do not turn provider authentication failures into retries.

## Scheduling, evidence and data quality

Expose the backend's actual trigger and schedule, IANA timezone, effective
configuration revision, next due time, last attempted/completed run, source-data
timestamp and observation time. Represent unavailable values explicitly; do not
derive a reassuring next-run badge from browser-local schedule preferences.

The Swing Board contract currently specifies weekdays at 16:30 WIB and a 17:00
retry only for an unavailable first close check. It requires an exact-date Yahoo
bar and retains prior facts when unavailable. This is not an exchange-holiday
calendar or proof of a live scheduled run. The API must preserve these details
rather than replacing them with generic weekday scheduling.

Real run evidence should associate source events, evaluations and delivery
attempts without exposing private payloads. Distinguish no change, filtered,
duplicate, deferred, stale data and provider failure. Keep sample and live
datasets separate. No message is not proof of a healthy watcher. Do not expose
a generic manual “Run now” or replay operation as part of this initial contract.

For Track 02, real unattended execution evidence and Sectors REST/MCP as a core
data source are still separate completion requirements. Neither a settings save
nor the frontend's sample history proves either requirement. No automated trade
execution endpoint is proposed.

## Agreement and rollout checklist

- Backend owner approves authentication, tenancy, schema, capabilities, routing,
  revision semantics, asynchronous application and source-specific constraints.
- Both sides share sanitized contract fixtures. Test tenant isolation, IDOR,
  invalid fields, stale writes, duplicate retries, partial application, expired
  authorization and delayed/out-of-order responses.
- Destination setup uses an approved ownership-verification flow; provider
  credentials never pass through local preference fields or analytics logs.
- Let users review a local-preference import; validate every field and unsupported
  choice before creating server-owned settings. Preserve the local draft if it
  fails. Do not blend sample activity into real accounts or imply historical replay.
- Start with explicitly supported capabilities. Enable live save only after
  acceptance/application/read-back are verified against an approved test setup.
- Validate browser flows, keyboard/mobile feedback and real read-after-write
  behavior. Verify actual unattended runs separately without using production
  destinations for smoke tests.
- Keep this proposal and [INTEGRATION.md](INTEGRATION.md) current when an API is
  agreed. Until then, ship the navigable frontend with honest local-save states.
