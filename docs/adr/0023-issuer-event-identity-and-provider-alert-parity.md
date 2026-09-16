---
status: accepted
---

# Preserve material follow-ups and align provider alerts

The watcher must preserve a later issuer report as a separate alert when its material facts change, even if its source text overlaps an earlier report. Cross-provider equivalents should still collapse to one alert when structured event facts establish the same development, and Phintraco should use the shared issuer-alert market-data structure while retaining its provider identity and legal-name heading.

## Considered options

- Suppress same-provider items using broad raw-token overlap: rejected because generic issuer and transaction vocabulary incorrectly suppresses material follow-ups such as MGLV `14884`.
- Require exact model-generated dedupe facts across providers: rejected because equivalent Tuntun and Phintraco reports can express the same event with different wording, as with FORU.
- Replay already-suppressed historical alerts during the change: rejected because the change is future-facing and historical delivery requires a separate approval.

## Consequences

The dedupe model must distinguish a repost from a follow-up update and compare structured event facts across providers. Provider-specific headings remain allowed, but market-data presentation and source provenance become consistent.
