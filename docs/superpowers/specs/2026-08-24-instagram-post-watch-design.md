# Instagram Post Watch Design

**Date:** 2026-08-24
**Status:** Approved design, ready for implementation planning
**Owner:** Abhip / Yanto

## Goal

Create `instagram-post-watch`, an agent-backed Hermes watcher that monitors configured public Instagram profiles for posts and reels, reads captions and all carousel text, and delivers relevant source-grounded analysis to Discord using the existing `x-post-watch` pattern.

The first watched profile is `beyondthefundamental`:

```text
https://www.instagram.com/beyondthefundamental
```

## Approved decisions

- Watch public posts and reels only.
- Exclude stories, comments, tagged posts, mentions, live broadcasts, and private-account monitoring.
- Use an authenticated RSSHub Instagram source. Credentials belong to a dedicated Instagram watcher account and remain in VPS service configuration, never in this repository.
- Use a new sibling cron named `instagram-post-watch`, not a generalization of `x-post-watch`.
- Treat one Instagram publication as one event. Preserve every carousel asset in source order.
- Always inspect the caption and every carousel image. For reels, inspect the cover and a bounded set of sampled frames.
- Run OCR on every downloaded image or sampled frame before deciding whether the LLM needs original images.
- Reuse the X watcher's relevance, promotion exclusion, Indonesian title and summary, central-thesis routing, bounded agent lease, Discord delivery, heartbeat, and no-backfill patterns. Instagram additionally excludes generic trading or investing education and actionable trade setups, even when a ticker is present.
- Route the first profile to the canonical `macro_news` and `id_stocks_news` channel keys shared with X. Accept `macro` and `id_stock` only as compatibility aliases. Do not invent a new route or custom emoji.
- Poll hourly once the live Hermes schedule is explicitly approved.

## Source and authentication

The source adapter uses the authenticated RSSHub Instagram web API route:

```text
http://127.0.0.1:1201/instagram/2/user/<handle>?format=json
```

The RSSHub container owns `IG_COOKIE` through its VPS-local `.env`. The watcher does not receive or log the cookie. The account should be a dedicated watcher account. RSSHub's legacy private route accepts `IG_USERNAME` and `IG_PASSWORD`, but its login flow does not support 2FA, so the watcher uses the cookie-based web API route instead.

The watcher accepts only Instagram profile URLs and publication URLs for `/p/` and `/reel/` forms. If the source explicitly reports a private target, the profile is skipped and the heartbeat is degraded. The watcher does not discover private accounts or attempt to bypass Instagram access controls.

RSSHub remains the source boundary. Direct Instagram HTML scraping, Picuki, Picnob, Cobalt, and Meta Graph API access are not alternate production fetchers in v1. The parser is isolated behind a source interface so a future adapter can be added without changing state or delivery contracts.

## Configuration

`instagram-post-watch/config/watches.json` owns all watched-account policy. The root object contains exactly `version` and a non-empty `profiles` array. Version is `1`. Unknown root, profile, OCR, or sampling fields are rejected.

The first profile has this shape:

```json
{
  "version": 1,
  "profiles": [
    {
      "id": "beyondthefundamental",
      "enabled": true,
      "source": "rsshub",
      "profile_url": "https://www.instagram.com/beyondthefundamental",
      "handle": "beyondthefundamental",
      "display_name": "Beyond thy Fundamental",
      "platform_emoji": "📸",
      "emoji": "",
      "discord_channels": [
        {
          "key": "macro_news",
          "channel_id": "1531655369884045382",
          "description": "Broad economic, business, market, sector, and cross-asset analysis."
        },
        {
          "key": "id_stocks_news",
          "channel_id": "1525102508714889257",
          "description": "Direct IDX-listed company, earnings, corporate action, fundamental, and valuation analysis."
        }
      ],
      "forward_post": true,
      "forward_reel": true,
      "forward_media": true,
      "enable_llm_title": true,
      "enable_llm_summary": true,
      "enable_llm_routing": true,
      "enable_llm_relevance_filter": true,
      "additional_prompt_instruction": "Always use the caption and all carousel OCR together. Preserve the account's own thesis.",
      "max_items_per_poll": 20,
      "ocr_languages": ["ind", "eng"],
      "ocr_min_confidence": 0.70,
      "max_reel_frames": 5
    }
  ]
}
```

