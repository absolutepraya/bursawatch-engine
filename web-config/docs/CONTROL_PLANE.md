# Control-plane integration

The current web packages and control API are reviewed together in
`absolutepraya/bursawatch-engine`. The source import is documented in
[MIGRATION.md](MIGRATION.md). Historical review hashes below identify the
earlier backend repository and are retained as provenance; the current engine
snapshot used for this import is `6abf28732f92cc8c1249372141f575f794d307b5`.

## Reviewed handoff

The 20 September 2026 Web App Handoff and backend branch
`absolutepraya/bursawatch-control-plane` at
`25079b3465a97de132ed977ffec3ce3a488a867a` define this implementation.
Contract: `service-bursawatch-control/openapi/control-plane.v1.yaml`.
The API origin is `https://api.bursawatch.abhipraya.dev`.
Read-only probes returned HTTP 200 from `/healthz` and 401 from unauthenticated
`/v1/watchers`. This verifies reachability and rejection without credentials,
not user permission, database contents or successful scheduler execution.
No teammate source, runtime, database or schedule was changed by this work.
Follow-up review of main at `103a4856901c51f145851af8768506124f83c174`
added X's optional `show_quoted_post` control. Its availability on the deployed
API still depends on the owner's validator rollout. The field-by-field audit
is in [CONFIGURATION_COVERAGE.md](CONFIGURATION_COVERAGE.md).
Read-only review of backend main at
`a23a416a5e5ba5a524bccfdebb83e9f375b973cb` on 21 September confirmed that its
four subsequent release-infrastructure commits leave these API routes and
watcher schemas unchanged. No profile-picture or stock-research API is present
in that backend revision.

Read-only follow-up at
`96b83fdbca6e9383183d3ded5d42f23a8c73fc8a` found no Sectors client or reusable
stock-research API. The reviewed price ingestion uses Yahoo Finance. This is
source-code evidence, not proof of deployed provider access or market-data
availability. The user declined paid Sectors requests; do not add a web key or
consume its credits. No teammate runtime was changed or verified in this pass.

A deeper review at `f426e24f447961d1371638735ccc6e3a060ef43e` corrected two
missed capabilities already present in the preceding revision: WhatsApp v2
observe/forward configuration, and separate profile/avatar endpoints. This web
pass implements the WhatsApp editor. The subsequent engine review at
`a343ec4d6897c927edee17a4ea3779febc926649` connects profile/avatar metadata as described below.
The eight intervening commits do not change the control API or config validators.

## Authentication and transport

`/workspace` uses Supabase's browser client for email/password authentication,
session persistence, refresh and local sign-out. It is **not cookie-based SSR
authentication**. The page pre-renders a public opening shell; protected records
are fetched only after sign-in. The allowlisted workspace URLs can use the CDN
because they contain no user session, configuration, runs or source settings.
Only the validated public Supabase URL/publishable key is built in. Updating
those public settings requires rebuilding. Supabase dashboard membership is not
an app account.
The owner supplies an Auth account and explicitly allowlists admin UUIDs.
There is no public signup. This is a shared operator workspace, not a
tenant-isolated consumer service.

The browser calls same-origin `/api/control` with its current user access token.
That Next.js server route forwards the token to the configured HTTPS origin.
The backend verifies JWT signature, issuer, audience, role and authorization on
every request; the proxy's JWT-shape check does not establish identity.
No database password, service-role key, machine token or reconciler token is
needed. The backend owns all Postgres access.

Unlike the handoff's direct-browser option, this same-origin proxy does not
require browser CORS access to the control API. It accepts no caller-supplied
upstream URL, rejects redirects, disables caching, requires same-origin PUTs,
bounds request sizes/timeouts, allowlists paths, validates response identities
and strips arbitrary provider error bodies. The upstream origin is server-only
configuration. Deploy to a Node-capable Next.js host, not a static export.
Never cache `/api/control` responses or protected records. Static `/workspace`
HTML is a public shell only, not an authenticated server-rendered response.

## Workflow and job evidence terminology

