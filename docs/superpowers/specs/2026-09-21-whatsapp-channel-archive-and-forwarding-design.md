# WhatsApp Channel archive and specialized forwarding design

## Status and intent

This is the reviewed design for a specialized WhatsApp Channel watcher that
retains BRI Danareksa Sekuritas, INS, and Samuel Sekuritas Indonesia. It must
preserve raw Channel evidence for later format review while making BRI the
first deliberately enabled forwarding profile. It must not create a second
WhatsApp session, backfill or replay historical posts to Discord, expose raw
Channel data to the control plane, Git, dotfiles, or Discord, or change live
VPS state without a separately approved release.

The existing bridge cannot reliably retrieve a complete 30-day upstream
history. BRI's retained source sample is research-only and incomplete. INS and
Samuel begin collecting a future evidence corpus after their approved follow
operation, rather than treating a failed historical lookup as a backfill.

## Source identities and profile lifecycle

| Profile | Stable Channel JID | Public URL | Initial lifecycle |
| --- | --- | --- | --- |
| `bri-danareksa-sekuritas` | `120363419226413141@newsletter` | `https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c` | Forward after the approved cutover and validation |
| `ins` | `120363405187024421@newsletter` | `https://whatsapp.com/channel/0029Vb6qi96ISTkJcDn4op2z` | Observe and archive only |
| `samuel-sekuritas-indonesia` | `120363319274271353@newsletter` | `https://whatsapp.com/channel/0029VagNdGpFMqrXKEcdBb2U` | Observe and archive only |

A **Channel Profile** binds one stable Channel identity to its source display
name, lifecycle, archive namespace, cursor, source-specific instructions,
routes, and fixtures. The configuration schema moves to version 2 and adds a
required `mode`:

- `observe` follows and archives source events but never creates a watcher
  outbox item, wakes the LLM, or posts to Discord. It has no Discord route or
  presentation requirements.
- `forward` follows and archives source events, then may create a routable
  item after the archive invariant and forward cursor are satisfied. It needs
  reviewed routes and presentation configuration.
- `enabled: false` disables a profile completely. `enabled: true` is required
  for both `observe` and `forward` profiles to participate in subscription
  management.

The static fallback configuration, its control-plane baseline, and the
control-plane validator copy must carry the same schema and three identities.
The live control-plane snapshot remains authoritative whenever its runtime
settings are configured. The bridge's deployed subscription registry must
contain the same enabled JIDs, so bridge reconnect behavior cannot silently
omit an observation profile.

## Canonical records and archive boundary

An **Archived Channel Record** is the immutable raw source representation of
one Channel post. It contains a schema version, event key, Channel JID,
message ID, publication and receipt timestamps, original text or caption,
extracted links, media descriptors, checksum, capture result, profile ID, and
the source configuration revision or `null` when only the bridge registry was
available. Its event key is the stable `channel_jid:message_id` identity.

The **Historical Analysis Archive** is a VPS-only filesystem store rooted at
`~/.hermes/state/whatsapp-channel-watch/archive/`. It uses one profile
namespace and one atomic mode-`0600` record file per event, organised by UTC
publication date. Directories use mode `0700`. Supported source media is
copied into an archive-owned content-addressed media directory and recorded
with SHA-256, byte count, MIME type, and capture status. The bridge must use
bounded, regular-file, no-symlink media staging. It must not turn an untrusted
media path into an archive path.

The bridge retains the existing normalized queue. It also writes the archive
at intake. The scanner treats an archive record as a forwarding precondition:
if bridge archival was interrupted, it retries the same idempotent archive
write from the queue and leaves the event non-routable until it succeeds. This
preserves source evidence without permitting an archive outage to cause a
silent delivery or an irreversible source loss.

Media capture is explicit. A missing or failed source-media download is
recorded as unavailable rather than fabricated. A BRI `#TechnicalReview`
requires exactly one successfully archived image before it can complete the
All Swing and Board handoff. Other supported events preserve their capture
status and delivery retries independently. For ordinary macro and issuer-news
forwarding, the text remains deliverable when an archive record reports
unavailable source media. The watcher records a terminal degraded media status,
skips only the unavailable source leg, and does not retry that known archive
miss forever. A Discord transport or upload failure remains retryable. A
technical review remains strict and cannot fall back to text-only delivery.

