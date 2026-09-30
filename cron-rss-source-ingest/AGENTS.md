# RSS source ingest

This package supplements the repository `AGENTS.md`. It is the active,
agent-backed Stockbit RSS source adapter. The read-only production snapshot at
2026-09-30 23:27 WIB recorded the existing Hermes job `cron-stockbit-snips`
active every 15 minutes. That job runs the deployed wrapper and is the sole
scheduled path for this reader. Refresh the snapshot before relying on these
scheduler facts. Read `SKILL.md` before changing intake.

The only supported feeds are the four system-owned `config.FEEDS` Stockbit
lanes. The adapter requires the existing Stockbit watcher's validated live
configuration revision and exact catalog agreement for enabled lanes. It
cannot accept an arbitrary RSS URL, new lane, or stale watcher config.

The RSS runner is the live source reader and owns endpoint polling, conditional
validators, source cursors, and inbox acceptance. The Stockbit domain owner
retains its article queue, frozen settings, agent wake, rendering, routes,
Delivery Owner handoff, and heartbeat. The RSS runner claims only
`stockbit_snips` work and submits text-only articles through that owner. The
owner binds the validated live configuration snapshot included when the
source event was accepted. A retry with the same effect is idempotent; a
legacy article collision or mismatched revision fails closed. The runner
claims at most one Stockbit agent item per run and emits the existing bounded
payload. Do not re-enable a legacy RSS poller beside this active reader or
reuse and rewrite live cursors or article state. A later intake revision
mismatch does not prevent already accepted work from settling against its
frozen snapshot.

## Catalog revision compatibility

Each cursor's `legacy_seed.catalog_revision` is immutable provenance for the
original boundary. All four seeds must share one origin revision and one
legacy-state digest. The source reader's `catalog-revision.json` marker may
advance beyond that origin only when every adjacent RSS transition journal
from the origin through the marker is present, private, complete, and bound to
the current complete enabled Stockbit projection and watcher-config revision.
When the marker equals the seed origin, no transition journal is allowed. A
direct marker edit, missing or extra journal, incomplete edge, changed
projection, or changed watcher-config revision blocks new intake. It does not
discard work already accepted by the inbox or Stockbit owner.

`bin/compatible_catalog_transition.py` previews or applies exactly one
adjacent edge. It takes `--prior-catalog`, `--target-catalog`, `--state-root`,
and `--plan-file`; it loads and validates the current Stockbit watcher config
for each action. Refresh both effective catalog snapshots before each edge.
Use a new private plan file outside the RSS state root for every preview:

```bash
python bin/compatible_catalog_transition.py preview \
  --prior-catalog <private-prior-catalog.json> \
  --target-catalog <private-target-catalog.json> \
  --state-root "$HOME/.hermes/state/bursawatch-rss-source-ingest" \
  --plan-file <private-plan-directory>/rss-4-to-5.json
```

The plan file is mode `0600`, its parent directory must be private, and the
file must not already exist. Apply uses the same snapshots, state root, and
plan file with the explicit guard:

```bash
BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY=1 \
  python bin/compatible_catalog_transition.py apply \
  --prior-catalog <private-prior-catalog.json> \
  --target-catalog <private-target-catalog.json> \
  --state-root "$HOME/.hermes/state/bursawatch-rss-source-ingest" \
  --plan-file <private-plan-directory>/rss-4-to-5.json
```

Apply rechecks the snapshots, current config, seed origin, journal chain, and
source-state fingerprint. It can resume only from the exact plan after an
interruption. A successful edge changes only `catalog-revision.json` and
`catalog-transitions/<from>-to-<to>.json`; cursors, validators, seed records,
owner state, inbox work, receipts, and destinations remain byte-for-byte
unchanged. The command cannot prove scheduler quiescence. Before apply, pause
the existing source writer through the supported Hermes interface and prove
that no run is in flight. Do not trigger the job manually, replay or backfill
RSS, reset a cursor, or send a test post. Resume only through the approved
scheduler path after the complete chain is verified.

The adapter stores its own conditional HTTP validators per endpoint in
`http-validators.json`. A 304 is an empty poll and does not move the source
cursor. New response validators are saved only after successful endpoint
ingestion. `plan_legacy_cursor_seed` is preview-only: it needs a fresh non-304
page response of at most 20 ordered items. That page must contain the legacy
GUID exactly once at the same publication timestamp. It hashes the GUID into
the new anchor and records the bounded page digest and response validators.
Missing, duplicate, or mismatched boundaries stay blocked; never initialize
from the latest item.
The preview does not apply a cursor or migrate live state. Stockbit remains
text-only: thumbnail and enclosure URLs are optional feed metadata. The adapter
strips `media_url` from accepted events, sets `media_required` to `false`, and
uses no media refs. It never fetches media URLs, stores images, or provides
images to the article agent.

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
        {"guid": "provider-id", "published_at": "2026-09-28T08:00:00+00:00", "media_present": true}
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
array; it reports an empty poll and cannot prove a cursor boundary.
`media_present` is a required boolean hint that a thumbnail or enclosure may
exist. It is ignored for readiness and cursor planning. Actual media URLs never
belong in this identity-only bundle or preflight report.

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
The handoff cannot apply a 304 because it has no boundary page. Media metadata
does not block a 200 page and is not stored or fetched. The receipt covers each
input file, page digest, config revision, frozen article revision counts, and
both validator pairs without source text.

`bin/runner.py --verify-synthetic` and the release wrapper's
`BURSAWATCH_RELEASE_NO_POST=1` path use fixed in-memory data only. They do not
fetch feeds, read `.env` or token files, access either owner state, or send
messages. Runtime heartbeats use the existing Stockbit heartbeat operation
through the shared Delivery Owner and contain counts only.
Before polling, the production runner requires the state marker to match the
effective Source Catalog and the watcher marker to match the validated live
Stockbit config. It accepts four reviewed seeds with one immutable origin
revision only when the complete adjacent journal chain proves the current
RSS projection and watcher-config revision. It never bootstraps from the
latest page item. Every live page is checked against the preflight
timestamp/GUID ordering. If the cursor is absent from an untruncated page and
an item ties its boundary, that lane stays blocked until ordering can be
proven.

Run `../../../.venv/bin/python -m pytest -q tests` in this worktree. Tests
use fake feed pages, temporary state, and no Discord or source network calls.