A **workflow** is a catalogued configuration resource for a **domain owner**.
The owner component links that resource to its **shared jobs**, using the
component inventory's `job_ids`. A `watcher:<id>` configuration resource ref
and a watcher ID identify the same workflow, but the ref is not a URL query ID.
Jobs can support multiple components; a workflow is not itself a schedule.
Jobs resolves one distinct supported watcher from a domain owner's resource
refs before constructing its editor link. Bare watcher IDs remain compatible;
unrelated, unknown or ambiguous refs stay readable without a guessed editor.
Source adapters link to Sources, while delivery services remain non-navigable.

Catalog endpoint identities are opaque, case-sensitive ASCII IDs bounded to
128 characters. Activity, registry, compatibility, effective subscription and
saved override identities share a validator that preserves dots and mixed case,
including Instagram handles and WhatsApp channel IDs. Saved overrides use the
same rule in catalog responses and configuration writes. Component, job,
pipeline and user-created endpoint ID rules remain
separate. Activity reads still validate the requested component identity,
timestamps, states and response shape; malformed responses remain unavailable.

A **saved configuration revision** records settings accepted by the API. A
**run-used revision** records which configuration a particular recorded owner
run used. A matching revision establishes use by that run, without establishing
that subsequent work used it or that a post was delivered.

A **desired schedule** is the stored job setting. **Reconciled state** reports
whether the scheduler applied its revision. **Observed state** is the latest
observer evidence of the runtime job, including freshness and comparison.
Active, paused, pending, stale, mismatch, unknown and unavailable remain
separate states. An absent observation after a successful read is unknown;
a failed observation read is unavailable. Neither establishes delivery.

A **catalog-only read** intentionally omits runtime evidence. A successful read
with no rows is **loaded empty**; an omitted resource is **not loaded**; a failed
read is **unavailable**. Empty arrays alone do not prove that a read completed.
Render runtime claims only in views that requested that evidence, and retain
partial-read failures beside the relevant evidence.

## Loading and failure feedback

The browser fetches only the current destination's data. Catalog-driven views
first check watcher membership; a direct run link reads the authorized event
endpoint without requesting unrelated watcher histories:

- Sources reads the authenticated Source Catalog and effective subscription
  snapshot. The workflow list reads the separate watcher catalog. Neither
  presents unloaded schedules or history as empty results. Workflow catalog
  rows show the saved configuration revision and Configure action, without
  schedule, run, configuration-use or shared-job claims. Overview passes its
  loaded component, job and observation records into watcher rows. Failed
  relationship reads remain unavailable; failed observation reads retain known
  job identities with unavailable status.
- A selected workflow starts its admin configuration read after catalog
  membership is confirmed. It requests only component-linked operator jobs,
  then observations for those job IDs, to link related jobs and show observed
  state; schedule controls live only on Jobs. X also loads source-poll runs for
  its delivery checks; other editors do not fetch unrelated run histories.
- A run timeline reads events directly; it does not wait for all workflows'
  histories. Metadata already present in the same signed-in component can be
  shown; direct links do not invent missing run metadata.
- History lists read runs; Overview reads jobs and runs. Detail reads
  use at most six concurrent slots, with each completed request freeing its
  slot immediately. Account makes no control API requests.

Obsolete reads are cancelled on navigation. Initial session restoration is
bounded to 12 seconds. Each control read has one 15-second deadline covering
session restoration, network access and response decoding; saves retain a
25-second deadline for their revision preflight and write. A cancelled or
timed-out write remains an unknown outcome and is never automatically retried.

The shared loading UI begins with a skeleton and subtle shimmer only while a
read is pending, adds a spinner after two seconds, and exposes elapsed time and
request details after eight seconds. Known requests show a determinate progress
bar and completed/total count; the details show safe per-resource pending,
loaded, or error status. Sources tracks its catalog and effective-subscription
reads as two requests, and compact loaders name the actual operation. Reduced
motion leaves the skeleton static and disables the spinner animation. Partial
failures retain successful results with safe resource-specific reasons and
recovery actions. Lost authentication discards protected records; it must not
leave the editor or false empty diagnostics visible. Diagnostics never include
raw provider errors, secrets or config.

## Implemented surface

