# RSS source ingest pilot

This package supplements the repository `AGENTS.md`. It is an unscheduled,
agent-backed Task 5 source adapter. Read `SKILL.md` before changing intake.

The only supported feeds are the four system-owned `config.FEEDS` Stockbit
lanes. The adapter requires the existing Stockbit watcher's validated live
configuration revision and exact catalog agreement for enabled lanes. It
cannot accept an arbitrary RSS URL, new lane, or stale watcher config.

The current Stockbit watcher remains the live source reader and owner of its
versioned feed state, article queue, frozen settings, agent wake, rendering,
routes, Delivery Owner handoff, and heartbeat. The RSS runner claims only
`stockbit_snips` work and submits text-only articles through the existing
Stockbit article owner. The owner binds the validated live configuration
snapshot included when the source event was accepted. A retry with the same
effect is idempotent; a legacy article collision or mismatched revision fails
closed. The runner claims at most one Stockbit agent item per run and emits the
existing bounded payload. This pilot has no production job. Do not reuse or
rewrite live cursors or article state; a future cutover needs an exact queue
and receipt inventory. A later intake revision mismatch does not prevent
already accepted work from settling against its frozen snapshot. Never run the
new reader beside the live source job.

The adapter stores its own conditional HTTP validators per endpoint in
`http-validators.json`. A 304 is an empty poll and does not move the source
cursor. New response validators are saved only after successful endpoint
ingestion. `plan_legacy_cursor_seed` is preview-only: it needs a fresh non-304
page response of at most 20 ordered items. That page must contain the legacy
GUID exactly once at the same publication timestamp. It hashes the GUID into
the new anchor and records the bounded page digest and response validators.
Missing, duplicate, or mismatched boundaries stay blocked; never initialize
from the latest item.
The preview does not apply a cursor or migrate live state.
Articles with a parsed media URL remain fail-closed in this pilot. The feed
parser exposes provider-controlled HTTP(S) URLs, and this package has no
reviewed host allowlist or bounded, redirect-safe media downloader. Do not
fetch those URLs or submit them as accepted source-event payloads.

`../../../.venv/bin/python bin/preflight.py <bundle-directory>` is a
deterministic, read-only four-lane preflight. It reads only
`stockbit-state.json` and `rss-pages.json` from the operator-supplied directory.
It makes no requests, has no apply option, prints JSON to stdout, and does not
create the proposed state root. The owner snapshot must be version 1 or 2 and
have exactly the four configured `feeds` keys. Each feed entry must include a
legacy cursor and both validators:

```json
{
  "version": 2,
  "feeds": {
    "stockbit_commentary": {
      "cursor": {"published_at": "2026-09-28T08:00:00+00:00", "guid": "legacy-provider-id"},
      "etag": null,
      "last_modified": "Mon, 28 Sep 2026 08:00:00 GMT"
    }
  }
}
```

Repeat that feed entry shape for all four lanes. Each cursor timestamp must be
timezone-aware ISO text and its GUID must be a nonempty string. Validators are
strings or `null`. Other owner fields are not interpreted or emitted, though
the legacy snapshot digest covers the complete file. The page bundle format is:

```json
{
  "version": 1,
  "catalog_revision": 4,
  "lanes": {
    "stockbit_commentary": {
      "status": 200,
      "etag": null,
      "last_modified": null,
      "items": [
        {"guid": "provider-id", "published_at": "2026-09-28T08:00:00+00:00", "media_present": false}
      ]
    }
  }
}
```

`lanes` must contain exactly `stockbit_commentary`, `unboxing`,
`unboxing_ipo`, and `ai_reports_stockbit`. Each page item has only `guid`,
timezone-aware ISO `published_at`, and boolean `media_present`; at most 20 items
are allowed and the page must be nonincreasing by `(published_at, GUID)` in
newest-first order. Each page status must be 200 or 304. Each page record
supplies both `etag` and `last_modified`, as strings or `null`. Reports preserve
these as `http_validators` and separately preserve the owner snapshot values as
`legacy_http_validators`, including `null`. A 304 must have an empty `items`
array; it reports an empty poll and cannot prove a cursor boundary. Any page
item with `media_present: true` blocks that lane.

