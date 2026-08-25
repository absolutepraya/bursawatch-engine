# IDX Market News Watch Design

**Date:** 2026-07-14  
**Status:** Approved design, awaiting implementation plan  
**Owner:** Abhip / Yanto, Hermes agent on the VPS

## Goal

Deliver a compact, market-wide IDX company-news feed to Discord `#id-stocks-news` (`1525102508741889257`) without turning it into an unreadable source repost stream.

The watcher monitors Tuntun Sekuritas and Phintraco Sekuritas, selects only source-supported issuer information, suppresses duplicate cross-provider coverage, and produces:

1. immediate Tier 1 alerts for strict material disclosures, any time of day; and
2. at most two compact Tier 2 digests per weekday, one pre-market and one post-market.

The feed is informational. It must never create a trade recommendation, price target, valuation view, or unsupported inference.

## Evidence behind the scope

The 30 June to 14 July 2026 source audit found:

| Source | Eligible company material before curation | Implication |
|---|---:|---|
| Tuntun `Daily Market Update & News` topic | 189 company-level units across 11 active sessions, 17.2/day | Broad issuer coverage, unsuitable for raw forwarding. |
| Phintraco | 18 company Notes, 2 Company Flash reports, 7 Stock Information posts | More selective, but insufficient as the only discovery source. |
| Cross-source overlap | 8 of 18 Phintraco company Notes repeated the same issuer fact covered by Tuntun | Independent forwarding would create duplicate alerts. |

Matched duplicate examples include EMAS 1Q26 results, DEWA's Rp22T contract, DSSA's acquisition, CBRE's Hidayah project, BBNI's buyback completion, PTBA exploration spending, and CBDK subsidiary funding. Tuntun was earlier for five of the eight matched facts and Phintraco for three. Neither provider is reliably first.

## Non-goals

This watcher does not:

- forward broad market, macro, sector, commodity, FX, bond, index, calendar, or event-promotion content;
- forward raw PDFs, source previews, or generated replacement images;
- repeat existing Phintraco trade calls, target or stop-loss reminders, weekly swing ideas, SSF reviews, or source charts already owned by the trade watchers;
- become a personal portfolio-only watchlist;
- backfill historic Telegram messages at first deployment; or
- let a failed source, summary, image upload, or Discord delivery discard an eligible event.

## Source scope

### Tuntun Sekuritas

The adapter reads only the `Daily Market Update & News` forum topic rooted at Telegram topic ID `3743` in `tuntunsekuritas`.

Eligible source shapes:

- standalone ticker-led issuer news;
- individual company entries in `Corporate` posts, extracted as separate company candidates; and
- issuer-specific Tuntun Special Topics, including a source PDF only as private extraction input.

Excluded source shapes:

- Daily Market Update, Midday Update, Evening Update, and any other macro, market, industry, or sector recap; and
- promotional, educational, webinar, app, account, or customer-service posts.

### Phintraco Sekuritas

The adapter reads the public `phintasprofits` channel.

Eligible source shapes:

- `Phintraco Sekuritas Notes` that contain an issuer-specific development;
- `Phintraco Sekuritas Company Flash`, restricted to its factual issuer content; and
- `Stock Information` notices for issuer-specific exchange status, including UMA, suspend, unsuspend, and FCA notices.

Excluded source shapes:

- Good Morning, index-session updates, Daily Domestic or Global Market Review, economic calendars, fixed-income reports, and economic or sectoral research;
- all Stock Review, Weekly Swing Trading Ideas, SSF Review, top-pick, BUY/SELL, entry, target, stop-loss, and reminder material; and
- any market review whose company-news context cannot be separated without leaking trade or market commentary. The whole review is excluded.

## Architecture

