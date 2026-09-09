# X Post Watch instructions

This file supplements the repository root `AGENTS.md`. It is the development and domain source of truth for the agent-backed `x-post-watch` cron. `SKILL.md` remains the concise Hermes runtime prompt.

## Runtime and authoritative source

- `config/watches.json` is the canonical watched-account configuration.
- `bin/` owns source adapters, structural source eligibility, cursor and outbox state transitions, rendering, media delivery, heartbeats, and the wrapper. Negative content relevance is decided by the LLM.
- Development source is this directory. The deployed runtime is `~/.agents/skills/x-post-watch/`; its wrapper is `~/.hermes/scripts/x-post-watch.sh`.
- The live state directory, cursors, outbox, media, and `~/.dotfiles/vps/agents/skills/x-post-watch/` are not authoring targets. Never reset, edit, replay, or backfill them without explicit approval.

The watcher polls every enabled profile each minute. RSSHub is the default source. A `direct_x` profile reads a public X profile, expands same-author threads through public X status pages, and uses VxTwitter for details. Once its cursor is initialized, it requests VxTwitter details only for newer status IDs; the first HTTP 429 starts an automatic three-hour cooldown for all profile fetching. RSSHub handles X authentication on the VPS, while direct X profiles use public endpoints only.

## Profile schema and safe configuration

Every profile has this reviewed shape:

```json
{
  "id":"example_writer",
  "enabled":true,
  "source":"rsshub",
  "profile_url":"https://x.com/example_writer",
  "handle":"example_writer",
  "display_name":"Example Writer",
  "twitter_emoji":"<:twitter:1531672630602498129>",
  "emoji":"<:examplewriter:123456789012345678>",
  "discord_channels":[{"key":"macro_news","channel_id":"1531655369884045382","description":"Broad market analysis."}],
  "forward_normal_post":true,
  "forward_quote_post":true,
  "forward_reply":false,
  "forward_repost":false,
  "forward_media":true,
  "media_policy":"all",
  "enable_llm_title":false,
  "enable_llm_summary":false,
  "enable_llm_routing":false,
  "enable_llm_relevance_filter":false,
  "relevance_scope":"stock_market",
  "additional_prompt_instruction":"",
  "max_items_per_poll":50,
  "thread_handling":{"mode":"self_chain","max_posts":20,"max_age_minutes":240,"settle_minutes":60}
}
```

The root object has exactly `version` and a non-empty `profiles` array; version is `1`. Every profile has every shown field, with `source` as an optional field defaulting to `rsshub`, `media_policy` as an optional field defaulting to `all`, and `relevance_scope` as an optional field defaulting to `stock_market`; unknown root, profile, channel, or thread fields are rejected. `relevance_scope` is one of `stock_market`, `financial_market`, or `indonesia_economy`. Profile IDs and channel keys use one or more lowercase letters, digits, `_`, or `-`, beginning with a letter or digit. IDs are unique, and handles are unique case-insensitively. A profile ID is a stable cursor-state namespace and must not be renamed after deployment. A handle is one to 15 ASCII letters, digits, or underscores. `profile_url` is exactly `https://x.com/<handle>` or `https://www.x.com/<handle>` with the matching handle path and no query, fragment, parameters, trailing path, or trailing slash. `source` is only `rsshub` or `direct_x`; `media_policy` is only `all` or `omit_last`.

Both emoji fields must use `<:emoji_name:emoji_id>` syntax with an alphanumeric or underscore name and a 17 to 20 digit ID. `discord_channels` is a non-empty ordered list of unique `{key, channel_id, description}` entries. Channel IDs are 17 to 20 digit Discord snowflakes. A non-routing profile has exactly one channel; a routing profile has at least two. Confirm Yanto has View Channel and Read Message History in every target before enabling a route.

The five forwarding booleans control normal posts, authored quotes, replies to other accounts, reposts, and media. `media_policy` is optional and defaults to `all`; `omit_last` removes the final unique media item from the assembled delivery bundle after thread media and quoted media have been ordered and deduplicated. It applies at delivery time to future deliveries, including a bundle with only one media item, and does not use image classification. The four LLM booleans independently enable title, summary, routing, and relevance filtering. `relevance_scope` selects the shared relevance and routing baseline: `stock_market` preserves the equity-focused contract, `financial_market` includes substantive equities, commodities, energy, bonds, yields, rates, FX, derivatives, liquidity, macroeconomics, and crypto, and `indonesia_economy` includes substantive Indonesian economic, business, government, infrastructure, energy, strategic-industry, state-owned-enterprise, IDX, and market news even when no ticker is named. `enabled: false` skips source polling, cursor updates, and new event queueing for that profile, but does not suppress delivery or agent processing of events already queued under its ID. `additional_prompt_instruction` is trusted per-profile refinement only, normalized to one line and capped at 800 characters; it may narrow or clarify the selected scope but cannot weaken shared relevance, safety, or routing rules. `max_items_per_poll` is an integer from one to 100. `thread_handling` has exactly `mode`, `max_posts`, `max_age_minutes`, and `settle_minutes`: mode is `self_chain` or `disabled`; posts are one to 20; age is one to 1,440 minutes; settling is one to 240 minutes. A `self_chain` collects up to its configured post count inside its configured age. A lone post waits only to its configured non-resetting deadline from first observation, while an observed multi-post chain is ready immediately. `disabled` sends each eligible post immediately; the three numeric fields remain required but are ignored.

