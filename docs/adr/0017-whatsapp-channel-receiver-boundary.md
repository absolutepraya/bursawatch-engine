---
status: accepted
---

# Separate the WhatsApp Channel receiver from Hermes processing

The WhatsApp Channel watcher will reuse Hermes's existing single Baileys bridge, with an additive Channel sink that converts supported Channel posts into normalized events and writes them to a durable Processing queue. A separate Hermes watcher owns source eligibility, future-only state, relevance decisions, summaries, rendering, media delivery, Discord delivery, and operational heartbeats. Event-driven delivery is primary, with bounded reconciliation for recovery. This keeps WhatsApp Web session lifecycle and authentication failure separate from the deterministic watcher and its delivery state, while preserving the X watcher prompt and processing boundary.

The observer account is a separate WhatsApp number dedicated to Hermes. Yanto's existing Cloud API number remains untouched, and the watcher must not create a second Baileys session against either account.
