# WhatsApp platform source boundary

Runtime identity reserved: `bursawatch-wa-source-ingest`. Entry point:
`bin/runner.py`. No Hermes job is registered. This release-metadata pilot
must not read the live queue while the existing source reader runs.

Each verified forwarding Channel has an endpoint-local future-only cursor and
private source handoff. The reader uses only the already durable bridge queue,
scans file metadata for a stable arrival cursor, and opens at most 500 new
files to collect at most 20 matching messages per endpoint. Initial polling
records the latest arrival without parsing retained history. Publication time
does not set freshness, so a late-arriving old message is eligible. The queue
files must remain immutable with their original modification time; a later
backdated or rewritten file needs reviewed reconciliation. The reader never
deletes from the bridge queue. The existing immutable archive remains
authoritative for raw media and history. For each media-bearing BRI item, the
adapter resolves the exact archive record, validates its identity and
checksum, and reads only captured archive objects within the Source Media
Owner's 8 MiB per-object and 25 MiB per-event bounds. It uploads those bytes
through `lib-bursawatch-source-media` before source event acceptance, with an
idempotency key derived from endpoint, provider event ID, and media index. The
accepted event contains only validated opaque media refs and ref IDs, never
media bytes or attachment URLs. The upload client uses
`BURSAWATCH_SOURCE_MEDIA_URL` and
`BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE`; if either setting, an archive
object, or valid Owner metadata is unavailable, the event stays blocked and
the cursor does not advance. The queue's disposable staging paths are never
read by this adapter. INS and Samuel are observe-only and are not subscribed
to pipeline work. BRI `swing_chart_context` work is left pending because no
reviewed pipeline owner can reproduce the current agent and image behavior.