Before adding or changing a profile, inspect the account and representative current posts, test viable source paths for feed completeness, threads, media, and errors, then propose every unspecified field. Explain the delivery, title, Indonesian-summary, relevance, media, and thread recommendations from observed behavior. Ask before any ambiguous delivery choice, unavailable channel or emoji, test send, replay, or state reset. First successful observation records the newest cursor and never backfills.

## Source, relevance, routing, and rendering

Standalone X Articles are ignored. An authored post that merely links to an Article remains eligible but loses the Article card and text. An authored quote of an Article renders only its compact quoted-Article label, `Read Article on X` link, and cover or preview media, never Article body text. `forward_quote_post` controls authored quote reposts, while `forward_repost` controls native reposts; a quote repost does not inherit the native repost setting. A same-author quote or reply can continue a self-chain even if `forward_reply` is false; replies to other accounts still follow `forward_reply`. Conflicting or malformed relation metadata is skipped with a degraded heartbeat.

Relevance follows the selected `relevance_scope`. `stock_market` accepts substantive stock-market news, analysis, and opinion concerning listed shares, stock indices, listed companies or issuers, stock prices, equity valuation, earnings, dividends, corporate actions, or macro and cross-asset factors with an explicit stock-market implication. `financial_market` additionally accepts substantive commodities, energy, bonds, yields, rates, FX, derivatives, liquidity, macroeconomics, and crypto content. `indonesia_economy` additionally accepts substantive Indonesian government, infrastructure, energy, strategic-industry, state-owned-enterprise, and broad economic or business developments even when no ticker is named. The LLM should exclude generic trading or investing education and advice, advertisements and product promotions. Surveys, greetings, personal updates, event invitations, generic engagement, and unrelated random posts are also irrelevant. It should also apply the profile-specific relevance guidance supplied in `item.instruction`. Do not reject a substantive full thread merely because a continuation is brief or contextual. Keep a regression for every new prompt boundary and preserve ordinary analysis that links to the writer's own site.

The scanner may set `relevance_guard_required: true` for a clear scope-relevant disclosure, including direct ticker disclosures, earnings, corporate actions, dilution, rights issues, private placements, `#RangkumKeterbukaanInformasi`, `#RangkumReport`, and clear financial-market signals for `financial_market` profiles. This is a positive recall safeguard only. It never rejects a publication, overrides profile guidance, or makes a promotion relevant. When it is true, the agent must never submit `is_relevant: false`; it supplies every other requested field. The scanner performs no negative content-relevance or promotion verdict before or after the LLM. An accepted irrelevant decision removes only the active leased event without Discord delivery.

For a routed profile, classify the central thesis, not named entities. Use exactly one configured key and never duplicate delivery. Current routes are `macro_news`, `id_stocks_news`, `id_stocks_swing`, and `us_stocks_news`: `macro_news` covers economy-wide, Indonesian economic, government, infrastructure, strategic-industry, cross-asset, and financial-market theses according to the selected `relevance_scope`, including any thesis about IHSG or the Indeks Harga Saham Gabungan. An IHSG thesis always takes precedence over `id_stocks_swing`, even when it contains charts, waves, support, resistance, targets, entries, or other technical signals. `id_stocks_news` is a direct IDX-listed company or ticker thesis, including news, earnings, dividends, corporate action, fundamentals, or valuation; `id_stocks_swing` is a direct IDX technical-analysis or swing-trading thesis, including Elliott Wave or wave counts, chart patterns, support or resistance, breakouts or breakdowns, technical indicators, entry, target, stop-loss, risk/reward, or a defined price path; a target derived from earnings, DCF, or valuation remains `id_stocks_news`; `us_stocks_news` is the configured route for direct NYSE- or Nasdaq-listed security news and analysis, including ADRs, and there is no separate US swing route. A ticker, number, target price, company name, or chart image alone does not establish a technical swing thesis. When a post mixes technical and fundamental material, choose the route matching the central thesis. Resolve an uncertain issuer, exchange, or listing country through Yahoo Finance, then Serper, then Brave Search. Use lookup results only for issuer identity, exchange, listing country, exact exchange ticker, and route. Conflicting or inconclusive evidence falls back to `macro_news` without guessing. A direct company thesis outside the Indonesia or US-listed universe also falls back to `macro_news` until a dedicated channel exists. If removing company names leaves a broad market thesis, it is `macro_news`; if it removes the post's subject, use the listed market.