`emoji` may be empty because no account-specific custom emoji has been approved. The renderer uses `platform_emoji` and includes `emoji` only when it is non-empty. Profile IDs are durable state namespaces and must not be renamed after deployment. Handles are unique case-insensitively. `max_items_per_poll` is one to 100. `ocr_min_confidence` is between 0 and 1. `max_reel_frames` is one to 8 and includes the cover frame.

## Publication and media model

The normalized source model is a publication, not a thread:

```text
Publication
  profile_id
  publication_id       stable Instagram media ID, otherwise shortcode
  url
  published_at
  caption_html
  kind                  post or reel
  media[]               ordered image or video assets
```

The parser extracts a stable media ID from RSSHub metadata, the publication URL, or a verified shortcode. If it cannot derive a stable ID, it fails closed and reports a degraded source condition. It never uses a signed CDN URL as the durable identity.

For an image publication or carousel, every source image is downloaded in order. For a reel, the original video is retained for Discord delivery and the cover plus up to `max_reel_frames - 1` evenly spaced frames are generated with the VPS `ffmpeg` binary for OCR and optional vision analysis. Sampled frame files are analysis artifacts, not Discord delivery media.

Downloaded publication media stays under the watcher-owned runtime state directory until the event's Discord delivery is complete. It is not committed, mirrored as source, or exposed in logs. A content hash identifies an OCR cache entry, and the cache key also includes the selected OCR engine, model version, language set, and preprocessing version.

## OCR and vision gate

The OCR implementation has an interchangeable backend interface. Tesseract and PaddleOCR Mobile are benchmarked against real text-heavy carousel samples on the VPS. The selected backend is configured outside the repository's source code, and the benchmark records the selected engine, model version, median per-asset latency, peak memory, and text-recovery result. OCR dependencies live in an isolated watcher-owned VPS environment and never in the shared Yahoo Finance environment.

OCR runs for every asset, including assets that will later be sent to the LLM. A blank result is valid when the image contains no detectable text. OCR output is bounded per asset and for the complete publication before it is put in an agent payload.

The deterministic gate produces one of three modes:

### `text_only`

Use caption plus OCR text from every asset. Do not attach original images to the LLM request when:

- every asset downloaded and decoded successfully;
- OCR completed without timeout or backend error;
- every detected text region meets the calibrated confidence threshold;
- normalized OCR output is not obviously corrupted; and
- caption plus OCR contains enough text to judge relevance and summarize the publication.

### `vision_partial`

Use caption plus OCR text from every asset and attach only the failed or uncertain image assets when any of these conditions holds:

- an image download, decode, or OCR operation failed;
- detected text confidence is below the calibrated threshold;
- OCR output is malformed or mostly non-word noise; or
- a sampled reel frame contains likely on-screen text that OCR did not recover.

The agent receives all OCR text plus local paths for the uncertain assets. If one carousel slide fails, the other slides remain represented through their OCR text.

### `vision_full`

Use caption plus all OCR text and attach all carousel images or sampled reel frames when:

- caption and OCR are too sparse to judge the publication's meaning;
- the caption explicitly depends on a chart, table, diagram, annotation, or visual comparison;
- multiple slides are uncertain; or
- the publication's meaning depends on the relationship between slides rather than isolated text.

The agent reads every supplied local path with vision. It does not refetch Instagram, use the signed CDN URL directly, or browse unrelated sources for image interpretation.

OCR reduces multimodal input on the common path but does not remove the normal text analysis call. Deterministic promotion and empty-content filters may reduce total agent calls separately.

## Agent boundary

The scanner owns source access, media download, frame sampling, OCR, the vision decision, deduplication, state, rendering, Discord delivery, and heartbeats. Hermes receives one bounded event only when `wakeAgent` is true.

The wake payload contains:

```text
event_key
profile_handle
profile_name
post_url
post_kind
caption_text
post_text              caption plus labeled OCR text for every asset
ocr_assets[]           asset index, text, confidence, and status
vision_mode
vision_asset_paths[]   local paths only for partial or full vision
media_count
title_required
summary_required
route_required
relevance_required
relevance_guard_required
instruction
```