`feed_page_sha256` covers only the ordered page identity pairs
`(published_at.isoformat(), guid)`, serialized as compact UTF-8 JSON and hashed
with SHA-256. It excludes source text, URLs, media flags, and HTTP validators.
Reports contain no source text or raw page GUIDs. Readiness requires previews
for all four lanes with no missing or extra lane keys.

The separate `bin/handoff.py` is the gated state handoff for a cutover. It
requires a four-file operator snapshot bundle:

- `stockbit-state.json`: the complete version 1 or 2 Stockbit owner state.
- `rss-pages.json`: the four page responses used by `preflight.py`, with the
  active Source Catalog revision.
- `delivery-receipts.json`: version 1 and an exact `receipts` array. Each item
  contains only `operation_key_sha256`, `digest`, `status`, and `receipt`, where
  `receipt` is `{ "channel_id": "<snowflake>", "message_id": "<snowflake>" }`
  or `null`. The operation key is SHA-256 hashed; no rendered message is copied.
- `migration-context.json`: exactly `version`, `snapshot_taken_at` (timezone
  aware ISO text, no older than 15 minutes at plan/apply), `watch_config_revision`,
  `source_catalog_revision`, `legacy_job_id`, `legacy_reader_paused`, and
  `legacy_inflight_runs`. The catalog revision must match `rss-pages.json`; the
  current legacy job id is `0c6b17e4c944`; the paused flag must be true and the
  in-flight count must be zero.

Keep the private bundle under
`~/backup/hermes/runtime-cutovers/<YYYY-MM-DD>/bursawatch-rss-source-ingest/`
for rollback and retain it for at least 30 days. Do not commit it or copy it to
dotfiles.

Plan with `bin/handoff.py --plan --bundle-dir <bundle> --state-root
<absolute-path>/bursawatch-rss-source-ingest`. A ready plan prints a digest and
the checksums for all four input files. It contains no article text or raw
GUIDs. Apply requires the same bundle and path, that digest, and both
`--apply` and `BURSAWATCH_RSS_HANDOFF_ALLOW_APPLY=1`. The apply creates only the
new RSS source state root through a staged sibling directory and atomic rename.
It refuses an existing target, any blocked lane, pending legacy article work,
an active agent lease, invalid or future frozen config revisions, or Delivery
Owner receipts that do not exactly match Stockbit's delivered records. It
does not update Stockbit owner state, Control Plane state, or schedules. The
snapshot context must attest that the legacy reader is paused and has no
in-flight run before planning or applying the state handoff.

The new cursor anchor is the SHA-256 hash of the exact legacy GUID. The cursor
records the boundary timestamp and legacy snapshot provenance. The lane-local
`http-validators.json` contains the page response ETag and Last-Modified,
including `null`; the cutover receipt also retains the old legacy validators.
The handoff cannot apply a 304 or a media-bearing page. The receipt covers each
input file, page digest, config revision, frozen article revision counts, and
both validator pairs without source text.

`bin/runner.py --verify-synthetic` and the release wrapper's
`BURSAWATCH_RELEASE_NO_POST=1` path use fixed in-memory data only. They do not
fetch feeds, read `.env` or token files, access either owner state, or send
messages. Runtime heartbeats use the existing Stockbit heartbeat operation
through the shared Delivery Owner and contain counts only.
The production runner refuses to poll unless the state root already contains
all four reviewed legacy seeds with matching catalog and watcher revisions; it
never bootstraps from the latest page item. Every live page is checked against
the preflight timestamp/GUID ordering. If the cursor is absent from an
untruncated page and an item ties its boundary timestamp, that lane stays
blocked until ordering can be proven.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use fake feed pages, temporary state, and no Discord or source network calls.
