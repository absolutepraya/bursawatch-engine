"""Strictly guarded fill for a null close on the latest completed session.

Yahoo's daily series can return ``close = null`` for the most recent completed
session, while the same response (or its hourly series) still carries a
consistent close. This module fills only that single bar, only from evidence
that agrees with the bar itself, and reports exactly how. Anything that does not
agree leaves the gap in place. Pure functions, no IO, inputs are never mutated.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _at(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return datetime.fromtimestamp(value, timezone.utc)


def _same(a, b):
    return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def _row(payload):
    try:
        row = payload['chart']['result'][0]
        quote = row['indicators']['quote'][0]
        stamps = row['timestamp']
        if len(quote['close']) != len(stamps):
            return None
        return row, quote, stamps
    except (KeyError, IndexError, TypeError):
        return None


def _meta_close(meta, quote, index, start, end, grace):
    price, moment = _number(meta.get('regularMarketPrice')), _at(meta.get('regularMarketTime'))
    if price is None or moment is None or not end - grace <= moment <= end + grace:
        return None
    high, low = _number(quote.get('high', [None] * (index + 1))[index]), _number(quote.get('low', [None] * (index + 1))[index])
    if high is None or low is None or not low <= price <= high:
        return None
    if not _same(high, _number(meta.get('regularMarketDayHigh'))) or not _same(low, _number(meta.get('regularMarketDayLow'))):
        return None
    bar_volume, day_volume = quote.get('volume', [None] * (index + 1))[index], meta.get('regularMarketVolume')
    if bar_volume is not None and day_volume is not None and bar_volume != day_volume:
        return None
    return price


def _intraday_close(intraday, symbol, meta, start, end, grace, tail, bar):
    try:
        series = intraday['chart']['result'][0]
        if series['meta']['symbol'] != symbol:
            return None
        stamps, closes = series['timestamp'], series['indicators']['quote'][0]['close']
        if len(stamps) != len(closes):
            return None
    except (KeyError, IndexError, TypeError):
        return None
    inside = [(moment, close) for stamp, close in zip(stamps, closes)
              if (moment := _at(stamp)) is not None and start <= moment < end]
    if not inside:
        return None
    moment, close = max(inside, key=lambda item: item[0])
    value = _number(close)
    if value is None or moment < end - tail:
        return None
    high, low = bar
    if (high is not None and value > high * (1 + 1e-6)) or (low is not None and value < low * (1 - 1e-6)):
        return None
    # The hourly series can stop before a closing auction, so it is never trusted alone: the
    # closing-window market price must confirm it. A live next-session price cannot.
    price, quoted = _number(meta.get('regularMarketPrice')), _at(meta.get('regularMarketTime'))
    if price is None or quoted is None or not end - grace <= quoted <= end + grace:
        return None
    if not math.isclose(price, value, rel_tol=1e-4, abs_tol=0.01):
        return None
    return value, moment


def _previous_close(previous, symbol, end):
    """``chartPreviousClose`` of a one-day chart request made after the session ended."""
    try:
        series = previous['chart']['result'][0]
        stamps = series['timestamp']
        if series['meta']['symbol'] != symbol or not stamps:
            return None
        # Every bar must belong to a later session, so the response's prior close is this session's.
        if any((moment := _at(stamp)) is None or moment < end for stamp in stamps):
            return None
        return _number(series['meta'].get('chartPreviousClose'))
    except (KeyError, IndexError, TypeError):
        return None


def fill_latest_close(payload, *, session_start, session_end, intraday=None, previous_close=None,
                      closing_grace=timedelta(minutes=30), intraday_tail=timedelta(minutes=70)):
    """Return ``(payload, repair)`` for the one bar inside ``[session_start, session_end)``.

    Evidence, in order: the response's own closing-window market price when it agrees with
    the bar; the hourly series when that same market price confirms it; the prior close of a
    later one-day chart request. ``repair`` is ``None`` when nothing was changed. Otherwise the returned payload
    is a copy whose single null close is filled and ``repair`` names the method,
    value and session window so callers can retain the provenance.
    """
    parsed = _row(payload)
    if parsed is None:
        return payload, None
    row, quote, stamps = parsed
    start, end = session_start.astimezone(timezone.utc), session_end.astimezone(timezone.utc)
    inside = [i for i, stamp in enumerate(stamps) if (moment := _at(stamp)) is not None and start <= moment < end]
    if len(inside) != 1 or quote['close'][inside[0]] is not None:
        return payload, None
    index = inside[0]
    meta = row.get('meta', {})
    method = None
    value = _meta_close(meta, quote, index, start, end, closing_grace)
    if value is not None:
        method = 'meta_regular_market_price'
    elif intraday is not None:
        bar = (_number(quote.get('high', [None] * (index + 1))[index]), _number(quote.get('low', [None] * (index + 1))[index]))
        found = _intraday_close(intraday, meta.get('symbol'), meta, start, end, closing_grace, intraday_tail, bar)
        if found is not None:
            value, moment = found
            method = 'last_intraday_bar_close'
    if method is None and previous_close is not None:
        value = _previous_close(previous_close, meta.get('symbol'), end)
        if value is not None:
            method = 'chart_previous_close'
    if method is None:
        return payload, None
    repaired = deepcopy(payload)
    repaired['chart']['result'][0]['indicators']['quote'][0]['close'][index] = value
    return repaired, dict(method=method, value=value, session_start=session_start.isoformat(), session_end=session_end.isoformat())
