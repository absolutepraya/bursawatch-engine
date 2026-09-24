# Stockbit Snips live control-plane configuration

## Status and intent

This design brings Stockbit Snips into the existing Bursawatch control plane
and the authenticated web-config workspace. It completes the current
configuration path across the eight scheduled watcher packages. The other
seven watchers already load versioned live configuration from Postgres and
have typed workspace editors. Stockbit is the remaining watcher whose
operator settings are still read from static code and environment variables.

The change must preserve the current four Stockbit RSS lanes, 15-minute
production cadence, Discord routing behavior, and local cursor, outbox, retry,
and delivery state. It must not backfill RSS history or modify the live Hermes
schedule as part of source implementation.

## Operator experience

The authenticated workspace adds Stockbit Snips to the existing watcher
configuration list. Its typed editor exposes:

- An enabled switch for each of the four existing RSS lanes: Stockbit
  Commentary, Unboxing, Unboxing IPO, and AI Reports Stockbit.
- The Discord channel ID for the fixed issuer-news route and the fixed
  macro-news route.
- One optional additive analysis instruction, limited to 800 characters.
- The interval and enabled state for the existing Stockbit schedule through
  the existing Schedules view. The displayed status distinguishes saved,
  pending, and applied revisions.

The source URL, lane identity, route keys, channel descriptions, agent
response schema, and system safety rules are not editable. The editor does not
accept a new RSS URL or an arbitrary route. Existing X, Instagram, and
WhatsApp editors continue to own user-managed account and channel membership.

Saving watcher settings creates a complete versioned config revision in the
control plane. Saving a schedule creates a desired schedule revision. A
schedule change is effective only after the trusted scheduler reconciler
reports the same revision as applied.

## Configuration contract

The v1 Stockbit config is a complete object with this shape:

    {
      "version": 1,
      "feeds": [
        {"id": "stockbit_commentary", "enabled": true},
        {"id": "unboxing", "enabled": true},
        {"id": "unboxing_ipo", "enabled": true},
        {"id": "ai_reports_stockbit", "enabled": true}
      ],
      "destinations": {
        "id_stocks_news_channel_id": "<Discord snowflake>",
        "macro_news_channel_id": "<Discord snowflake>"
      },
      "additional_prompt_instruction": ""
    }

The four feed IDs and the two route names are closed enums. Feed IDs must be
unique and all four must be present. Destination IDs are required Discord
snowflake strings and must differ. The instruction is normalized and capped
at 800 characters. Unknown fields, missing lanes or routes, invalid IDs, and
unsupported versions are rejected by both the backend validator and the
watcher parser.

The initial baseline keeps all four lanes enabled. Its destination IDs must
match the effective production environment values verified immediately before
the first live-config cutover. Do not assume repository defaults equal the
current VPS environment.

The fixed agent instruction remains code-owned and is sent separately from
the operator instruction. The operator text may guide selection or emphasis
only within the existing source-only, no-browsing, factual-language, route,
and closed-output-schema rules. It cannot override those rules. The output
schema and deterministic submission validator do not change.

## Schedule contract

The control-plane job ID and Hermes runtime key are both
bursawatch-stockbit-snips. It is an interval job in Asia/Jakarta, enabled at
the existing 15-minute cadence for its source baseline. The proposed operator
range is 5 to 60 minutes. The lower bound prevents unusually frequent polling
of all four RSS endpoints; the upper bound keeps the watcher useful without
creating an unbounded interval.

Registering this job in the database is a mirror of the existing live job. It
must not add, remove, pause, enable, or reschedule a Hermes entry. Before
registration, read-only production inspection must confirm the existing
runtime key, enabled state, cadence, and timezone. A mismatch blocks cutover
until separately reviewed.

## Runtime behavior

Each scheduled invocation fetches one validated live config snapshot and
records its revision. There is no static-config fallback in live mode. A
missing, unavailable, wrong-watcher, or invalid snapshot prevents source
polling and dispatch of articles that do not yet have a frozen config
snapshot. The failure is reported as a degraded or failed run, local state is
left intact, and the fixed system heartbeat is still attempted. Work already
bound to a frozen snapshot can continue: completed agent submissions and
pending deliveries use their stored prompt and destination values. Legacy
pending items without a snapshot wait until a valid live config is available
to bind them.

Feed toggles affect source intake only:

- A disabled lane is not fetched and creates no new article work.
- Its lane record, cursor, validators, and prior articles remain in local
  state.
- When a lane is re-enabled, its first successful unconditional fetch moves
  its cursor to the current newest item without queueing the paused interval.
  This preserves the package's future-only behavior.
- Articles already queued before a lane was disabled continue through agent
  analysis, delivery, and retries.

When an article is first dispatched to the agent, its local state record
captures the config revision, additive instruction, and two destination IDs
used for that dispatch. submit-analysis and any delivery retries use this
frozen event snapshot, even if the operator saves a newer config meanwhile.
Queued articles that have not yet been dispatched use the latest config when
they are dispatched. This makes each asynchronous article flow deterministic
without making a setting change rewrite queued work.