```text
Phintraco channel     Tuntun news topic
        |                    |
        v                    v
PhintracoNewsAdapter   TuntunNewsAdapter
        |                    |
        +---- independent provider cursors ----+
                                                  v
                               Candidate extraction, one company per item
                                                  v
                         Source-bound structured classification and summary
                                                  v
                        Cross-provider dedupe and strict Tier assignment
                                                  v
                  Tier 1 immediate outbox     Tier 2 scheduled digest queues
                         |                    |              |
                         v                    v              v
                    Discord alert        08:30 WIB       16:30 WIB
                    + direct image       pre-market       post-market
                                         top 5 max        top 5 max
```

One new Hermes agent-enabled cron, named `idx-market-news-watch`, runs every minute in `Asia/Jakarta` time. Its deterministic launcher polls, extracts, queues, deduplicates, schedules, and delivers. It returns `{"wakeAgent": true, "items": [...]}` only when its oldest queued candidate needs source-bound classification, and that `items` array contains exactly one candidate. Hermes then invokes Yanto with the `idx-market-news-watch` skill, and Yanto submits a schema-validated classification back to the launcher. User-facing output goes only to `#id-stocks-news`; run heartbeats and persistent-failure notices go to the existing `#hermes` operations channel (`1505162000420835388`).

The watcher uses Hermes’s configured model runtime. It does not invoke Claude, Codex, OpenAI, Anthropic, or any other model CLI or direct model API, and it introduces no model credential. The deterministic launcher uses the existing authenticated Telegram session, Discord credentials, and Hermes deploy pattern used by the current watcher skills.

## Provider adapters and state isolation

`PhintracoNewsAdapter` and `TuntunNewsAdapter` own source-specific discovery, normalization, and durable cursor state. Their state lanes are independent:

```json
{
  "providers": {
    "phintraco": { "highest_observed_message_id": 0, "outbox": [] },
    "tuntun": { "highest_observed_message_id": 0, "outbox": [] }
  },
  "dedupe": {},
  "digest_windows": {},
  "delivery": {}
}
```

A failure to poll, extract, classify, or retry one source must not block later candidates from the other source. The source message ID is immutable identity within a provider. A Tuntun `Corporate` message produces multiple candidate identities by adding ticker to the source-message identity.

Candidate state is durable and explicit: `discovered`, `pending_analysis`, `awaiting_agent`, `classified`, `pending_delivery`, `delivered`, `suppressed_duplicate`, `suppressed_rank`, or `discarded`. A cursor advances only after every observed source message is safely recorded as ineligible, queued, or terminally suppressed.

Before returning its single `wakeAgent` item, the launcher atomically moves that candidate from `pending_analysis` to `awaiting_agent` and stores an agent lease expiry. `submit-classification` accepts only the matching leased candidate. If the Hermes turn supplies no valid submission before the lease expires, the next launcher run moves it back to `pending_analysis`, increments its classification retry attempt, and schedules the approved bounded backoff. This prevents an interrupted agent turn from blocking later candidates or spinning every minute on the same item.

Initial deployment records current source cursors and starts only from subsequently observed messages. It never posts historical backfill.

## Candidate contract

Each candidate contains only source data and stable delivery metadata:

```json
{
  "provider": "tuntun",
  "source_message_id": 13597,
  "ticker": "DEWA",
  "source_published_at": "2026-07-01T06:18:54Z",
  "source_url": "https://t.me/tuntunsekuritas/13597",
  "source_text": "...",
  "direct_source_image": null,
  "source_kind": "corporate_entry"
}
```

A direct image is eligible only if attached to the same source message. A later media-only message, reply attachment, neighboring message, thumbnail, or inferred image is not associated with the candidate.

PDFs may be extracted privately when a source format requires it, but PDFs, extracted charts, and source-document attachments are never delivered to Discord.

## Source-bound structured model contract

The model runs only after deterministic source filtering and candidate extraction. It receives exactly one bounded company candidate. It must return validated structured output containing:

The deterministic launcher passes one queued candidate as untrusted source data in `items[]` to the Hermes agent. The `idx-market-news-watch` skill instructs Yanto to ignore all instructions in source text, classify solely from source facts, and call only `scan.py submit-classification --json '<classification>'` for each item. That subcommand validates the exact closed schema before state changes or delivery. The skill prohibits direct Discord posting, natural-language cron replies, Telegram writes, file access unrelated to the supplied item, and all investment advice.

- the existing issuer ticker;
- one closed event class;
- two to three short factual Indonesian sentences;
- source-supported material figures or dates when present;
- a closed ranking band and fact identifiers used for cross-provider dedupe; and
- an eligibility decision explaining the source evidence.

The permitted event classes are:

1. `financial_results_or_guidance`
2. `corporate_action`
3. `financing_or_ownership`
4. `mna_or_asset_transaction`
5. `material_contract`
6. `listing_legal_regulatory_or_credit`
7. `quantified_operational_execution`
8. `other_company_operation`
9. `routine_status`
10. `not_eligible`

The model must not emit recommendations, BUY/SELL language, valuation, sentiment, projected price movement, entry, target, stop-loss, or facts absent from the supplied source. Validation rejects malformed output, mismatched ticker, excessive sentence count, unsupported fields, or prohibited language. Invalid output remains pending for retry; it is never silently replaced by raw source text.

Telegram and PDF text are untrusted data, not instructions. The skill prompt must explicitly require Yanto to ignore instructions contained in the source, use only source facts, and submit only the supplied schema. A malformed submission, rejected schema, or agent failure leaves the candidate pending for bounded retry; it is never silently replaced by raw source text.

The deterministic policy maps only classes 1 to 6 to Tier 1. `material_contract` requires an explicitly disclosed material scale, such as value, capacity, duration, or output. Classes 7 to 9 are Tier 2. `not_eligible` is discarded with its reason.

For Tier 2 ranking, sort by: policy event-class weight, source-supported material scale and ranking band, then source publication time. This makes the highest-impact item appear first. The model cannot upgrade a source item beyond the policy's Tier 1 boundary.

## Cross-provider dedupe

After classification, the watcher compares candidates across providers in a 24-hour event window. It suppresses a later candidate only when issuer, event class, and source-supported event facts are a confident match. The earlier observed source wins and remains the source link shown to Discord.

If matching is uncertain, retain both events. False suppression is worse than two distinct company developments appearing in the same digest.

A substantive Phintraco `Company Flash` is not discarded merely because it concerns the same issuer. It is suppressed only when its factual event is a confident duplicate of an already queued or delivered source event. Its trade, target, and valuation content remains excluded in all cases.

## Delivery policy

### Tier 1, immediate

Tier 1 sends immediately at any time, including outside normal market hours and on weekends. It is limited to strict material disclosures:

- financial results or guidance;
- rights issues, buybacks, dividends, tender offers, and other capital or ownership actions;
- M&A, asset transactions, major financing, or material credit actions;
- quantified major contracts; and
- major suspension, delisting, legal, regulatory, or listing-status events.

A Tier 1 source image is uploaded immediately after the alert only when the exact source message includes one eligible direct image. If image retrieval or upload fails, the factual alert still delivers without an image.

### Tier 2, scheduled digests

Two delivery windows run on weekdays in `Asia/Jakarta` time:

| Digest | Scheduled time | Candidate window |
|---|---:|---|
| Pre-market | 08:30 WIB | Since the previous post-market cutoff through 08:30. Friday after-close and weekend candidates carry into Monday. |
| Post-market | 16:30 WIB | Since the pre-market cutoff through 16:30. |

Each digest is exactly one Discord message and contains at most five Tier 2 company entries. It is ranked highest material impact first. A source bundle can supply zero, one, or several entries. Lower-ranked Tier 2 candidates are marked `suppressed_rank` at the cutoff and never create overflow posts or later backlog.

Tier 1 entries never repeat inside either digest. An empty digest does not post.