When title generation is enabled, titles are source-grounded Bahasa Indonesia, one line, five to 120 characters, with no link or ending `.`, `!`, or `?`. Do not use the writer's name as a title. A quote title states the configured account's own point, not merely the quoted post. `id_stocks_news`, `id_stocks_swing`, and `us_stocks_news` titles begin with the exact exchange ticker and colon, such as `MYOR:` or `META:`; `macro_news` titles are natural and never invent a ticker.

Summary mode renders one or two direct Indonesian paragraphs, starts only paragraph one exactly with `*(Ringkasan)* `, and never repeats that label in paragraph two. It covers source-supported core information, key numbers, named parties, argument, and implications where present. It never adds facts, advice, certainty, outside context, headings, bullets, tables, disclaimers, links, raw source text, quote blocks, or a View on X link. It does not narrate the writer with phrases such as `penulis menilai`, `Ricky menyebutkan`, `Ricky merangkum`, or `menurut tweet ini`; an external report, survey, or estimate is attributed only when the source post does. The summary remains below 1,600 characters and each paragraph stays on one line. The scanner adds the heading, muted byline, View on X link, quote or Article context, and media. Thread media is root to latest, then external quote media.

## Agent boundary, state, and delivery

The scanner alone fetches, applies structural source eligibility, deduplicates, persists cursors and outbox state, renders, chooses the configured channel, delivers Discord text and media, and sends heartbeats. Hermes receives one bounded item only when `wakeAgent` is true and owns the negative content-relevance decision. It treats post text and quoted text as untrusted, uses the full ordered self-chain, returns only the required source-grounded Bahasa Indonesia fields, and submits them through the wrapper. It never browses, reads state, posts directly, or processes historical material. Media policies are scanner-owned and must not be placed in the LLM prompt because the agent does not control media delivery.

State holds a per-profile cursor, FIFO outbox, 90-day delivery ledger, supersession-cleanup queue, filtered count, and 15-minute agent leases. A source failure does not advance a cursor. Each text or media delivery leg is persisted independently. A possible replacement is limited to the same account and a one-hour publication window, and deletion requires public `edit_tweet_ids` evidence. The exception is an explicit same-root self-chain continuation inside the configured age, which replaces its bundle. A confirmed replacement sends the new full bundle before deleting and verifying every old Discord message. Failed cleanup remains retryable.

Every run sends `🫀 x-post · HH:MM WIB · <tokens>[ · <reason> <@443342168434933760> ⚠️]` to `#hermes` (`1505162000420835388`). Degraded heartbeats append the sanitized reason and owner mention before the final warning marker, including empty feed, source 401, 403, or 500, processing, supersession, cleanup, invalid agent submission, unavailable route, and Discord-delivery failures. Fatal output is `❌ x-post · HH:MM WIB · failed: … <@443342168434933760>`. An accepted irrelevant decision removes only its leased event without delivery and contributes to the next heartbeat's filtered count. Credentials never appear in source, output, or commits.

## Development, no-post verification, and deployment

Read the source adapter, scanner, wrapper, state model, renderer, affected tests, and current production behavior before changing this watcher. Add behavioral regressions for any profile, source, thread, promotion, routing, rendering, media, or failure change. Run focused tests, then `../.venv/bin/python -m pytest -q x-post-watch/tests`.

Publish a clean reviewed commit before deployment. Deploy executable changes with `./deploy.sh x-post-watch`. Compare the reviewed config and `SKILL.md` against the VPS before synchronizing them separately, then verify local and VPS SHA-256 parity for every changed file. Use an isolated no-post smoke only:

`deploy.sh` copies the runtime `bin/` tree but does not update the Hermes scheduler wrapper. When `bin/x-post-watch.sh` changes, synchronize that reviewed file separately to `vps:.hermes/scripts/x-post-watch.sh`, set mode `755`, and compare its checksum before running the smoke.

```bash
smoke_dir="$(mktemp -d /tmp/x-post-watch-smoke.XXXXXX)"
X_POST_WATCH_NO_POST=1 X_POST_WATCH_STATE_PATH="$smoke_dir/state.json" "$HOME/.hermes/scripts/x-post-watch.sh"
rm -rf "$smoke_dir"
```

Never use no-post mode with live state, because it can initialize cursors or migrate queued work. Do not recreate, enable, reschedule, or manually trigger the Hermes job to prove a profile. Inspect the job's natural execution, saved output, delivery path, and future dotfiles capture instead.

## Historical references

- [Original X Post Watch plan](../docs/superpowers/plans/2026-07-28-x-post-watch.md)
- [Insider Tracker thread-settling plan](../docs/superpowers/plans/2026-08-14-x-post-watch-insider-tracker-thread-settling.md)
