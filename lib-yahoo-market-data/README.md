# Shared Yahoo market data

`yahoo_market_data` supplies reusable, pure validation of native Yahoo daily
OHLC records and local simple moving averages and Wilder RSI. Python 3.11 or
newer is sufficient; no additional dependencies are required.

Add `lib-yahoo-market-data/bin` to the consumer import path. `parse_daily` checks
the exact symbol, exchange timezone and daily interval, rejects duplicate or
unordered bars and invalid prices, and excludes dates after an explicit final
session. An explicit `session_dates` set filters non-session rows before OHLC
validation, so Yahoo's null holiday placeholders do not become missing trading
candles. Missing/null prices on required sessions remain errors. It uses ordinary
OHLC rather than dividend-adjusted Close. It does not
certify official sessions, corporate actions, publication rights or price-return
compatibility for basket calculations.

`parse_closes(payload, symbol=, exchange_timezone=, through=, session_dates=)`
returns ordinary daily closes keyed by explicit session date, keeping null or
invalid closes as `None` instead of dropping the session. `close_performance(closes,
sessions=, through=)` computes the latest close and 1D, 1W, 1M and 3M changes
against exactly 1, 5, 22 and 66 prior verified sessions. A missing anchor leaves
that horizon `None` rather than sliding to an older close. Both are pure and make
no requests.

`latest_close.fill_latest_close(payload, session_start=, session_end=, intraday=, previous_close=)`
returns a copy with the one null close of the latest completed session filled, plus a `repair`
record naming the method, or the original payload and `None`. It accepts only evidence that
agrees with the bar: the response's closing-window market price (day high, low and volume must
equal the bar's), an hourly series confirmed by that price, or the previous close of a later
one-day chart. It never fills an interior gap and never mutates its input.

`simple_moving_average(closes, period)` returns an aligned tuple with `None`
during warm-up. `wilder_rsi(closes, period=14)` seeds with the first period's
average gains/losses and uses Wilder smoothing thereafter. Flat windows return
50, loss-free gains return 100, and gain-free losses return 0.

The morning public collector retains one content-addressed IHSG daily source
snapshot for both benchmark facts and local chart rendering. The dispatcher
uses only that frozen snapshot. This library adds no network requests or
independent provider cache. Source acquisition and rate-limit policy belong to
the explicit producer. Yahoo access is unofficial and can be rate-limited.

`yahoo_market_data.rotation.parse_caps` reads native exact-symbol quote responses
in batches of at most 100. It requires IDR equity identity and positive finite
`marketCap`; absent symbols or caps stay missing. Yahoo's `tradeable` field is
not IDX suspension evidence and is not used for eligibility. No cap is derived
from shares, prices or another provider.

`parse_rotation_history` requires all 18 explicit calendar sessions, ordinary
Close, native IDR equity identity and positive trading volume on every required
session. Null or zero volume, missing candles and malformed/unknown actions
reject the stock. This proves observed trading during the closing window, not
eligibility at a future opening. Native split ratios must agree with their
components. Ordinary Close is used as already split-adjusted, without applying
the split a second time; dividend amounts are retained as excluded additions.
Adjusted Close is never used. Caller-owned retained sources establish request,
retrieval, closing-session and cutoff provenance.

Run `python -m pytest -q lib-yahoo-market-data/tests` from the repository root.