The desktop sidebar and mobile bottom navigation expose the same seven
destinations: Overview, Sources, Workflows, Jobs, History, Published and
Account. They reuse
the sample workspace's visual language while keeping authenticated API records
and sample browser preferences separate.

- Overview: recorded-run counts, 24-hour/7-day chart with an accessible table,
  schedule reconciliation and recent runs. Coverage is at most 50 latest runs
  per watcher, explicitly disclosed; these are not complete historical totals.
- Sources: separate Securities and People tabs of dated public references.
  Securities shows two-column thumbnail previews; People uses a three-column
  profile layout where space permits. Illustrative added/to-add presentation is
  not saved membership, an enabled source, a health check or database state.
- Workflows: live catalog and eight schema-specific admin editors for X,
  Instagram, WhatsApp Channels, market news, daily Phintraco swing calls,
  GTW investment classes, the swing board and Stockbit Snips. Each supported workflow explains
  its input, processing and output. All existing editor fields remain available;
  unknown keys are preserved when a known field changes. No private config is
  bundled as defaults. Each selected workflow links to its related jobs and
  shows their observed state. Schedules are edited only from Jobs.
- History: recorded timestamps, config revisions, outcomes and event metadata.
  A server-side event-specific projection exposes bounded source IDs, validated
  counts and execution flags only. Raw messages and arbitrary attributes remain
  excluded. Missing counts are not zero; run totals and simulated dry-run counts
  cannot establish per-post/channel receipt. An `ok` run is not proof of message
  delivery or Sectors use.
- Jobs: declared jobs appear once with their component relationships, desired
  schedule, reconciler state, fresh observation and last execution evidence.
  Backend `can_edit` gates interval controls; fixed jobs and viewer sessions
  have no save action. `/workspace/schedules` redirects here.
- Published: cursor-paginated confirmed News and Swing deliveries since the
  recorded forward-only boundary. Date, source, type, route, ticker and group
  filters are sent to the authenticated read API before pagination. Detail
  shows exact delivered legs and safe source or related-publication links.
  Publisher coverage is shown separately; an incomplete or unknown checkpoint
  keeps an empty result explicitly bounded. Coverage loading or a failed read
  is distinct from a confirmed inactive feed. Coverage errors survive page
  filtering and pagination, and the coverage retry reads only coverage.
  Authentication or permission failure on any Published read clears loaded
  pages, detail and coverage, cancels pending reads, and blocks further reads
  until sign-in or an explicit permission retry.
- Account: current identity, copyable UUID for owner-managed access and sign-out.

The Sources page (`/workspace/sources`) reads the versioned Source Catalog and
effective subscription snapshot from the authenticated API. Securities lists
only engine-supported symbols; while that registry is empty, the page shows an
explicit empty state. Institutions are curated engine records with static 4:3
presentation art where available. People & Org combines seeded identities and
user-managed records. The catalog response includes a backend-derived
`can_edit` flag. Viewers see read-only records, while admins can draft new
identities, platform endpoints, publisher defaults and compatible endpoint
overrides, then save an optimistic catalog revision. A successful PUT followed
by a failed read leaves the draft locked and clearly marks refresh as
unconfirmed; only an explicit successful reload restores editing. Unsaved catalog
changes and in-flight saves warn before link navigation or closing the page;
manual reload requires confirmation before discarding a changed draft. Catalog
drafts and their selected tab survive same-document Back/Forward in the existing
signed-in user's JavaScript memory, without persistent browser storage. Returning
rechecks backend edit access and catalog/effective revision consistency before
restoring the draft. A changed server revision or an unconfirmed save keeps the
restored draft locked until explicit reload. Access failure or lost edit access
clears its retained draft; sign-out and identity change clear all retained drafts.
Late save completions after leaving cannot clear or unlock a recovered draft.
Newly added endpoints remain pending identity verification;
an enabled intent is not an effective subscription or delivery proof. The page
shows default, override, effective draft and saved effective values separately.
For ingestion, verified or enabled catalog state remains subject to the
platform adapter's fixed identity bindings and owner configuration-snapshot
support. Current platform pilots fail closed for unbound endpoints; adding a
person to the catalog does not silently start provider polling or delivery.
The fixed watcher editors, including Stockbit's four RSS lanes, remain independent.
There is no persistent browser source cache, object-storage upload, direct database access,
or custom-security creation. Public curated assets remain in the web package.