Archive records and copied media are retained for 365 days. Redacted fixtures
that describe a source layout or regression case are permanent, source-free,
and kept in tests. A prune command reports eligible records by default; its
destructive `--apply` form is never scheduled and requires a separate explicit
approval. The archive is neither the processing queue nor a control-plane
store, and historical records are permanently non-routable.

## Archive inspection helper

`bin/bursawatch-wa-channel-archive.sh` is the only watcher-owned operator
entry point for archive inspection. Its deployed counterpart is
`~/.hermes/scripts/bursawatch-wa-channel-archive.sh`. It supports read-only,
bounded query and export commands by profile, UTC time interval, archived
event identity, and computed layout signature. It can emit JSONL for a
machine review or Markdown for human inspection. It must require an explicit
output path for a raw export, set the output mode to `0600`, and print only
counts and safe metadata to stdout by default.

The helper provides `verify`, bounded `query`, explicit-path `export`, and
`prune` as a dry run unless `--apply` is supplied. It also provides a read-only
`cutover-plan` and a separately guarded `cutover-apply` for BRI: the apply path
requires both CLI `--apply` and `WHATSAPP_CHANNEL_WATCH_ALLOW_CUTOVER_APPLY=1`,
preserves the original queue and outbox, and writes a private state backup and
manifest. The inspection commands never follow a Channel, fetch upstream
history, advance a cursor, edit queue or watcher state, send Discord messages,
create an archive from arbitrary input, or invoke the Hermes scheduler.
`AGENTS.md` documents these commands, their runtime path, and the separate
live-release gate.

## Source post, derived News Item, and rendering

One WhatsApp **Source Post** always produces exactly one Archived Channel
Record. A forwarding profile may derive zero or more independently relevant
**News Items** from the Source Post. Each News Item has its own source-grounded
title, one or two paragraph Bahasa Indonesia summary, and one configured route.
The analysis protocol changes from one event-level title/summary/route to a
bounded ordered `items` array. An irrelevant result remains the minimal
event-level rejection. A deterministic `#TechnicalReview` produces exactly
one Swing item.

A Source Post with one shared editorial headline and one coherent macro or
market thesis remains one News Item even when it has many bullets. Its title
is the substantive news, not a category label already implied by its Discord
destination. For example, the BRI roundup headed `Indonesia Policy and Macro |
Menkeu baru, revisi HPM nikel efektif` renders with the title `Menkeu Baru dan
Revisi HPM Nikel`, not `Indonesia Policy & Macro: Menkeu Baru dan Revisi HPM
Nikel`. A post splits only when it contains clearly separate titled sections
or independent issuer-specific stories that retain their meaning alone.

Each derived News Item is rendered as one Discord text delivery of at most two
paragraphs. For a Source Post with more than one item, source media remains
in the archive and is not duplicated across ambiguous destinations. For a
single-item Source Post, including a shared-headline macro roundup with many
bullets, one supported source image or video is delivered once after its text
under the existing independent delivery checkpoints.

BRI nontechnical items retain the existing route policy:

- one clear direct IDX issuer thesis routes to `id_stocks_news`;
- broad market, sector, economy, infrastructure, or multi-issuer thesis routes
  to `macro_news`;
- chart-like vocabulary, a target, an indicator, support or resistance, or an
  image never selects Swing by itself.

BRI uses a source-specific automatic allowlist, derived from a read-only
review of 100 retained source posts. It forwards only material single-issuer
events or disclosures, factual macro or market developments including session
recaps, coherent multi-news macro roundups, and exact technical reviews.
Registration, rewards, product activation, competition, partner benefit, and
other calls to action are irrelevant. Analyst research, stock picks,
watchlists, outlooks, valuations, targets, and untagged technical or
price-level material are archive-review-only, even though they are
finance-related. A disclaimer is a removable source footer, never inclusion
evidence. This intentionally keeps the BRI watcher news-first rather than an
automated recommendation feed.

Only an exact leading case-sensitive `#TechnicalReview` token selects
`id_stocks_swing`. The retained BRI evidence has no safe alternate chart header
or `#Charge` format. This policy deliberately does not infer a technical route
from a chart-looking message.

## BRI Swing and Board handoff

