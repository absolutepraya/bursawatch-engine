---
status: accepted
---

# Allow text-only delivery when ordinary WhatsApp source media is unavailable

The WhatsApp Channel archive can retain a source post while failing to decrypt
or download one of its supported images or videos. Treating that archive miss
as a permanent delivery block prevents useful BRI macro and issuer-news text
from reaching Discord and causes the same known source problem to be retried
on every drain.

For ordinary BRI macro and issuer-news items, the watcher therefore delivers
the validated text after the archive and analysis checkpoints have succeeded.
It records `media_delivery_status` as `unavailable` when all requested source
media is missing, or `partial` when only some media is missing, records the
skipped source indexes and sanitized `media_error`, and emits a degraded
heartbeat. Available media is still delivered. The known archive miss is
terminal for that media leg, so a later drain does not duplicate text or retry
the same unavailable source forever.

This does not weaken technical-review safety. A BRI `#TechnicalReview` still
requires exactly one verified archive-owned image before any All Swing text,
image, or Board handoff. Discord transport and upload failures remain
retryable for every route because they are delivery failures, not source-media
availability facts.

## Consequences

- Macro and issuer-news information survives a source-media availability miss.
- Heartbeats and outbox state make the degraded text-only outcome observable.
- Technical Swing keeps its all-or-nothing image boundary and Board ordering.
- Archive media remains VPS-only and content-addressed; no placeholder asset is
  fabricated and no media is copied into logs or the control-plane database.
