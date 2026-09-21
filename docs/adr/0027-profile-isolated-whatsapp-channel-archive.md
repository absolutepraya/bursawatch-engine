---
status: accepted
---

# Specialize WhatsApp Channel watching as profile-isolated archival intake

`cron-wa-channel-watch` remains the one shared Channel intake and processing engine. BRI Danareksa Sekuritas, INS, and Samuel Sekuritas Indonesia are separate **Channel Profiles**, each binding one stable `@newsletter` identity to its own source configuration, archive namespace, cursor, routing policy, and fixtures. This preserves specialized source handling without duplicating the existing single Baileys connection, durable intake, deduplication, and operational lifecycle. INS and Samuel begin in archive-only observation, while BRI is the first profile intended for explicitly approved forwarding.

An **Archived Channel Record** is an immutable capture of a source post, its original text or caption, identity and time metadata, links, checksums, and supported media. The **Historical Analysis Archive** contains Archived Channel Records only: it supports source-format research, audits, and fixtures, but must never be treated as a delivery queue. It retains raw records and supported media for 365 days per profile, while redacted test fixtures are permanent and remain outside Git. A **Routable Event** is a newly observed post eligible under an explicitly activated profile's forward cursor and route policy. Historical records, including BRI's pre-existing retained sample, are permanently non-routable and cannot be replayed to Discord.

A source post always remains one Archived Channel Record. It may derive zero or more **News Items**, each with its own relevance and route decision. A News Item is a concise, source-grounded Discord delivery of no more than two paragraphs, not a copy of the source bulletin. This permits distinct items from one bundled WhatsApp post to reach their appropriate destinations without losing the original evidence.

## Consequences

- INS and Samuel start as archive-only observation profiles after their identity and subscription gates are approved. They cannot forward until a later, separate activation decision. BRI forwarding remains a separately tested and explicitly activated profile.
- A Channel Profile may require a channel-specific parser and routing policy, but it shares the bridge, archive boundary, state discipline, and runtime lifecycle with every other profile.
- The VPS-only archive root is `~/.hermes/state/whatsapp-channel-watch/archive/`, with mode-`0700` directories and mode-`0600` records, media, and exports. It retains raw evidence for at least 365 days. `bursawatch-wa-channel-archive.sh` supports verify, bounded query, explicit private export, dry-run prune, and guarded BRI cutover planning. It is not a schedule, history fetcher, or replay tool.
- Archive completeness must be recorded honestly. The current BRI sample is usable for conservative format research but is not a claim of complete 30-day source coverage.
- A single-ticker BRI `#TechnicalReview` with its required single chart image reaches the chronological All Swing channel first, then makes a typed, retryable Swing Plan Board handoff as Chart context. Its text is delivered before the image, and the Board consumes the archived image copy rather than watcher-owned state. It can never create a Primary Plan. Multi-ticker or ambiguous technical posts remain All-only.
- A BRI technical review without exactly one verified archive-owned chart stays pending with no partial All Swing delivery. Neither an untrusted source-media path nor a missing attachment is an acceptable substitute.
- The source-grounded eligibility rule for other chart formats and the nontechnical destination policy remain separate decisions.
