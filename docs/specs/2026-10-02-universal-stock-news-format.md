# Universal stock-news format discussion

Status: approved by the user. Independent issuer developments become separate
cards with one tracker per issuer. The local implementation shares generated
news presentation across the five domain owners; verification and release
remain distinct from design approval.

## Objective

Use one stock-news presentation contract across Telegram, X, WhatsApp,
Instagram, and Stockbit/RSS. Share direct Indonesian reporting, a flexible
two-paragraph preference, one renderer-owned Ringkasan marker, deterministic
prices and 1D/1W/1M/3M changes, unavailable-value placeholders, and source
provenance. Style and quote availability must not introduce new delivery
blocking. Preserve source-supported research attribution and uncertainty.

The user's existing reliability decision carries forward: paragraph thresholds
remain flexible and style violations do not block eligible news. Common
presentation must not silently change source selection or routing rules.

## Checked-in source findings

These are source-code findings from the `telegram-news-summary` worktree,
not a current production inventory or a release verification.

| Domain owner | Summary and rendering | Price tracker |
| --- | --- | --- |
| Telegram Market News | Shared issuer renderer for Phintraco and Tuntun; the local change preserves paragraphs | Existing deterministic four-horizon IDX block |
| Stockbit | Separate renderer and protocol; protocol text normalization currently flattens paragraphs | Existing separate four-horizon IDX block, with different percentage punctuation |
| X | Separate summary protocol and renderer; supports IDX, US, macro, and swing routing | No four-horizon block in the news renderer |
| WhatsApp | Separate renderer; independent news items, industry/macro routes, and a special technical-review path | No four-horizon block in ordinary news rendering |
| Instagram | Separate protocol and renderer with caption/media handling | No four-horizon block in the news renderer |

Source adapters own intake and dispatch, while these domain owners own analysis
and publication. A universal format belongs in the domain owners' shared news
layer, not in the platform intake adapter or Discord transport service.

X, WhatsApp, and Instagram summary validators currently enforce paragraph and
Ringkasan-label shape. Their news paths must be reviewed for compatibility with
the user's flexible style policy, rather than copying those hard checks into a
shared formatter.

X, WhatsApp, and Instagram also reconstruct text for delivery and publication
projection. Inserting a live quote lookup into each reconstruction could
change a retry's payload digest under the same operation key. Quote enrichment
must therefore be frozen with the first prepared card, and retries and feed
projection must reuse that exact representation. Stockbit already freezes its
rendered content before delivery. Existing owner state, credentials, and
transport boundaries remain authoritative.

## Proposed shared responsibilities

1. A shared news-writing instruction fragment is composed into each owner's
   existing classifier prompt. Platform parsing, relevance, route selection,
   evidence rules, and supported analysis remain source-specific.
2. A common news item carries summary prose, source provenance, route, and
   identified security metadata. Adapters accommodate existing marker-prefixed
   summaries without introducing another label or a schema-based style gate.
3. Shared deterministic market enrichment and one card renderer own quote
   presentation, four horizons, placeholders, whitespace, and length fallback.
   Prices are never model-generated. Market lookup failure degrades the price
   block while preserving eligible news.
4. Each domain owner persists the prepared representation before its first
   Delivery Owner submit. Delivery retries and Published Feed projection reuse
   it without another quote fetch, model call, or reformatting.
5. Adopt the new contract forward-only. Preserve existing submitted payloads
   and their retry keys. Live release, existing queued-work compatibility, and
   natural-output verification require a reviewed implementation plan.

Common presentation does not imply a common ban on research vocabulary. For
example, X issuer analysis can include source-supported valuation or targets
that Telegram's current classifier excludes. Preserve route and source-policy
semantics instead of applying Telegram's entire classification protocol to
every platform.

## Design tree

Settled prerequisites: common presentation across platform sources, flexible
paragraph guidance, deterministic prices, reliability priority, and preserved
source provenance and delivery ownership.

1. Market scope, accepted: cover IDX and US stock-news routes, using IDR
   and USD respectively, without converting prices into another currency.