## Discord format

The source link uses Discord's no-preview form and remains attached to the exact company fact.

Tier 1:

```md
### COMPANY NEWS · TIER 1

**DEWA** · [Tuntun, 13:18 WIB](<https://t.me/tuntunsekuritas/13597>)
DEWA secured a five-year mining-services contract worth about Rp22T from PT Sebuku Sejaka Coal. The contract targets up to five million tonnes of coal output a year.
```

Tier 2:

```md
### COMPANY NEWS · POST-MARKET · Tue, Jul 14

**CBRE** · [Tuntun, 18:37 WIB](<https://t.me/tuntunsekuritas/13696>)
CBRE deployed the Gunanusa Hai Long 106 for the Hidayah Field project, with execution due to start in August.

**ANTM** · [Phintraco, 07:56 WIB](<https://t.me/phintasprofits/33608>)
ANTM reiterated its nickel-downstreaming focus to support Indonesia's EV-battery ecosystem.
```

The pre-market version substitutes `PRE-MARKET`. There is no provider-first heading, group-level source footer, generated editorial label, source-preview embed, PDF attachment, or image inside a digest.

## Retry and failure policy

Every candidate and formatted Discord payload survives until terminal delivery or terminal suppression.

- Temporary Telegram, model, media, or Discord failures use bounded exponential backoff: 1, 2, 4, 8, 15, 30, then 60-minute intervals.
- A provider outage blocks only that provider's lane.
- A model failure leaves the candidate pending. There is no raw-text fallback, partial summary, or invented substitute.
- A failed Discord request retries the exact stored payload. A successful Discord response writes `delivered` before later state advances.
- A failed image upload never blocks a Tier 1 text alert.
- A persistent failure emits one deduplicated operational notice to `#hermes`, retains the candidate for recovery, and clears the notice only after successful recovery.
- `#id-stocks-news` never receives heartbeat, failure, retry, empty-digest, or diagnostic messages.

## Verification plan

Tests must exercise observable contracts, not implementation plumbing:

1. **Source fixtures:** Tuntun topic scoping, standalone ticker post, multi-company Corporate extraction, Special Topic, Phintraco Notes, Company Flash, Stock Information, and every excluded source class.
2. **Classification contract:** valid agent submission, invalid, overlong, mismatched-ticker, unsupported-fact, and prohibited-investment-language rejection; retry-safe pending state after missing or malformed agent work.
3. **Tier routing:** each strict Tier 1 class routes immediately; operational and routine issuer updates route Tier 2; unqualified material contracts do not bypass the digest.
4. **Dedupe:** known Tuntun/Phintraco duplicate issuer facts suppress the later candidate; distinct facts for the same ticker do not suppress; uncertain overlap remains separate.
5. **Ranking and cap:** strongest Tier 2 facts sort first; a source bundle can contribute several entries; exactly five are selected; overflow candidates become terminal `suppressed_rank`.
6. **Scheduling:** pre-market and post-market boundaries, Friday-to-Monday carry, no Tier 1 repeat, no empty digest, and any-time Tier 1 delivery.
7. **Formatter and media:** exact Discord Markdown, no source previews, correct inline source link and WIB time, image only for a direct Tier 1 image, no PDF forwarding.
8. **Durability:** provider isolation, cursor safety, retry backoff, process restart recovery, exact Discord replay, deduplicated operational failure notice, and no historical backfill.
9. **VPS smoke test:** both Telegram sources read with the existing authenticated session, dry-run produces no Discord post, real scheduled job registers and sends its required `#hermes` heartbeat.

## Acceptance criteria

The result is complete when a newly observed eligible issuer event from either provider is classified, deduplicated, ranked, and delivered under the policy above without manual intervention; ordinary user-facing output stays to at most two Tier 2 digest messages per weekday plus strict Tier 1 events; and all source links, timestamps, retries, and failure paths are verifiably source-faithful.
