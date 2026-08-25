# Phintraco SSF Watch

This context names the Phintraco Weekly SSF Review and its Discord alert representations.

## Language

**Weekly SSF Review**:
A Phintraco multi-stock report that recommends Short or Long positions in single-stock futures for five underlying IDX equities across one-, two-, and three-month contract horizons.
_Avoid_: Weekly Swing Bundle, Swing Call, stock-pick summary

**SSF Contract Recommendation**:
One source-provided Long or Short strategy for one underlying equity and one SSF contract horizon, including its contract purchase price and technical context.
_Avoid_: buy call, target price, individual Swing Call

**SSF Strategy**:
The source-provided trade direction for an SSF Contract Recommendation: Long or Short.
_Avoid_: BUY, SELL, sentiment

**SSF Review Alert**:
A Discord presentation of every SSF Contract Recommendation for one underlying equity in a Weekly SSF Review, followed immediately by the corresponding SSF Source Chart.
_Avoid_: Swing Alert, generated recommendation, filtered long-only alert

**SSF Source Message Link**:
The public Telegram permalink for the immutable source-message ID of a Weekly SSF Review. The provider name `Phintraco Sekuritas` in an SSF Review Alert’s existing `**Source:**` footer is its Markdown anchor text, so the link adds no line or standalone label.
_Avoid_: a separate Open Message line, a link to the text announcement rather than the source PDF, a nearby Telegram post

**SSF Source Chart**:
The analyst-annotated technical chart embedded in a Weekly SSF Review PDF and associated by its stable report order with one underlying equity.
_Avoid_: reconstructed chart, inferred chart, replacement chart

**SSF Provider Tag**:
The canonical Discord prefix for a Phintraco SSF Review Alert: the `:phintraco:` custom emoji followed by `[SSF]`.
_Avoid_: `[Phintraco-SSF]`, `[Phintraco][SSF]`, `[Phintraco]`, broker tag

**SSF Alert Direction**:
The summary direction in an SSF Review Alert heading: unmarked `LONG`, `SHORT`, or `MIXED`. Each contract carries its exact source strategy as `Long:up:` or `Short:down:`.
_Avoid_: inferred conviction, a Long or Short label that omits a differing horizon
