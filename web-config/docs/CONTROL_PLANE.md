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

## Loading and failure feedback

The browser fetches only the current destination's data. Catalog-driven views
first check watcher membership; a direct run link reads the authorized event
endpoint without requesting unrelated watcher histories:

- Sources uses dated public previews and the watcher catalog for any settings
  links; the workflow list also reads only the catalog. Neither presents
  unloaded schedules or history as empty results.
- A selected workflow starts its admin configuration read after catalog
  membership is confirmed and loads only that workflow's jobs for its schedule
  controls. X also loads source-poll runs for its delivery checks; other editors
  do not fetch unrelated run histories.
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

The workspace begins with a skeleton for a full-page load, adds a spinner after
two seconds, and exposes elapsed time and request details after eight seconds.
Compact resource loaders name the actual operation. Reduced motion disables
the spinner animation. Partial failures retain successful results with safe
resource-specific reasons and recovery actions. Lost authentication discards
protected records; it must not leave the editor or false empty diagnostics
visible. Diagnostics never include raw provider errors, secrets or config.

## Implemented surface

The desktop sidebar and mobile bottom navigation expose the same five
destinations: Overview, Sources, Workflows, History and Account. They reuse
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
  bundled as defaults. Each selected workflow also shows its own jobs. Interval
  schedules use API bounds, the WIB timezone and pending/effective status;
  fixed jobs are read-only. Configuration and schedule saves have independent
  revisions and actions.
- History: recorded timestamps, config revisions, outcomes and event metadata.
  A server-side event-specific projection exposes bounded source IDs, validated
  counts and execution flags only. Raw messages and arbitrary attributes remain
  excluded. Missing counts are not zero; run totals and simulated dry-run counts
  cannot establish per-post/channel receipt. An `ok` run is not proof of message
  delivery or Sectors use.
- Account: current identity, copyable UUID for owner-managed access and sign-out.

The Sources page (`/workspace/sources`) reads the versioned Source Catalog and
effective subscription snapshot from the authenticated API. Securities lists
only engine-supported symbols; while that registry is empty, the page shows an
explicit empty state. Institutions are curated engine records with static 4:3
presentation art where available. People & Org combines seeded identities and
user-managed records. Admins can draft new identities, platform endpoints,
publisher defaults and compatible endpoint overrides, then save an optimistic
catalog revision. Newly added endpoints remain pending identity verification;
an enabled intent is not an effective subscription or delivery proof. The page
shows default, override, effective draft and saved effective values separately.
The fixed watcher editors, including Stockbit's four RSS lanes, remain independent.
There is no browser source cache, object-storage upload, direct database access,
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
delivery proof. The workflow's schedule section uses the generic API-provided job bounds,
desired revision and reconciler status. A saved interval or enabled change is
pending until that exact schedule revision is reported applied and effective.

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

Before deployment is declared complete:

1. Sign in with the owner's provided **Supabase Auth** account and verify real
   watcher/job/run reads; verify a viewer cannot read or change admin config.
2. Have the owner confirm an admin UUID and the intended shared audience.
3. With explicit approval for a specific safe change, save/read back a revision,
   observe matching schedule reconciliation and a later unattended run.
4. Record actual Track 02 evidence. Sample runs and mocked tests do not qualify.

No production write, message delivery or live authenticated session was tested
in this implementation pass. Do not use the database password as a login.

Verified locally on 22 September 2026 after workspace visual unification and loading improvements:
both production builds, formatting,
lint and types passed; 275 configuration-app unit tests and 24 landing tests
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