The same-origin proxy allowlists GET `/source-catalog` and
`/source-catalog/effective`, plus PUT `/source-catalog/config`. It forwards only
user JWTs; the backend enforces admin writes and validates compatibility.
Existing watcher, schedule and avatar routes retain their separate contracts.
The proxy exposes no run creation, internal reconciliation, provider connection
or trade endpoint.
Private admin config stays in the signed-in session's memory, not public
fixtures or persistent browser storage. Unsaved drafts survive same-document
Back/Forward; they clear on sign-out, identity change or page reload. Returning
to a draft based on an older server revision blocks saving until review.
`/app` is a separate sample experience;
its local custom workflows and connection preferences are not uploaded.

Configuration GETs require admin authorization for human users. PUTs save a
complete `{config_version, config}` object through the backend, which records
the revision in Postgres. This is the dashboard's database read/write path;
the browser has no direct database access. Viewer access to watcher summaries
does not grant access to profile configurations or destinations.

The current backend exposes profile metadata through `GET /v1/watchers/{id}/profiles`
and avatar controls through `PUT .../profiles/{profile_id}/avatar` and
`POST .../profiles/{profile_id}/avatar/refresh`. The selected workflow's Source
profiles panel loads these records only after an explicit Load profiles action.
Signed-in viewers can read profiles; editing controls appear after a successful
admin config read, and the backend authorizes every mutation. Profile reads may
synchronize backend metadata and are not used as anonymous diagnostic probes.
Responses are identity-validated and raw refresh errors become a boolean error
indicator. HTTPS URLs reject credentials, fragments, custom ports and literal or
local-network hosts before being rendered without referrer information. Images
fall back to initials if loading fails. Admins can save automatic/manual photo
settings and request a refresh; refresh acknowledgement is not completion.
Uncertain changes block further writes until profiles are reloaded. Avatar writes
have no atomic revision precondition in the backend; coordinate shared edits.
Current catalog images remain
reviewed static assets. There is still no arbitrary workflow creation, personal
brokerage goal/language/tone config or outbound WhatsApp/Telegram destination API.
Do not translate sample preferences into unsupported config keys.

## Save semantics and remaining limitation

Before a write, the web server reads the current revision. A stale draft is
rejected with a reload instruction. This is **best-effort preflight**, not atomic
compare-and-swap: another admin could write between the GET and PUT. The current
backend has no If-Match/idempotency contract. Coordinate one editor per record
until the backend adds atomic revision preconditions. Do not present this
protection as a complete concurrent-editing guarantee.

Validation errors keep the draft and identify safe field paths. Conflicts,
network failures, server failures or malformed write acknowledgements never
trigger automatic retries; uncertain saves require reading current state first.
Saving config means a revision was stored for future invocations, not that a
running invocation changed. A schedule is effective only when reconciliation
reports `applied`, matching applied/requested revisions and `effective=true`.
Polling is bounded and paused while hidden; a failed refresh is not success.
Fixed schedules cannot be edited.

Stockbit's authenticated editor sends the complete version 1 config through
the same config GET and PUT path. Its only editable fields are the four fixed
feed switches, two Discord news channel IDs, and one optional additive analysis
instruction of at most 800 normalized Unicode code points. RSS URLs, feed and
route identities, heartbeat, credentials, parsers and fixed agent rules remain
system-owned. A disabled lane stops new intake; on resumption, its first
successful fetch establishes a future-only baseline without replaying paused
items. Articles already queued keep their frozen dispatch settings. A saved
config revision applies to future work after a valid runtime read and is not
delivery proof. Jobs is the single schedule editor and uses the API-provided
bounds. Workflow details link back to the shared jobs that serve their adapters
and owners. A saved interval or enabled change stays pending until that exact
schedule revision is reported applied and effective.

## X source and delivery evidence

The X editor explains paused sources, future-only initialization, eligible post
types, relevance filtering, thread delay and saved Discord destinations. New
profiles start paused, with a five-minute self-chain settle default. Existing
saved settings are preserved. A new account's first successful nonempty poll
establishes its baseline and queues none of the posts already returned.

