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
price and available horizons. Unknown or failed values use grey placeholders,
never zero. Each quote waits at most three seconds with four daemon worker
slots, and a batch stops optional quote lookup after nine seconds. A stalled
provider cannot consume an unbounded number of workers. Currency mismatch makes the optional quote unavailable. `as_of`
is the UTC quote observation time, not a claim about source publication time.

`freeze_cards` records each accepted item's exact messages, source owner
selected destination, ticker and quote timestamp. Owners persist this bundle
before sending and reuse it for retries, handoff plans and feed projections.
Raw-forwarding and specialized Swing/status output remain owner contracts.
No model-generated quote tracker or style rejection is introduced.

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