2. Card heading, accepted: ticker-plus-headline heading with a
   provider/account byline.
3. Multi-company stories, accepted: distinguish independent issuer developments
   bundled in one publication from a single connected story with several
   companies. The LLM emits one item per independently
   supported issuer development. Each receives its own title, factual summary,
   deterministic tracker, and original source link. A connected transaction
   or broad thesis must not be multiplied just because it names other issuers.
4. Raw-forwarding settings, accepted: preserve explicit profile settings;
   universal generated news cards do not silently enable summarization on a
   profile configured for raw forwarding.
5. Education relevance, required by the user: generic education must be
   excluded through the LLM's semantic judgment. Deterministic keyword or
   ticker matches must not force an education post to be relevant.

The local implementation below covers delivery bundle sizing, per-item
identity, source-specific analysis compatibility, and forward-only queue
adoption. Production rollout remains separately approved.

## Source examples checked through RSSHub

On 2026-10-02 at about `12:58 WIB`, RSSHub health returned HTTP 200.
`/twitter/user/doktermarket?format=json` returned HTTP 200 with 18 items,
including both requested publications. These are returned feed contents,
not independent verification of company disclosures.

- [GIAA and UNTR](https://x.com/doktermarket/status/2105815114746360162):
  two independent issuer developments, a GIAA rights issue and a UNTR
  buyback. Recommend two issuer cards. The feed itself contains an incomplete
  buyback budget, `Rp triliun`; do not invent a number or repeat that malformed
  amount as a quantified fact. Preserve the supported maximum 20% detail.
- [Dividends, rights issue, and reopened suspensions](https://x.com/doktermarket/status/2105815054771970383):
  DADA and NICL have separate dividend events; ENRG has a rights issue;
  SINI, SMMT, and SONA each have a reopened-suspension update. Recommend six
  concise issuer cards rather than making DADA the lead issuer of unrelated
  developments. One sentence is sufficient when that is all the source
  supports. All six retain the same original source link and source date.

This expands the current X one-post/one-analysis contract into bounded news
items. It is a deliberate owner/schema change, not only title rewording. Stable
item identities, frozen ordered items, independent retry receipts, and complete
source-to-item projection need regressions before adoption.

## Education-filter finding

The user supplied [Discord message 1554807697709342814](https://discord.com/channels/940285152335110204/1531655369884045382/1554807697709342814).
Read-only Discord retrieval confirmed that it presents Ricky Ho's general
fundamental-versus-chart investing lesson as a macro alert.
`/twitter/user/rickyho_1989?format=json` returned HTTP 200 with 18 items,
including [the original post](https://x.com/rickyho_1989/status/2105247932639539305).
That source discusses investment methods and professional judgment rather than
a concrete issuer development or a substantive current market event. Under
the stated education exclusion it should receive an LLM irrelevant verdict.

Current X instructions already exclude generic investing education. However,
`agent_protocol.requires_relevance()` can set a mandatory positive guard based
on market words, `instruction_for()` tells the LLM never to return false for
that guard, and `scan.py` rejects a submitted false verdict when the guard
matches. An isolated local check using the exact RSSHub-returned source and
checked-in Ricky profile returned `guard_on_exact_rss_text=True` and
`prompt_forbids_irrelevant_decision=True`.

This proves a current code conflict with LLM-owned relevance. It does not prove
the original accepted analysis or exact deployed source context caused the
historical delivery. The guard rejects an irrelevant submission; it does not
automatically turn it into a delivered relevant message. Instagram has a
similar guard, and WhatsApp's technical-review path has a relevance override;
each needs a source-specific compatibility review.

Recommended correction: market signals may provide advisory context, but the
LLM can exclude education or promotion despite those signals. Preserve full
source/thread/article evidence for that decision. Keep schema, lease, source
eligibility, capability, and security-identity checks deterministic. Do not add
a deterministic education denylist. Test both education containing tickers or
earnings vocabulary and substantive issuer/market research, including an
isolated LLM evaluation as well as tests that submission honors its verdict.

The required read-only production snapshot preceded these observations at
`2026-10-02T12:58:42+07:00`, with main and last successful release at
`6c64a24dd5f79c20a658070ed3c978db63c55636`. It does not establish incident
causation, runtime checksums, or the success of this source correction.

## Reliability and rollout requirements

The shared contract covers generated issuer news across the listed platform
owners, including IDX and US routes. Macro and industry summaries share the
reporting shell when adopted but have no arbitrary issuer tracker. Existing
source-specific technical and status contracts require explicit integration
review; changing news format does not silently change them or profile flags.

Introduce compatible adapters and validate each owner before adoption. Freeze
the exact ordered news items, quotes, rendered messages, source links, and
operation identities before first delivery; projection reads that same bundle.
Keep pending legacy payloads on their original contract, without replay or
rewriting. Quote failures use placeholders and paragraph style does not block
delivery. Preserve existing destinations, cadence, media handoff, capability
gates, and owner boundaries. Run focused, package, and full repository checks,
then review the release and first natural output for each adopted path. Passing
synthetic tests reduces regression risk but cannot guarantee zero live issues.

Terminology is recorded in the [shared stock-news glossary](../glossaries/stock-news.md).

## Local implementation

`lib-news-format` is the shared source and runtime dependency. It supplies
writing and splitting guidance, summary normalization, native-currency Yahoo
snapshots and the renderer. New X/Instagram item-array schemas are additive;
legacy scalar responses stay accepted. WhatsApp retains its original array.
Stockbit split articles create independently checkpointed child records with
original source provenance. Telegram's existing per-candidate intake remains
intact and both providers request generated headlines.

New social news cards freeze content, quote observation timestamp and selected
destination before the first delivery operation. Projection and operator
handoff paths reuse those cards. Old pending payloads keep their legacy path.
Source schemas, capability gates and specialized Swing/status paths are
preserved. Quote failures render placeholders and paragraph style never
changes LLM relevance. X/Instagram/WhatsApp market-word guards are advisory;
false LLM relevance decisions are accepted even with a positive lexical hint.

Validated new submissions collapse identical news items before assigning
delivery or child identities, preserving the first copy and source order.
Only whitespace and legacy summary markers are ignored when comparing route,
title, summary, ticker and sentiment. Distinct stories about the same issuer,
old frozen records, and separate source events remain separate. Stockbit run
completion checks every split child: pending receipts keep the run degraded
until all children are delivered or excluded, without changing owner retries.

The shared library is a checksum-verified runtime dependency in the release
manifest, installed before its consumers. No scheduler, service, destination,
production state, or credentials are changed by local development.

## Validation and rollback boundary

The complete local `bash scripts/test-all` run after review corrections and
integration of the latest main passed with 2,840 Python tests
and 13 JavaScript sink tests. One optional PostgreSQL integration test was
skipped because its existing database environment variable was absent.
Focused consumer suites, release dependency ordering, repository policy and
`git diff --check` also passed. Synthetic tests cover independent issuer
cards, native currencies, unavailable and partial quotes, lossless bounded
rendering, education decisions, frozen retry payloads, publication identities,
source provenance, X cleanup across destinations, frozen WhatsApp handoffs with
partial receipts, and quote-session alignment with missing history values.
They also cover duplicate removal before child or card identities, preservation
of distinct stories and old frozen cards, and split-child completion reporting
for pending, delivered, and excluded outcomes.
The root child-instruction index includes the new shared library. These tests do not establish
live model accuracy or a production source-to-delivery result.

Compatibility is forward-only: the new owner readers accept old records and
old leased scalar schemas; existing saved delivery payloads stay unchanged.
Older Instagram readers reject the new optional card field, and older
Stockbit readers reject split-parent records. For rollback, retain compatible
owner readers and the shared library, or drain the new-format outboxes before
restoring older owner binaries. Do not rewrite live state, reset cursors,
replay source events, or silently discard pending independent items. A future
release needs the normal published-main, CI, checksum and natural-run checks.
No runtime deployment, schedule change, state migration or external test post
was performed during this local change.
