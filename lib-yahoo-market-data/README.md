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

`simple_moving_average(closes, period)` returns an aligned tuple with `None`
during warm-up. `wilder_rsi(closes, period=14)` seeds with the first period's
average gains/losses and uses Wilder smoothing thereafter. Flat windows return
50, loss-free gains return 100, and gain-free losses return 0.

The morning public collector retains one content-addressed IHSG daily source
snapshot for both benchmark facts and local chart rendering. The dispatcher
uses only that frozen snapshot. This library adds no network requests or
independent provider cache. Source acquisition and rate-limit policy belong to
the explicit producer. Yahoo access is unofficial and can be rate-limited.

Run `python -m pytest -q lib-yahoo-market-data/tests` from the repository root.
