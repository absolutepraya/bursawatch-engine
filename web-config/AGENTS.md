# Bursawatch web application

Read root `AGENTS.md` and this package's `DESIGN.md` before changing the app.
This independent Next.js package owns the user workspace and configuration
dashboard. The public website lives in sibling `../web-landing/`. Both are
reviewed in this repository; the backend still owns runtime state and delivery.
Use the canonical `Bursawatch` spelling. Preserve the approved Signal Fold
mark, seven-destination navigation, readable dark palette and concise copy.

## Integration boundary

`/workspace` is the private shared-operator application. Supabase Auth supplies
the user's token; same-origin `/api/control` forwards only allowlisted reads and
config/schedule/avatar PUTs and explicit avatar-refresh POSTs to the configured HTTPS API. That backend verifies identity
and admin authorization on every request. No public signup, machine/admin token,
direct SQL, second scheduler or browser role flag may bypass that boundary.
See `docs/CONTROL_PLANE.md` for the reviewed handoff and remaining live checks.

The live sidebar and mobile bottom navigation share Overview, Sources,
Workflows, Jobs, History, Published and Account, in that order. Sources reads the authenticated
Source Catalog API and shows Securities, Institutions, and People & Org. The
engine owns supported securities, curated institutions, registered endpoints,
capabilities and compatibility. People & Org identities and platform endpoints
are revisioned admin configuration; new endpoints remain pending verification
and are not effective subscriptions. Show each registered endpoint's
identity-verification state beside its address, separate from subscription
state. The catalog read includes backend-derived
`can_edit`; show mutation controls only when it is true. A successful PUT must
be followed by a confirmed catalog and effective read before success feedback.
If that read fails, preserve and lock the draft until an explicit reload. Display publisher defaults, endpoint
overrides and the resolved status separately. Do not infer identity from a
display name or internal ID. Public curated images remain static assets until
an object-storage owner and upload policy are approved. No browser-local source
preferences count as saved catalog records. Preserve all eight watcher editors and their input, processing and output
summaries. WhatsApp requires configuration version 2 and explicit observe/forward
modes; the other seven editors require version 1. Stockbit's v1 editor exposes
only four fixed feed switches, two distinct Discord route IDs and an optional
800-code-point additive instruction. RSS URLs, the heartbeat, credentials,
parser behavior and agent rules remain system-owned. Mode changes must not silently
discard routing or processing settings. Source profiles load from the separate
metadata endpoint only on request, without blocking the configuration editor.
Admins can save auto/manual avatar settings and explicitly request refresh.
Refresh acknowledgement is not completion; reload metadata to inspect the result.
Validate public HTTPS image URLs and strip raw refresh errors; use initials on
image failure. Keep curated catalog assets distinct from engine profile metadata.
It has no custom-workflow creation, personal brokerage
preferences or outbound WhatsApp/Telegram API; do not invent config fields.

Admin forms fetch current configuration on demand. Preserve unknown keys but
never embed real config, destinations, sessions or runtime state in public
bundles, fixtures, logs or snapshots. Tests use synthetic values. No silent
retry of writes: ambiguous saves and stale drafts require a fresh read.
Preflight revision checking is best effort, not an atomic backend lock.
Global schedule controls live in Jobs; workflow detail retains related schedule
controls. The old Schedules URL redirects to Jobs. Configuration and schedule
saves use separate revisions and actions. Saved schedules remain pending until
matching reconciliation is observed. Fixed jobs and viewer sessions have no
save control. Job `can_edit` is backend-derived and never inferred from browser
claims. Jobs and Published read only their current-view inventory or publication
records; Published filters are sent to the authenticated API before paging.
Do not trigger a real run or delivery in smoke tests.

Load only the current view's records: Sources reads the source catalog, Jobs
reads components, jobs and observations, workflow lists read watchers, History
lists read runs, and Account makes no control reads. Published reads its
filtered forward-only publication page and coverage. Selected
workflow configuration opens after the catalog and loads only its jobs; only X
also loads source-poll run status. Do not show a failed jobs read as an empty
schedule list.
Run timelines request events directly instead of waiting for unrelated watcher
histories. Reuse existing run metadata only within the current signed-in component;
do not add a persistent private-record cache.
Keep detail reads bounded to six concurrent requests, cancel obsolete reads,
and retain the whole-request 15-second read / 25-second save deadlines.
Long-wait diagnostics may expose safe stage/status/error summaries, never raw
provider errors, configuration or tokens. Authentication failure clears records.
Event diagnostics are server-projected by event type: bounded source IDs, validated
counts and execution flags only. Missing counts stay absent, never become zero.
Run totals do not prove a particular post was delivered; dry-run counts can be
simulated. Never forward arbitrary event attributes or raw provider errors.

The allowlisted `/workspace` URLs pre-render only the public opening shell and
validated public Supabase settings. Protected records never enter that HTML or
the CDN cache; `/api/control` remains authenticated and `no-store`. Public Auth
setting changes require a fresh build. Deploy web functions in Singapore (`sin1`).
Keep sample-only CSS under `/app`; shared toast styling lives with ToastProvider.

X sources added in the editor start paused. Saving does not establish that a
source poll consumed the revision or that Discord received a post. The first
successful nonempty poll initializes an account without forwarding its existing
posts. Only the reviewed scheduled source-job identities count as polling
evidence; queue and agent-submission runs do not. Preserve existing settings
when applying new-source defaults. See `docs/X_DELIVERY_TROUBLESHOOTING.md`.
Do not add a Sectors key or consume paid data credits for stock research; the
reviewed backend has no reusable Sectors research API.

`/app` retains sample records and browser-local preferences. Its connection
forms and custom workflows cannot alter the live backend or send messages.
Do not translate those consumer preferences into runtime config automatically.
The backend owns all scheduler implementations and the shared database.
It grants shared viewer/admin roles, not tenant-isolated personal ownership.
Do not expose this operator workspace as a general consumer service.
Tests use a pinned allowlisted public source fixture; do not read backend
configuration or require backend services to build or test.

## Validation and review

Run `npm ci` then `npm run check` in this package and validate `web-landing`
before the PR handoff. Add behavioral tests for changed validation,
storage, source identity and interactions. Check keyboard access, toast
feedback, 375px layouts, reduced motion and enlarged text for UI changes.
Build output is `.next-build`, separate from the development `.next` tree.
Never delete a build directory while its server is running.

Do not commit `.env*` (except reviewed `.env.example`), `.vercel`, local preferences, databases, `node_modules`,
build output or review screenshots. Publishing a feature branch is not
deployment approval. Retain the feature branch for review.