The reviewed source-poll baseline is ten minutes; the current saved and applied
schedule is authoritative. Queue-worker runs process queued work and do not
fetch X. The diagnostic panel recognizes scheduled source runs only when their
job ID is `bursawatch-x-account-watch-source` or `x-post-source`; it excludes
queue runs and `agent_submission` runs. A matching `config_revision` shows
which saved revision a recorded source run used. Neither an `ok` run nor a
matching revision proves a particular profile was fetched or a tweet reached
Discord. Relevance rules can exclude personal or test posts.

See [X delivery troubleshooting](X_DELIVERY_TROUBLESHOOTING.md) for the ordered
checks and evidence limits. The affected live profile, its applied runtime
settings and its Discord delivery have not been verified. These web changes
do not reset cursors, replay tweets, alter scheduler jobs or repair a runtime
provider connection.

## Local setup and verification

Create an ignored `web-config/.env.local` from `.env.example` and supply only:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_your_public_key
CONTROL_PLANE_API_URL=https://your-control-api.example
```

Do not copy the backend's `.env` into this package. Use Node 24 and run
`npm ci`, `npm run check`, then the browser checks in the package README.
Unit/browser regressions use synthetic contracts and intercepted authentication;
they cannot establish that a real user is allowed to access production.

## Production rollout status (2026-09-30)

The operator workspace and Published feed shipped in PR #28. PR #29 corrected
the reconciler schedule contract; PRs #30 and #31 corrected Hermes observer
status and legacy cron handling. All four PRs are merged. The rollout release
SHA `b1297c269bd42fb7d56624c362e0e0e1fe059144` was then-current `main`, passed
its exact CI gate, and the VPS release agent reported that SHA as released. The
Control Plane health route,
public landing page, and authenticated workspace view returned successfully.

The production snapshot on 2026-09-30 found 13 Hermes jobs, 8 active and 5
paused, with all 8 desired interval schedules matching. The separately
installed and enabled observer timer completed a natural run that reported all
13 jobs. The authenticated Jobs page showed 8 observed active jobs, 5 observed
paused jobs, and no unknown observations or attention state.

The Published page boundary is 30 September 2026, 14:15 WIB. At the production
page check it showed no confirmed publications since the boundary and marked
publisher coverage incomplete or unverified. This does not prove that no
upstream delivery occurred. A published row requires a supported owner
projection backed by confirmed Delivery Owner receipts and does not include
historical backfill.

No live configuration or schedule write, manual watcher run, or test post was
used for this rollout verification. These checks do not establish natural
source-to-delivery coverage or separate Track 02 evidence.

## Historical local verification (2026-09-22)

The original local check followed workspace visual unification and loading
improvements. Both production builds, formatting, lint and types passed; 275
configuration-app unit tests and 24 landing tests
passed. Isolated browser suites passed for viewer/admin behavior, 422 field
errors, 409/uncertain-save recovery, schedule pending-to-applied responses,
same-document Back/Forward draft recovery, stale restored revisions, sign-out,
keyboard controls, the source library, reduced motion and 375px/200% text layouts.
Additional source-editor checks exercise X, Instagram and WhatsApp source
creation, editing and removal, Discord routing, GTW and swing-board saves,
exact identity matching, last-source protection, whole-config preservation
and revision feedback using synthetic authentication and intercepted PUTs.
The landing's
finite chart/walkthrough playback, pause/replay and offscreen suspension were
also checked. These are synthetic acceptance tests, not unattended-run evidence.

## References

- [Reviewed backend](https://github.com/absolutepraya/bursawatch/tree/25079b3465a97de132ed977ffec3ce3a488a867a/service-bursawatch-control)
- [Latest reviewed backend main](https://github.com/absolutepraya/bursawatch/tree/f426e24f447961d1371638735ccc6e3a060ef43e/service-bursawatch-control)
- [Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys)
- [Email/password sign-in](https://supabase.com/docs/reference/javascript/auth-signinwithpassword)

`WEB_API_HANDOFF.md` and the legacy sections of `INTEGRATION.md` describe an
earlier proposed consumer contract, not the current operator API.
