# Instagram platform source boundary

Runtime identity reserved: `bursawatch-ig-source-ingest`. Entry point:
`bin/runner.py`. No Hermes job is registered. The adapter is release metadata
only and must not run beside the live Instagram watcher.

Each verified configured profile has an independent future-only cursor and
private staged inbox handoff. RSSHub page order determines freshness. A full
page without the prior anchor blocks and retains the cursor; publication time
remains event metadata. At most the next 20 fresh events are considered for
media upload. The adapter reuses the live watcher's bounded public-HTTPS
downloader with an 8 MiB object limit and 25 MiB publication limit, then uploads
bytes through the shared Source Media Owner before inbox acceptance. Accepted
events contain validated opaque refs, never signed CDN URLs or bytes. Missing
or unsupported media and upload failures write safe caption metadata to
`blocked-media.json` and retain the cursor. No `company_news` or `macro_news`
work is claimed. OCR, vision, agent relevance, and original-image delivery stay
with the existing watcher until a reviewed pipeline migration has complete
no-post parity.

The Source Media Owner uses `BURSAWATCH_SOURCE_MEDIA_URL` and the private
upload-only token file `BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE`. If either
is absent, media events remain blocked.
