# Instagram profile onboarding and source recovery

Status: accepted

## Context

`instagram-post-watch` needs to watch public posts and reels from five profiles:
`beyondthefundamental`, `investart_id`, `avenirresearch.id`, `acresresearch`,
and `sectorsapp`. Instagram's web profile-info endpoint currently returns the
same deleted business-profile schema error for two of those public profiles,
while their authenticated feed endpoint returns usable publication data.

New profile activation also must not turn the RSSHub window into historical
backfill. The first successful observation needs to establish a durable cursor
without downloading media, running OCR or the LLM, delivering to Discord, or
advancing through old publications.

## Decision

- Keep all five profiles in the reviewed JSON configuration with stable IDs.
  The dotted handle `avenirresearch.id` uses the normalized state ID
  `avenirresearch_id`; the handle and canonical profile URL remain exact.
- Reuse the reviewed `macro_news` and `id_stocks_news` destinations. All
  profile-specific content refinement stays in `additional_prompt_instruction`
  and remains an LLM relevance decision, not a deterministic negative filter.
- Keep profile activation future-only. A valid initial source page records its
  newest publication as the cursor and performs no OCR, LLM wake, delivery, or
  replay. Existing live cursors and delivery state are not reset.
- Keep the watcher itself RSSHub-only. The dedicated `rsshub-instagram`
  dispatcher may recover only this exact sequence:
  `web_profile_info` returns HTTP 400 containing Instagram's deleted
  `business_category_subvertical` schema message, then the same handle's feed
  endpoint returns a valid JSON object with an items array and a user object
  containing an ID. It synthesizes the minimal guest-compatible `{data:{user}}`
  shape expected by the existing RSSHub route, including its timeline edges,
  and lets that route render the feed normally.
- For every other status, endpoint, profile, or malformed feed response, the
  original response is preserved. The dispatcher does not scrape HTML, switch
  platforms, bypass the configured residential proxy, or expose credentials.

## Consequences

- Public business profiles affected by this provider schema regression can use
  the existing RSSHub route without adding a second Instagram scraper.
- Source readiness remains an exact route test, not a `/healthz` result. A
  profile is not considered ready unless its configured route returns a valid
  feed that the watcher parser accepts.
- The fallback depends on the same authenticated headers, cookie, and proxy as
  the normal RSSHub request. If Instagram changes either endpoint or error
  contract, the route reports unavailable and does not silently guess.
- New accounts remain quiet at activation time. Only publications observed
  after the seeded cursor can enter OCR, LLM relevance, and Discord delivery.

## Verification

Test the dispatcher pure helpers locally, probe every configured route through
the isolated container, compare the deployed source checksum to the reviewed
source, and inspect the first natural Hermes execution. Do not reset live state
or manually replay the initial feed.
