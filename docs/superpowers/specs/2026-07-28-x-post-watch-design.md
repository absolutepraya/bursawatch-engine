# X Post Watch design

## Goal

Create `x-post-watch`, a deterministic Hermes `no_agent` cron that forwards selected X posts from declaratively configured profiles to Discord. It makes no LLM calls and uses the existing VPS RSSHub X user feed.

The first configured profile is `Kutekians` (`Almer Sad, CFA`) and sends alerts to Discord channel `1531655369884045382`.

## Scope

- Poll every configured profile once per hour, 24 hours a day, in `Asia/Jakarta`.
- Forward or skip normal posts, quote posts, direct replies, and reposts according to each profile configuration.
- Render source text as safe Discord Markdown.
- Deliver text before media, with every media attachment posted as its own Discord message in source order.
- Persist cursors and delivery outboxes so retries never lose a discovered post.
- Report source, classification, download, and Discord failures in the required `#hermes` heartbeat.
- Provide full local documentation and tests for future agents.

Out of scope: direct X GraphQL polling, account discovery, LLM analysis, replaying old posts, and changing a live cron schedule without the required operational approval.

## Source and classification

The scanner derives the RSSHub user route from each configured `handle` and makes one request per profile per scheduled hour. It does not add a second X request for post verification.

For every returned item, the scanner records a stable X post ID and classifies it before it enters the delivery outbox:

| Class | Detection | Config key | Initial behavior |
| --- | --- | --- | --- |
| Normal post | Not a repost, quote, or direct reply | `forward_normal_post` | Forward |
| Quote post | RSSHub supplies a quoted-post relationship and URL | `forward_quote_post` | Forward |
| Direct reply | RSSHub explicitly identifies an in-reply-to relationship | `forward_reply` | Skip |
| Repost | RSSHub identifies an `RT`/repost item | `forward_repost` | Skip |

An item with ambiguous or incomplete relation metadata is skipped and recorded as a degraded source condition. This is safer than forwarding a post that does not match a profile's filters.

The initial RSSHub user timeline is the selected source because it is live and authenticated on the VPS. A per-post X metadata request currently returns no usable relation data, while direct GraphQL polling would duplicate RSSHub's auth-sensitive machinery.

## Configuration

`x-post-watch/config/watches.json` owns all per-profile behavior. Adding a profile must only require adding an object to this file and deploying it with the normal review process.

```json
{
  "version": 1,
  "profiles": [
    {
      "id": "kutekians",
      "enabled": true,
      "profile_url": "https://x.com/Kutekians",
      "handle": "Kutekians",
      "display_name": "Almer Sad, CFA",
      "emoji": ":kutekians:",
      "discord_channel_id": "1531655369884045382",
      "forward_normal_post": true,
      "forward_quote_post": true,
      "forward_reply": false,
      "forward_repost": false,
      "forward_media": true,
      "max_items_per_poll": 50
    }
  ]
}
```

`id` is the durable state namespace. `profile_url`, `handle`, `display_name`, `emoji`, destination, all forwarding controls, media behavior, enablement, and the per-run safety cap are therefore explicit and independently reviewable.

On first observation of a profile, the scanner stores its current cursor without backfilling historical feed items. Later unseen eligible items are queued in chronological order. The state file is runtime data and is never part of source deployment or configuration.

## Discord rendering

The heading is exact:

```md
### :twitter::kutekians: Almer Sad, CFA
```

The body preserves safe semantic Markdown from the RSSHub post content. Raw HTML is not emitted. Links, paragraphs, lists, and emphasis are converted only when Discord can render them safely. The footer is exact:

- Normal post: `[View on X](<post URL>)`
- Quote post: `[(Quoted)](<quoted-post URL>), [View on X](<post URL>)`

Every source media item is posted after all text, one attachment per Discord message and in its source order. The text message and every media message are independent delivery legs. A failed media upload does not resend the text.

If rendered text exceeds Discord's 2,000-character limit, it is split in order. The first text message contains the heading, continuation messages contain only remaining content, and the footer is appended only to the last text message. Media follows after the last text leg.

## Scheduling, state, and failure behavior

The job runs hourly at minute zero in `Asia/Jakarta`, including overnight. It does one RSSHub request per enabled profile per run. It must not make a tight retry loop for source failures, so an exhausted or rejected X auth token is retried only by the next scheduled run.

Each profile has a durable cursor plus FIFO outbox events. An event tracks its text leg, every media leg, retry state, returned Discord IDs, and last sanitized failure. State is persisted immediately after each externally visible delivery transition. A process lock covers source observation, classification, delivery, heartbeat, and state persistence.

A source failure affects only that profile. Other enabled profiles can continue. A source failure must never advance the failed profile's cursor. If an overnight volume exceeds the returned feed window and the cursor cannot be reconciled safely, the run is degraded rather than silently claiming complete coverage.

The heartbeat is sent to Discord `#hermes` (`1505162000420835388`) on every scheduled run, including no-hit runs. It follows the standard form:

```text
🫀 x-post · HH:MM WIB · <tokens>[ ⚠️]
```

When degraded, the heartbeat includes a short sanitized reason, for example `RSSHub X feed HTTP 403: authentication rejected`, timeout, malformed XML, ambiguous relation metadata, media-download failure, or pending Discord delivery. Fatal failures use the standard `❌` form. Tokens, cookies, authorization headers, and raw provider error bodies must never be included in Discord, logs, tests, or source control.

## Folder contract and documentation

The eventual cron folder contains:

- `SKILL.md`: runtime, channels, schedule, environment, and dry-run controls.
- `README.md`: developer entry point, test commands, deploy procedure, checksum validation, and VPS no-post smoke test.
- `SPEC.md`: exact operational and behavioral contract.
- `CONTEXT.md`: terms, dependencies, source limitations, configuration rules, and future-maintainer decisions.
- `config/watches.json`: reviewed profile configuration.
- `bin/`: scanner and wrapper only.
- `tests/` and fixtures: behavioral regression coverage.

The root README inventory, VPS runtime skill path, VPS wrapper, and supported Hermes cron registration must use the same `x-post-watch` identity before the cron is considered complete.

## Verification plan

Tests cover:

1. Configuration validation, including duplicate IDs, invalid handles, invalid Discord IDs, and invalid booleans.
2. Normal, quote, direct-reply, repost, and ambiguous item classification.
3. Exact heading and footer rendering, safe Markdown conversion, Unicode, empty text, and text splitting.
4. One-media-per-message ordering and text-before-media behavior.
5. First-run cursor initialization with no backfill and later unseen-item deduplication.
6. FIFO outbox retries, Discord 429 handling, partial media failures, and no duplicate text sends.
7. RSSHub 401/403, timeout, malformed XML, and cursor-gap degraded heartbeats with secret-safe diagnostics.
8. Per-profile isolation, lock behavior, hourly heartbeat behavior, no-post output, and no-LLM execution.

Before deployment, run the focused tests and the complete suite through the shared project virtual environment. After deployment, compare local and VPS checksums for changed executable files, then run the documented VPS no-post control. The smoke test renders intended messages and exercises feed parsing, classification, media discovery, and heartbeat behavior without posting to Discord or changing live state.