Caption text, OCR text, and local image content are untrusted source data. The agent must follow only the trusted instruction field, read every supplied vision path, return the exact closed analysis object, and submit through the wrapper. It never reads watcher state, fetches Instagram, posts to Discord, processes historical events, or returns a natural-language cron response.

The title, summary, promotion, and route rules match `x-post-watch`, while Instagram uses a stricter relevance boundary that excludes generic investing or trading education and actionable trade setups. A target derived from earnings, fundamentals, or valuation remains substantive analysis, not an actionable trade setup. The source account's central thesis determines `macro_news` versus `id_stocks_news`. OCR text participates in deterministic disclosure, promotion, and noise guards, but OCR never appears in the user-facing Discord body unless the source caption or generated summary independently includes the same fact.

## State, delivery, and failure behavior

State version `1` contains:

- per-profile cursor;
- FIFO publication outbox;
- serialized publication and ordered media metadata;
- OCR results and vision mode for each queued event;
- local media-root reference and cleanup status;
- 90-day delivery ledger;
- filtered count;
- 15-minute agent leases.

The first successful observation stores the newest source cursor and does not backfill. Later unseen publication IDs are queued chronologically. A source failure never advances its profile cursor. `enabled: false` stops polling and new queueing but does not suppress existing queued events.

Each Discord text and media leg is persisted independently. Text is delivered first, followed by original carousel images or the original reel video in source order. A failed media upload never resends already delivered text. Temporary sampled frames and OCR-only artifacts are deleted after the event is fully delivered. A failed cleanup remains retryable and degrades the heartbeat.

Instagram publications are immutable delivery events in v1. The watcher does not attempt caption-edit supersession or delete previously delivered messages when an existing publication changes.

Every run sends an operational heartbeat to `#hermes` (`1505162000420835388`) using the watcher name `instagram-post`:

```text
🫀 instagram-post · HH:MM WIB · <tokens>[ ⚠️]
```

Tokens include fetched, filtered, queued, OCR processed, vision fallback, delivered, and error counts. When deterministic noise filtering occurs, the heartbeat may include bounded reason codes such as `generic_investing_education` and `actionable_trade_setup`. Degraded reasons include RSSHub authentication or rate-limit failures, empty feeds, media download or frame-sampling failures, OCR backend failures, expired agent leases, invalid submissions, and Discord delivery failures. Fatal runs use:

```text
❌ instagram-post · HH:MM WIB · failed: … <@443342168434933760>
```

Credentials, cookies, signed URLs, raw provider bodies, and local secret paths never appear in logs, heartbeats, payloads, tests, or commits.

## Deployment boundaries

The cron source lives in `instagram-post-watch/` with exactly `AGENTS.md` and `SKILL.md` at its root. Executable files deploy through `./deploy.sh instagram-post-watch`. The reviewed config and `SKILL.md` are synchronized separately after comparing the local and VPS copies. The dotfiles VPS mirror is never an authoring target.

RSSHub credential configuration, the isolated OCR environment, and Hermes cron registration are VPS operational changes. They require a reviewed diff and explicit approval before the first VPS write. The Hermes schedule is `*/15 * * * *` in `Asia/Jakarta`, but it is not registered as part of local source work until that operational approval is complete.

## Verification

Tests must prove:

1. strict configuration shape and profile URL validation;
2. RSSHub post, carousel, reel, private-target, malformed-feed, and source-error parsing;
3. stable publication IDs and first-run no-backfill behavior;
4. ordered media extraction, download, reel frame sampling, and cleanup;
5. OCR cache keys, bounded output, and backend failure handling;
6. every OCR vision-gate branch, including partial and full asset selection;
7. exact wake payload and agent submission schemas with local vision paths;
8. promotion, relevance, route, title, and summary behavior using caption plus OCR;
9. text-before-media Discord delivery, independent retries, media ordering, and no duplicate sends;
10. profile isolation, cursor safety, lease expiry, heartbeat degradation, and no-post execution.

Before production deployment, run the focused suite and `bash scripts/test-all`. Deploy only from a clean published commit, compare checksums for every changed runtime file, run an isolated no-post smoke with isolated state and media directories, then verify the first natural scheduled execution and its Discord heartbeat before claiming the cron is live.
