---
status: accepted
---

# Replace Superseded X Deliveries Deterministically

The X watcher will inspect every newly observed source post for a possible replacement of a previously delivered post. This behavior applies to every watched profile by default and does not add a profile configuration field. Historical Discord cleanup remains manual and explicitly approved; the automatic workflow is forward-only.

A previous delivery becomes a replacement candidate only when the source publication times are within one hour and the source belongs to the same account. Candidate generation uses deterministic signals: normalized string comparison, token overlap, character trigram similarity, paragraph overlap, quoted-post and outbound-URL fingerprints, cashtags, dates, numbers, and other source metadata. The watcher must not use an LLM, embeddings, or another AI similarity model for deduplication. Similarity only nominates a candidate.

Replacement of an ordinary source version requires explicit confirmation from X that the older status has a newer version, with the newer status ID matching the observed source post. If that evidence is unavailable, ambiguous, or inconsistent, the watcher keeps both deliveries and emits an attention heartbeat. Similarity alone never authorizes deletion. A same-root self-chain continuation within the configured thread age is a separate deterministic bundle update: relation metadata proves that the new root-to-latest bundle supersedes the earlier bundle, without treating the continuation as an X edit.

The watcher will persist a bounded 90-day delivery ledger containing source version identity, thread identity, rendered content fingerprints, destination channel, Discord text and media message IDs, delivery timestamps, and supersession relationships. Discord message IDs returned by successful posts are part of the delivery record, rather than being discarded after the outbox item is removed.

A source post or assembled self-chain is represented as one delivery bundle. If a member of a self-chain is superseded, the watcher rebuilds and delivers the complete root-to-latest bundle. A clearly related continuation within the configured thread age also replaces the existing bundle; a continuation after that age is a new delivery. Profiles using disabled thread handling continue to replace individual posts independently.

Replacement delivery is transactional in presentation order: send the new text and media first, mark the new bundle delivered, then delete every message in the superseded bundle and verify each deletion. The new bundle remains if cleanup is partial, while failed deletions remain retryable and produce an attention heartbeat. A replacement message keeps the normal rendering format, with `(Updated Tweet)` appended to the account byline, for example `-# <:rickyho1989:1531920390434328577> Ricky Ho (Updated Tweet)`.

This design avoids false deletion from similar market commentary, preserves a successful replacement when Discord cleanup fails, and keeps deduplication explainable and model-free. It adds bounded state, source-page checks for near-duplicate candidates, and a brief period where both bundles may be visible while the replacement is being delivered.
