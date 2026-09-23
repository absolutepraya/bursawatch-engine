# X posts missing from Discord

Use the authenticated `/workspace/workflows` X editor. The separate `/app`
sample saves browser-local preferences and cannot configure the live watcher.
The web can inspect saved settings and recorded runs; it cannot verify Discord
receipt or an individual account's source cursor through the reviewed API.

## Check the saved source

1. Open the intended X account and confirm its handle/profile URL. Newly added
   sources start paused: enable **Watch this source**, choose eligible post
   types, and configure its Discord destination before saving.
2. Confirm that saving returned a new configuration revision. An enabled draft
   or a completed form is not a saved setting. After an uncertain save, reload
   current settings before trying again; do not blindly repeat the write.
3. Inspect the source-poll schedule. It must be enabled with matching applied
   reconciliation. The reviewed baseline is every ten minutes, but current
   saved and applied API records determine the actual cadence. Queue-worker
   activity does not establish that X was polled.
4. Compare the saved configuration revision with the latest recorded source
   run's `config_revision`. A saved revision does not change a run already in
   progress. A matching revision establishes that run's configuration version,
   not that a particular account was successfully fetched.

## Understand eligibility and delay

The first successful nonempty poll for a new account records a starting point
and queues zero existing posts. A tweet published before that initializing
poll is therefore not forwarded automatically. Enabling a source is not a
request to backfill its history.

Subsequent posts must pass the saved post-type and relevance settings. For
example, a reply does not become eligible because normal posts are enabled.
The stock-market relevance filter can exclude personal or test posts. A fetch
with no eligible new posts can complete successfully without sending anything.

When relevance filtering is off, title/summary generation alone does not authorize
an irrelevant verdict. It still requires the separate AI-processing step. With
content-based routing off, X's validator requires one Discord destination and
the scanner sends to that configured channel ID. The topic selector and custom
instructions do not select a Discord channel. Confirm that ID is the intended
`macro-news` channel; do not infer routing from its description or key alone.

Self-chain handling waits for connected posts to settle before processing.
New profiles created by this web editor default to five settle minutes;
existing profiles retain their saved value. Source-poll cadence, thread wait
and queue processing can all contribute to elapsed time. These are separate
stages, not a promise of delivery within a fixed number of minutes.

## Inspect the right runs

The X diagnostic panel recognizes source-poll evidence only for the X watcher
when `trigger` is `scheduled` and `scheduler_job_id` is one of:

- `bursawatch-x-account-watch-source`
- `x-post-source`

Queue-worker and `agent_submission` runs are not source polls. Inspect the
source run first for fetch failures; then inspect queue activity for processing
or delivery failures. A `source.fetch.completed` event by itself proves neither
that a new item was queued nor that Discord received a message. An `ok` run
also does not establish delivery.

A Queue run with only `run.started`, `delivery.drain.completed` and `run.completed`
does not prove collection or receipt. The queue-only path skips source fetching,
and the drain-completed event is emitted even when nothing was sent. The web
explains this beside the event and links known X queue runs to source diagnostics.
These semantics were rechecked at backend `2daa959c747b617140a8cceb01b7dc537a5554ff`.

History contains at most 50 recent runs per watcher. “Not in returned history”
means the available records do not establish a run, not that it never occurred.
The web proxy projects event type, phase, level and time plus a narrowly allowed
diagnostics object. Source-fetch events may show a validated source/profile ID;
completed fetches may also show items fetched/queued. Delivery drains may show
run-total delivery and analysis-queue counts, oldest eligible queue age and the
queue-only flag. Run-start events may show queue-only and dry-run flags. Missing
or invalid fields are omitted, not displayed as zero. The ID is the configured
profile ID, not necessarily its X handle. Raw provider errors, messages,
arbitrary attributes, URLs, tokens and configuration remain excluded.
The analysis queue includes pending, awaiting-agent and ready items; it does not
mean every item still needs analysis. Its age is measured from eligibility
(`ready_after`), not from post creation.

The reviewed backend telemetry cannot establish per-tweet delivery on its own.
Source-fetch events identify a profile and aggregate counts, but agent-submission
and delivery-drain counts do not contain the X post ID or Discord message ID.
An aggregate delivered count must not be attributed to a particular account;
dry-run counts are not actual delivery. To resolve one missing post, correlate
its exact URL/time with the source initialization and the owner's authorized
runtime delivery records, or inspect the intended Discord channel directly.

For `source.fetch.failed`, the workspace owner should check RSSHub/X access,
rate limits and source health. For delivery failures, the owner should inspect
the configured Discord destination and the runtime bot's permissions. Use the
owning backend's authorized diagnostics; do not copy credentials into the web
or add direct database access to investigate.

## When a source returns zero items

A completed fetch with recorded `items: 0` means that this source supplied no
normalized posts to the watcher before post eligibility or relevance filtering.
When `queued: 0` is also recorded, that fetch added no posts to the processing
queue. Changing relevance settings, Discord routing or waiting for the queue
worker does not explain or repair that empty fetch. Do not mistake a completed
request for successful collection of the account's posts.

The event does not identify why the source was empty. It does not prove an
account has no public posts, that RSSHub is globally unavailable, or that a
provider was rate-limited. A failed event for another source is not evidence of
failure for this source. Missing counters are unknown, never zero. Conversely,
nonempty fetches with zero queued items can reflect first-poll initialization
or no new eligible posts; these counters alone do not distinguish the cause.

Send the backend owner the configured source ID, run time and revision when
available, recorded fetched/queued counts, and the missing public post URL.
Ask them to inspect that exact source's configured provider, response and
normalization path using their authorized runtime diagnostics. They should
compare the effective saved account identity and source health without sharing
provider credentials or raw secret-bearing errors. A successful nonempty poll
may only initialize a new source, so it is not a promise to forward older posts.
Do not reset cursors, backfill, replay or change schedules as a speculative fix.

## When the workspace itself is slow

The loading UI begins with a skeleton, adds a spinner after two seconds and
shows request details after eight seconds. Read requests stop after 15 seconds;
save requests have a 25-second deadline. These browser deadlines include
session restoration and response decoding. They are not watcher polling
intervals.

Failed reads show safe resource-specific reasons and a recovery action. A
partial failure must not be interpreted as an empty schedule or absent run.
Expired authentication requires signing in again. Uncertain writes require a
fresh read before saving again; the app never retries writes automatically.

## Verification boundary

The behavior above is grounded in read-only review of backend source at
`96b83fdbca6e9383183d3ded5d42f23a8c73fc8a` and the web's configuration contract.
The affected live account, its deployed settings and Discord receipt have not
been verified. Web validation and synthetic tests do not establish successful
live collection or delivery. No runtime change, cursor reset, replay, backfill
or external message was performed for this web change.
