# Bursawatch control-plane client

This shared runtime library lets cron packages read a versioned control-plane
configuration snapshot without receiving database credentials. It is deployed
as `~/.agents/skills/lib-bursawatch-control/bin/`.

The client is intentionally standard-library-only so it can be added to the
existing watcher runtime without changing the shared Yahoo Finance tool
environment. Configuration request failure raises a sanitized control-plane
error. Callers must fail closed and must not silently fall back to static
configuration when live mode is enabled.

`ControlPlaneReporter` stores lifecycle and event requests in a bounded,
0600 local spool under `~/.hermes/state/bursawatch-control/spool/<watcher-id>`
and retries them idempotently. The spool is a transport buffer, not the log
system of record: the control-plane Postgres database stores structured run and
event records, while local wrapper stdout files remain short-lived diagnostic
copies during migration.

## Source-event handoff

`bin/source_event_client.py` provides `SourceEventClient` and `SourceEventHandoff`.
The adapter stages a bounded event in the private local spool before sending. The
handoff removes that record only after a validated durable acceptance receipt. The
client computes the expected event key from the staged provider identity and refuses
an unrelated or malformed receipt, leaving the handoff file in place. The
adapter must persist its own cursor only after the receipt and must retry pending
handoff records on restart. If it crashes after acceptance and before cursor save,
provider rereads are safe because the server returns the original receipt. An HTTP
error, invalid receipt, or full spool must stop cursor advancement. Platform adapters
are introduced in later tasks; this library alone does not change any live cursor.
Corrections and tombstones use `stage_revision` with a stable provider revision ID.
A 409 while an older work item is leased leaves that staged revision pending for retry;
the adapter must retain its source cursor until a revision receipt is validated.

Claims require explicit supported pipeline IDs. Claimed work includes a stable
`effect_key` and event version. Domain handlers must send both to their owner to
deduplicate effects and reject stale versions across retries, lease expiry, and
audited replay.

## Published Feed projection

`bin/publication_client.py` provides `PublicationClient.submit(snapshot)` and
`checkpoint(comparison)` for a domain owner's already-confirmed publication.
The client sends the owner-scoped bearer token to the Control Plane's
`POST /v1/publications` and `POST /v1/publications/checkpoints` endpoints. Keep
the token in the owner's existing private runtime environment. The client has
no Discord dependency and cannot create, edit, or retry delivery operations.

The domain owner owns its durable projection intent and exact output snapshot.
At the boundary where the Discord Delivery Owner confirms every required leg,
persist the snapshot and a pending projection marker with the owner's receipt
state. Include the stable owner key and version, `required_operation_keys`, and
each leg's operation key, operation digest, receipt operation ID, confirmed
receipt, destination, exact rendered text, and safe attachment metadata. Do not
build an intent from a run summary, and do not create one while any required
leg is pending or failed. When recovering a crash after a delivery receipt,
reconcile the existing receipt and persist or recover the same intent; never
submit another Discord operation to make projection succeed.

Keep a pending snapshot until `submit` returns a valid durable acknowledgment
containing its publication ID, version, and digest. Network errors, timeouts,
HTTP 408/425/429, and server errors retry only the identical serialized
snapshot. A 409 is an immutable identity or version conflict and is surfaced
without retry. Other client errors also stop the attempt. The owner may retry a
later drain using the retained snapshot, with the same key, version, and
digest. The Control Plane acknowledgment is proof of read-model acceptance,
not proof of a new delivery.

Each owner also persists its own confirmed and accepted boundaries. Advance its
accepted boundary only across a contiguous sequence of acknowledged intents;
an unresolved earlier intent keeps later work from making the boundary appear
complete. Send bounded comparisons with the owner's comparison time, confirmed
boundary, accepted boundary, and outstanding count using `checkpoint`. Keep
these ledgers owner-specific. A missing or stale checkpoint means coverage is
unknown, not an empty complete feed. The client does not create a shared
cross-owner state file.

## Immutable source evidence client

`bin/source_evidence_client.py` provides the standard-library-only
`SourceEvidenceClient(base_url, token, timeout=5.0, opener=urlopen)` with a dedicated
source-reader token. It has no environment loading or import-time network/state
access, and no intake, work claim, scheduler, publication or delivery methods.

`capture_window(previous_cutoff, cutoff, limit=1000)` accepts timezone-aware ISO
strings and returns the validated manifest from `POST /v1/source-evidence/capture`.
Persist the entire result in the morning owner's private durable run state before
selection or payload reads. Then pass saved `version_ref` values to
`read_versions(version_refs)`, in batches of 1 to 100 unique references. It
returns a validated list in exact requested order, with bounded `text` and opaque
`media_refs`. Compare each returned `evidence_hash` with its saved manifest item.
The client validates manifest hashes/windows/eligibility, reference identities,
full evidence hashes, timing/history/overflow metadata and batch completeness;
malformed or changed results raise `ControlPlaneContractError`.

Capture is never silently retried because a retry observes a newer committed
state. Transport/HTTP failure raises a sanitized `ControlPlaneUnavailable`.
Recover persisted captures by rereading identical immutable references. Missing
retained history is an incomplete run, never a reason to claim work or replay
intake. Unset verified retention boundaries, early/late capture or corpus overflow
remain incomplete even if some useful records are available. Origin is currently
unknown because the canonical envelope carries only collecting publisher IDs;
selection and copied-story deduplication must preserve that uncertainty.
The full field/hash contract is in the Control Plane README and versioned OpenAPI.
