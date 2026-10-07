# Morning brief simplification rounds

The user requested a quick, one-problem-at-a-time grilling round on 7 October,
prioritizing a straightforward implementation and allowing a replacement for
Sectors. The user chose Yahoo as the primary numerical source, subject to
verification before production. Existing default timing, price-return basis, membership references,
coverage rule and shared delivery ownership remain settled.

## Problem 1: numerical market-data source

### Facts checked

- Yahoo access through `yfinance` is an unofficial, unaffiliated client. The
  [maintainer README](https://github.com/ranaroussi/yfinance) identifies personal
  use and directs consumers to Yahoo's data terms. There is no basis to promise
  unlimited access; the [client source](https://github.com/ranaroussi/yfinance/blob/main/yfinance/exceptions.py)
  explicitly handles rate-limit errors.
- Yahoo distinguishes ordinary historical Close from Adj Close. Its
  [adjusted-close explanation](https://help.yahoo.com/kb/SLN28256.html) describes
  split and dividend adjustment. The [yfinance adjustment implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/utils.py)
  replaces Close with Adj Close under automatic adjustment. The candidate
  configuration is explicit `auto_adjust=False` and ordinary Close, with
  representative split/dividend validation rather than an assumption about a
  library default.
- The retained 4 October sample has usable closes for all 188 mapped conglomerate
  stocks over the 18 sampled IHSG dates. It does not prove current access, the
  complete sector universe or cap coverage. The sample has no collected caps.
- The [market-cap implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/quote.py)
  can derive current cap from latest shares and last price. A returned value is
  not automatically an authoritative historical cap. A weekly collected
  snapshot remains distinct from a verified economic effective date.
- Yahoo market-data access does not establish official IDX classification,
  trading eligibility, holidays, conglomerate ownership mappings or primary
  BI/BPS releases. Retain the existing membership references and primary-source
  calendar/agenda boundaries. Prices also do not replace the approved rendered
  chart profile.
- Free client access does not grant data-publication rights. This source switch
  cannot itself settle the applicable Discord distribution terms.

### Accepted decision

The user answered "yes lets go" to choosing Yahoo as the candidate primary
price/cap source. Use one shared cached Yahoo adapter for numerical prices and
evaluate Yahoo weekly cap snapshots. Retain the existing sector membership import, conglomerate
CSV and official calendar/agenda sources. No automatic provider switching,
made-up caps, guessed price adjustments or missing-price zero fills. Decide cap
failure policy in the next round. This decision does not certify data coverage,
price adjustments or production readiness. It does not require rewriting other
watchers or removing the shared Sectors library from unrelated consumers.

## Problem 2: incomplete Yahoo cap snapshots

### Facts checked

The agreed rotation calculation requires a valid cap for every mapped basket
member before measuring 90-percent price coverage. A missing cap makes the
coverage denominator unknown; excluding that stock is not a verified workaround.
The existing snapshot age policy allows a prior-week snapshot for one extra
week, then expires it. Unsupported baskets are omitted independently of the
rest of the morning brief.

### Accepted decision

The user answered "oh yeah lets do it" to cache-then-omit behavior. Use a
complete valid cached basket snapshot within the existing age policy when
the weekly Yahoo refresh is incomplete. Otherwise omit the affected basket,
disclose its unavailability and continue the other brief sections. Do not
substitute equal weights, invent caps or automatically query Sectors.

### Full native cap check and confirmed omission policy

On 7 October, twelve bounded public Yahoo requests (two guest-session calls
and ten exact quote batches) returned valid native IDR caps for 917 of the fixed
962 stock symbols. All 34 conglomerate baskets had complete caps. Each of the
11 sector baskets lacked at least one native cap. The private retained responses
are validation inputs, not production snapshots or price-coverage proof.

The user explicitly confirmed keeping Yahoo and omitting unsupported sectors.
Do not replace missing native caps, remove members from the fixed mapping or
automatically spend Sectors credits. The bounded producer now retains native
quotes and daily action/trading evidence with restart-safe chunking, per-basket
cap fallback and the original age/90-percent coverage rules. Activation and
natural delivery remain separate verification work.

## Problem 3: IHSG chart dependencies

### Facts checked

The previous primary image design used a dedicated TradingView layout rendered through
the shared Chart-IMG component: three months of daily candlesticks, LuxAlgo
Smart Money Concepts swing structure and recent order blocks, plus RSI(14)
with confirmed regular divergence. It has no Volume panel. The existing
fallback is a verified simple current chart, then omission of the image.
The retained readiness checkpoint had no accepted chart proof/cache.
Yahoo's daily historical endpoint supplies OHLC, so candles and locally
calculated moving averages/RSI can share a single historical data fetch. The
[history reference](https://github.com/ranaroussi/yfinance/blob/main/doc/source/reference/yfinance.price_history.rst)
supports daily intervals and a one-year history window. The
[rate-limit exception](https://github.com/ranaroussi/yfinance/blob/main/yfinance/exceptions.py)
confirms that Yahoo can reject requests as too many requests. Local indicator
calculations do not require additional provider requests.

### Accepted decision

The user chose "full yahoo" for the IHSG image and specified candlesticks,
MA 10/20/50/100 and RSI. Generate the image locally from the shared cached Yahoo
`^JKSE` daily OHLC snapshot. Interpret MA as simple moving averages of Close;
retain the previously agreed RSI(14), using Wilder smoothing. Keep the
three-month visible window, branded presentation and absence of Volume. This
supersedes the LuxAlgo Smart Money Concepts and regular-divergence overlays for
this image. It does not change unrelated Chart-IMG consumers.

Fetch enough earlier sessions to calculate MA100 throughout the visible window,
with one year as the initial history request window. Verify actual session
coverage rather than assuming a calendar duration supplies enough bars. Retain
the warm-up history while displaying only the chosen three months. Reuse this
snapshot for numerical IHSG consumers and render all indicators locally.

Use bounded collection with a shared cache and rate-limit cooldown, rather than
repeated per-indicator or per-preview calls. Rate limits remain possible; this
decision does not assert an unlimited quota or verified current endpoint access.
Price provenance, completed-session alignment and cutoff verification still
apply. A cached chart is usable only if its data ends on the required latest
verified session. Otherwise omit the image and continue the brief.

### Implementation scope

The user's "ok lets do it" authorizes implementing the settled chart branch.
The morning collector shares its retained IHSG history with a local renderer
and a reusable Yahoo OHLC/indicator library. This does not itself implement the
full price/cap migration, complete other rollout producers or activate a job.
Remaining simplification rounds stay open independently of this chart work.

Local verification collected two bounded Yahoo responses on 7 October and
rendered 65 actual daily candles through 6 October with 180 aligned history
sessions for indicator warm-up. The responses arrived after the scheduled
morning cutoff, so the generated output is explicitly a visual preview, not a
live morning manifest. The in-progress 7 October candle is excluded. Yahoo's
null holiday placeholders are filtered by the official IDX calendar, while
missing/null candles on required trading sessions reject the image.
