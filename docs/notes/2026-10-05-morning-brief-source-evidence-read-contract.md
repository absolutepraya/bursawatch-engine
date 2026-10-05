# Morning brief source-evidence read contract proposal

Design only. Reviewed local main 9102eaf without production queries, credentials, source replay or mutations. The inspected code establishes storage and adapter capabilities, not actual live corpus completeness. This supplements the [morning design spec](2026-09-27-bursawatch-morning-brief-design-spec.md).

## Available source records

[Envelope validation](../../service-bursawatch-control/bin/control_plane/source_inbox.py:63) requires canonical endpoint and publisher IDs, provider event identity, timezone-aware published/observed timestamps, source URL, payload/hash, parser version and durable media metadata. [Immutable versions](../../service-bursawatch-control/migrations/014_source_inbox.sql:12) retain originals, corrections and tombstones with server acceptance timestamps.

| Adapter | Candidate evidence | Limitation |
| --- | --- | --- |
| Telegram | Message text, message URL, published/observed timestamps, reply context and media refs | Forward-origin publisher is not serialized |
| X | Post/thread HTML, public post URL, quoted URLs/content, timestamps and media refs | Quoted origin is not a normalized canonical publisher |
| WhatsApp | Text, links, provider message ID, channel publisher and timestamps | Source URL identifies the channel rather than a message; forward origin is missing |
| Stockbit RSS | Article URL, title, feed text, publication timestamp and lane | Text can be truncated at 12,000 characters or fall back to title; no complete article/image guarantee |

The canonical Stockbit publisher spans all four lanes; Phintraco spans its two Telegram endpoint identities. Limits must not reset per route or lane. Catalog publisher identity identifies the collecting publisher, not necessarily the original author of forwarded or quoted text.

## Existing read APIs cannot provide the agreed bundle

The [known-event inspection route](../../service-bursawatch-control/bin/control_plane/api.py:627) accepts an event key under machine/admin authorization. Work listing is status-filtered, limited to 100 entries, and lacks a window query or pagination cursor. Work claims mutate processing state and must not be used for research intake.

The Published Feed is a forward-only projection of confirmed Discord output, with human viewer/admin reads. Its date filter uses delivery confirmation, not source publication. It is useful delivery provenance, not a complete corpus of all collected events.

## Proposed minimum read surface

Keep normalized source evidence with its existing Control Plane owner. Add a bounded read-only event-window query under a least-privilege machine authorization contract. The morning owner assembles and persists its frozen research manifest; it does not receive work-claim, suppression, replay or delivery authority. Exact routes and credential provisioning are future implementation decisions.

Inputs are previous brief cutoff, current 07:30 WIB cutoff, bounded candidate/page limits and deterministic continuation identity. Select each event's highest eligible version accepted and observed by cutoff; suppress it only if that selected version is a tombstone. Then apply the publication window `(previous_cutoff, current_cutoff]`. Later corrections and tombstones must not rewrite the original frozen morning evidence. The lookback spans intervening weekends and holidays.

Return event key/version, acceptance timestamp, publication and observation timestamps, canonical catalog publisher and endpoint, source URL, bounded text with truncation status, parser/hash and opaque media metadata. Preserve original-publisher identity only when supported; mark it unknown otherwise. Do not expose credentials, private storage URLs or unrelated source payload fields. Deduplication, relevance, selection and the 30-item/three-per-publisher limits remain morning-owner responsibilities.

Capture candidate version identities and provenance in one consistent database read snapshot, then persist the immutable manifest with the morning run. Independent timestamp-filtered pages do not guarantee repeatability: database transaction timestamps can precede a later commit, and page requests can observe different committed rows. Paginate the frozen manifest, not a changing live result set. Record snapshot capture time, cutoff and overflow/unavailability explicitly. Do not claim completeness when a bounded candidate ceiling truncates the window.

No source purge was found in the inspected code, but no minimum retention guarantee or actual weekend/holiday corpus was established. The implementation contract needs retention covering the complete required lookback and run recovery period, plus an explicit incomplete-evidence response when unavailable. This investigation does not authorize a historical backfill.

## Reopened publisher decision

The agreed three-item original-publisher cap cannot be guaranteed for records whose original author is absent. Proposed policy: cap by verified original publisher where present, otherwise canonical collecting publisher with origin unknown disclosed. Deduplicate exact/near-identical stories separately and do not count copied accounts as proven independent opinions. The alternative is to exclude records with unverified original publishers. This is a user decision, not a silently adopted fallback.

## Publisher decision confirmed

The user accepted using available publisher information without further origin-verification complexity. Use verified original identity when present, otherwise canonical collecting publisher; apply the three-item cap across that publisher's routes and lanes. Preserve unknown origin in provenance, deduplicate copied stories and do not invent independent author identities. Missing original authors alone do not exclude eligible records. This supersedes the open decision above.
