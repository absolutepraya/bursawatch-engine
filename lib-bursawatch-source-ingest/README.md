# Source ingest handoff

`bin/source_ingest.py` provides an endpoint-local future-only cursor and the
Task 3 durable source inbox handoff contract. It is used only by the
unscheduled Task 5 platform adapters. A source event is staged in a private
spool before inbox acceptance; the cursor advances only after the receipt.
An empty first poll persists an initialized cursor, so its first later event
is accepted. Each staged event also has a durable position intent, allowing
the same event to be retried if acceptance succeeded before cursor persistence.
Freshness follows the provider page anchor or an adapter supplied arrival
position; `published_at` remains event data only. A reported truncated page
without its prior anchor blocks advancement. Ordered, nontruncated pages and
truncated pages that retain their prior anchor can be drained in 20-event
batches. Each acknowledged event advances the cursor; a contiguous page does
not advance `scanned_through` past unaccepted events in a partial batch. An
unavailable inbox leaves the request staged. Platform adapters may attach
already uploaded Source Media Owner references through `media_refs`; this
provider-agnostic library validates their UUID, digest, kind, MIME type,
filename, object size, and event aggregate limits before staging. The durable
handoff spool preserves refs for retries. `media_required` with no valid refs
stores only the adapter's bounded safe text and identity in a private
`blocked-media.json` and holds the cursor. This library never fetches media,
receives bytes, or calls Supabase.

`select_endpoints` validates enabled verified effective catalog rows against
each adapter's independently reviewed source and publisher binding. One
endpoint's fetch or handoff failure returns a bounded status code and does
not stop another endpoint. The library never claims pipeline work, handles
Discord, or reads production state by itself.

`legacy_cursor_seed.plan_seed` provides preview-first migration for
package-owned adapters. Apply requires the unchanged preview, the explicit
`apply=True` function argument, and `BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY=1`; it refuses
initialized cursors or pending handoffs. The opt-in is unset during ordinary
work. Provenance binds the legacy file SHA-256, endpoint identity, and catalog
revision. Platform adapters remain responsible for proving their legacy
boundary mapping and reconciling pending domain work.
