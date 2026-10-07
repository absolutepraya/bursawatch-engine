# Shared generated-news format

`bin/news_format.py` is imported by the Telegram Market News, X, Instagram,
WhatsApp and Stockbit domain owners. It owns direct Indonesian writing and
flexible paragraph guidance, independent issuer story guidance, one
renderer-owned Ringkasan marker, native-currency prices and the four-horizon
tracker. It never classifies relevance, selects destinations or sends messages.

`get_market_snapshot` reads Yahoo daily unadjusted closes for one year. IDX
symbols use `.JK` and IDR; US exchange class separators map to Yahoo's hyphen
and prices use USD. 1D uses previous close when available, while 1W, 1M and 3M
use 5, 22 and 66 prior trading sessions only when the history's final session
matches the quote's market date in the exchange timezone. Missing metadata or
a stale history leaves those horizons unavailable while preserving the latest
quote and an explicit previous-close 1D change. A history-only quote uses its
own final session as the anchor. Missing closes retain their session positions.
Partial history preserves the latest
price and available horizons. `market_block` accepts an optional
`price_label` (default `Harga terakhir`) and `missing_marker` (default true; false
drops the grey placeholder emoji and keeps `**-**`), so existing consumers render
unchanged. Unknown or failed values use grey placeholders,
never zero. Each quote waits at most three seconds with four daemon worker
slots, and a batch stops optional quote lookup after nine seconds. A stalled
provider cannot consume an unbounded number of workers. Currency mismatch makes the optional quote unavailable. `as_of`
is the UTC quote observation time, not a claim about source publication time.

Indonesian issuer cards add an optional company context block after the price
tracker: an analyst consensus (Sectors `future.analyst_rating_breakdown`, with
`UP`, `HOLD` and `DOWN` emoji and a `DD Mon YYYY` update date) and a `Tentang`
line made of Yahoo's `longBusinessSummary` first sentence plus Sectors sector,
sub-industry and Indonesian-formatted market cap. Sectors data goes through
`lib-sectors`, never direct HTTP: one `sections=overview,future` company report
per ticker, costing 2 credits, under caller `news-context` with no configured credit limit (an explicit
`max_cost=2` is the ledger estimate). The seven-day cache is the caller-owned
ISO-week generation `news-context:<year>-W<week>`: the shared store never
refetches an identity, and a new week is a new, separately budgeted fetch. The
client reads `SECTORS_API_KEY` from `~/.hermes/bursawatch-sectors.env` (mode 0600,
beside the other Bursawatch service credentials), falling back to the package-local
`lib-sectors/.env` for Mac development, and shares `~/.hermes/state/sectors-client.sqlite3`
with a WIB-month billing window. Without the library, key file, budget or
provider data, only the Sectors lines disappear. Yahoo and each field are also
optional, absent data drops only its own line, and nothing blocks the card.
Context lookups share a nine-second batch deadline, each capped at six seconds,
so a stalled provider or injected callback cannot stall card creation. Context stays inside frozen `messages`, so the card schema is unchanged.
`freeze_cards` fetches context only when it is not given a custom `fetch`, or when
`context_fetch` is injected. Direct `render_card` callers pass `ticker` and
`context` to opt in.

`freeze_cards` records each accepted item's exact messages, source owner
selected destination, ticker and quote timestamp. Owners persist this bundle
before sending and reuse it for retries, handoff plans and feed projections.
Raw-forwarding and specialized Swing/status output remain owner contracts.
No model-generated quote tracker or style rejection is introduced.

New generated-news headlines capitalize only their first cased subject
character, after an exact issuer ticker prefix when applicable. Names,
acronyms, the remaining casing, and source bylines are preserved. This shared
normalization adds no rejection and never rewrites old frozen card messages.

`deduplicate_items` keeps the first copy of an identical news item within one
new submission. Its key is route, headline, summary, ticker and sentiment;
only whitespace and legacy summary markers are ignored. It preserves order
and distinct stories about the same issuer. Owners call it after validation,
before assigning card or child delivery identities; `freeze_cards` also guards
against duplicate input. Specialized Swing items, old frozen records and
separate source events are not collapsed.

Discord length uses UTF-16 code units, including emoji.
The renderer keeps source anchors and tracker blocks intact. It first tries
flattening summary paragraph spacing when that alone fits the card, then
splits long prose without dropping facts for owners supporting message arrays.
Telegram and Stockbit retain their existing single-message bounds.

The release manifest installs this library before consumers, with checksums.
Manual deployment, if separately approved, uses `./deploy.sh lib-news-format`
before the consumers. Runtime imports resolve either the checkout sibling or
the installed `~/.agents/skills/lib-news-format/bin` directory.

Run `python -m pytest -q tests` here with the repository environment. The suite
uses synthetic Yahoo responses and never posts or reads live production state.

Forward compatibility does not imply that an old owner binary understands
new card records. Rollback must retain compatible readers, or drain the new
records before restoring older owner code. Preserve live state and stable
operations; do not strip fields or replay the source as a rollback shortcut.

`writing_contract.py` owns common narrative rules and composable presentation
category guidance. Owners compose common rules once and select category
context without deriving it solely from a delivery route. Macro guidance
preserves figure roles, periods, units, bases, revisions, and uncertainty.
Summary style is advisory; owner schema, source-safety and transport checks
remain authoritative. The legacy `WRITING_INSTRUCTION` export stays available.

Industry guidance distinguishes reported facts from qualified company impacts
using supplied specific exposure evidence and a direct connecting mechanism.
It adds no research/discovery call or output field. Unsupported implications
are omitted while eligible news remains deliverable. Tuntun's owner selects
Industry presentation by source kind even though its accepted route is
`macro_news`; delivery and feed routing are unchanged.
