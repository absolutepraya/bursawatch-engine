# Instagram platform source boundary

Runtime identity reserved: `bursawatch-ig-source-ingest`. Entry point:
`bin/runner.py`. No Hermes job is registered. The adapter is release metadata
only and must not run beside the live Instagram watcher.

Each verified configured profile has an independent future-only cursor and
private staged inbox handoff. A media publication writes bounded caption and
identity metadata to a private `blocked-media.json`, then retains its cursor.
It neither stores signed CDN URLs nor claims that the media bytes are durable.
No `company_news` or `macro_news` work is claimed. OCR, vision, agent relevance,
and original-image delivery stay with the existing watcher until a reviewed
media and pipeline migration has complete no-post parity.