A BRI `#TechnicalReview` with one successfully archived chart image is delivered
to chronological `#id-stocks-swing` first: its text, then its image. A typed
Board source event is submitted only after both All Swing delivery checkpoints
succeed. The handoff is
eligible only when the source and derived result establish exactly one IDX
ticker and one archived chart image. It uses the Board's `social` kind and
therefore creates only **Chart context**, never a Primary Plan. Multi-ticker,
or ambiguous technical reviews with their archived image remain All-only. A
missing-image technical review remains retryable with no partial delivery. The
Board never scrapes Discord and never reads watcher state.

The watcher stores the Board handoff intent and acknowledgement independently
of the Discord text and media checkpoints. It supplies the Board with the
All-Swing source content, a validated single ticker, source time and URL, and
the archive-owned image path. The Board remains the sole owner of forum,
SQLite, topic, and media mutations.

## BRI cutover and live operations

The current BRI queue and outbox predate this design. The deployment helper
must provide a read-only cutover plan that inventories records and state, then
an explicit `--apply` migration that archives each pre-cutover raw record,
marks the migration manifest with its coverage, and preserves the original
queue and state as a VPS-only rollback artefact. It must not deliver, replay,
delete, or rewrite an old outbox item.

After migration, the cutover advances BRI's forward cursor to the newest
captured pre-cutover event. Only a post first observed after that exact cursor
can become a Routable Event. The feature branch must pass focused and full
tests before a separate current-chat approval covers: deployment of changed
runtime code and configuration, checked wrapper synchronization, control-plane
revision creation, the specific `ensure --apply` Channel follows for INS and
Samuel, the BRI cutover `--apply`, and any Hermes job activation. This design
does not authorize any of those production mutations.

## Failure behavior and observability

Known unavailable source media on an ordinary news item is a terminal
text-only delivery with a sanitized media error and degraded heartbeat; the
watcher never fabricates a source asset or retries that same archive miss
forever. Discord transport and upload failures retain an error status and stay
retriable. Technical review image failures remain pending with no partial
delivery. None of these paths permit arbitrary filesystem access or a guessed
source record. Configuration snapshot failure remains fail-closed. The
existing standard heartbeat reports aggregate archival, observation, routing,
delivery, and Board-handoff counts plus sanitized failures. It never contains
raw source text, links, media paths, session information, or archive payloads.

No helper or test may contact the live bridge, pair WhatsApp, post to Discord,
or mutate production state. Isolated tests use explicit temporary queue,
archive, state, media, and Board paths with no-post controls.

## Test and documentation acceptance

Focused tests must cover configuration version 2 and mode validation,
profile-specific routing eligibility, atomic archive idempotency and collision
handling, file permissions, checksum verification, query/export bounds,
media capture status, retention dry runs, and no historic replay. They must
also cover zero, one, and many derived News Items; the shared-headline macro
roundup; exact technical routing; multi-ticker or missing-image All-only
behavior; and typed post-All Board handoff retries.

JavaScript sink tests must cover archive writes and media staging boundaries.
Python tests must cover scanner archive gating, source-to-item validation,
per-item checkpoints, cutover planning without mutation, and archive helper
behavior. `bash scripts/test-all` remains the repository-wide gate.

The final source change updates `cron-wa-channel-watch/AGENTS.md` and its
`SKILL.md` with the profile lifecycle, archive contract, inspection helper,
derived-News-Item protocol, BRI technical image and Board boundaries, testing,
deployment, and explicit live approval requirements. The ADR records the
durable architecture while this specification captures its implementable
contract.

## 2026-10-01 missing source image decision

This decision supersedes the strict no-text fallback above for a BRI
`#TechnicalReview` whose source chart was not captured. Keep the immutable
archive's truthful `unavailable` result. Forward ordinary news text with
an unavailable-image note. For an exact `#TechnicalReview`, forward the
source-grounded All Swing text with `Source chart unavailable` when the
verified chart cannot be captured. Omit the image leg and chart-dependent
Swing Board context. Discord transport or upload failure remains retryable;
only a known source-capture miss takes this text-only path.

The current source adapter blocks missing archive bytes before the watcher
can apply its ordinary-news fallback. Implement the change across that
boundary while preserving event identity, cursor order, original publication
time, archive record, and stable delivery operations. A queued item may
arrive late after the fix. This decision is not yet implemented or deployed;
the incident review does not establish a WhatsApp anti-bot cause.