Upgrade local Stockbit state from version 1 without resetting it. Keep all
four lane records and every existing article, lease, delivery, and retry
field. Add a last-observed enabled value for each lane and an optional frozen
config snapshot per article. Existing records without a snapshot bind to the
first valid live config used after upgrade. A state migration must reject
unknown or malformed data rather than silently replacing it with a fresh
state file.

Scheduled runs and agent-submission runs report the config revision and
scheduler job ID through the shared control-plane runtime library. Structured
events contain lifecycle, lane counts, delivery counts, and sanitized errors,
not article contents, source text, operator instructions, credentials, or
local paths. The required #hermes heartbeat remains fixed system behavior and
is attempted even when live config loading fails.

## Source and service changes

The implementation adds:

1. A self-contained Stockbit config parser under the control-plane validator
   source bundle, its validator registry entry, and the v1 baseline JSON.
2. A forward-only migration after migration 010. It inserts the Stockbit
   watcher catalog record, interval job metadata, and the initial desired
   schedule revision. The migration is marked manual because it registers a
   schedule. It does not edit the Hermes registry.
3. A live config loader in the Stockbit package that validates the shared
   client snapshot, applies the config once per invocation, and reports the
   snapshot revision. The Stockbit release-manifest runtime unit depends on
   lib-bursawatch-control.
4. Runtime handling for lane pause/resume, frozen article config snapshots,
   agent instructions, destination selection, and control-plane run events.
5. A Stockbit typed editor, workspace watcher registration, schedule
   presentation, and updates to the control-plane and configuration coverage
   documentation.
6. Development docs that distinguish the DB-owned operator settings from the
   system-owned sources, runtime state, heartbeat, and agent contract.

The migration must be additive and must not edit any applied migration.
Baseline seeding must continue to seed only an absent config revision and must
not replace dashboard-authored state.

## Production cutover boundaries

This design does not authorize a production write. A later release review
must inspect the exact live Stockbit job and effective route IDs before
cutover, show the migration and package diffs, and preserve the existing
production state path.

The reviewed release sequence should:

1. Confirm the live job is already enabled every 15 minutes in Asia/Jakarta,
   and record the effective two route IDs without exposing credentials.
2. Apply the reviewed manual control-plane migration and seed the initial
   config only if no dashboard-authored config exists.
3. Point the dedicated API environment variable
   CONTROL_PLANE_STOCKBIT_CONFIG_VALIDATOR_DIR at the deployed
   validator-sources/bursawatch-stockbit-snips directory. This separate VPS
   config edit and any required API restart need their own reviewed approval.
4. Confirm the database watcher, config revision, schedule revision, and
   reconciler view agree with the existing Hermes job before deploying the
   Stockbit runtime that requires live config.
5. Deploy the Stockbit runtime and web app through their separate release
   paths. Do not change the Hermes schedule during this cutover.
6. Verify a later unattended run reports the expected config and applied
   schedule revisions, and separately inspect source, processing, delivery,
   and heartbeat evidence. A healthy service or an ok run alone is not
   delivery proof.

No database migration, baseline seed, VPS file write, scheduler action,
manual production run, Discord test post, or web deployment is part of the
local implementation work.

## Out of scope

- Adding or removing Stockbit RSS endpoints, changing feed URLs, or allowing
  arbitrary user-provided fetch targets.
- Editing the mandatory heartbeat destination or watcher identity.
- Making Discord credentials, control-plane credentials, request timeout,
  state paths, file locks, cursor rules, dedupe behavior, retry policy, parser
  behavior, or agent output schema operator settings.
- Resetting or relocating local production state, replaying or backfilling
  articles, or changing an already queued article's frozen settings.
- Changing the seven existing watcher schemas or schedules as part of this
  Stockbit addition.

## Acceptance criteria for implementation

- The backend rejects malformed, incomplete, duplicate, unknown, or
  out-of-range Stockbit config and schedule values.
- The dashboard can load, edit, validate, save, and reload the complete
  Stockbit config with the existing stale-draft preflight behavior. This is
  not an atomic concurrent-edit guarantee. A viewer cannot read or write
  admin config.
- The workspace lists all eight live-configured watcher packages and shows
  the Stockbit schedule as pending or applied from backend reconciliation
  data.
- Runtime tests prove one live snapshot per invocation, no static fallback,
  correct revision reporting, and safe failure when the control plane is
  unavailable.
- Runtime tests prove lane pause/resume does not drop lane state or backfill
  paused items, while already queued work continues.
- Runtime tests prove an article uses the prompt and route IDs frozen when it
  was dispatched, including agent submission and delivery retries after a
  later config revision.
- The state upgrade preserves all version 1 cursors, ETags, article phases,
  leases, rendered content, and delivery retry fields.
- Isolated no-post verification uses temporary state and never calls Discord.
- Existing watcher tests and repository validation remain green; no test
  claims production delivery or scheduler application.
