"""Pure reusable Yahoo daily OHLC validation and technical indicators."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import math
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DailyBar:
    session: date
    open: float
    high: float
    low: float
    close: float


def _price(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('finite positive ordinary price required')
    return float(value)


def parse_daily(payload, *, symbol, exchange_timezone, through, session_dates=None):
    """Validate native ordinary OHLC, excluding unfinished/later session dates."""
    if type(through) is not date:
        raise ValueError('explicit final session required')
    allowed = None
    if session_dates is not None:
        allowed = frozenset(session_dates)
        if not 1 <= len(allowed) <= 2000 or any(type(day) is not date for day in allowed):
            raise ValueError('bounded explicit session dates required')
    try:
        chart = payload['chart']
        if chart['error'] is not None or len(chart['result']) != 1:
            raise ValueError('single successful Yahoo result required')
        row = chart['result'][0]
        meta = row['meta']
        if (meta['symbol'] != symbol or meta['exchangeTimezoneName'] != exchange_timezone
                or meta['dataGranularity'] != '1d'):
            raise ValueError('Yahoo daily identity mismatch')
        timestamps = row['timestamp']
        quotes = row['indicators']['quote']
        if len(quotes) != 1 or not 1 <= len(timestamps) <= 2000:
            raise ValueError('bounded matching daily OHLC required')
        quote = quotes[0]
        fields = [quote[key] for key in ('open', 'high', 'low', 'close')]
        if any(len(values) != len(timestamps) for values in fields):
            raise ValueError('daily OHLC lengths differ')
        zone = ZoneInfo(exchange_timezone)
        bars = []; previous_stamp = None; previous_date = None
        for stamp, values in zip(timestamps, zip(*fields), strict=True):
            if type(stamp) is not int or (previous_stamp is not None and stamp <= previous_stamp):
                raise ValueError('daily timestamps must be strictly ordered')
            previous_stamp = stamp
            session = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date()
            if previous_date is not None and session <= previous_date:
                raise ValueError('duplicate daily session')
            previous_date = session
            if session > through or allowed is not None and session not in allowed:
                continue
            opening, high, low, close = map(_price, values)
            if not low <= min(opening, close) <= max(opening, close) <= high:
                raise ValueError('invalid daily OHLC bounds')
            bars.append(DailyBar(session, opening, high, low, close))
        if not bars:
            raise ValueError('daily OHLC unavailable')
        return tuple(bars)
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError('malformed native daily OHLC') from error


def _inputs(closes, period):
    if type(period) is not int or period <= 0:
        raise ValueError('positive indicator period required')
    return tuple(_price(value) for value in closes)


def simple_moving_average(closes, period):
    closes = _inputs(closes, period)
    return tuple(None if index + 1 < period else
                 math.fsum(closes[index + 1 - period:index + 1]) / period
                 for index in range(len(closes)))


def wilder_rsi(closes, period=14):
    closes = _inputs(closes, period)
    result = [None] * len(closes)
    if len(closes) <= period:
        return tuple(result)
    changes = tuple(right - left for left, right in zip(closes, closes[1:]))
    gains = math.fsum(max(change, 0) for change in changes[:period]) / period
    losses = math.fsum(max(-change, 0) for change in changes[:period]) / period
    for index in range(period, len(closes)):
        if index > period:
            change = changes[index - 1]
            gains = (gains * (period - 1) + max(change, 0)) / period
            losses = (losses * (period - 1) + max(-change, 0)) / period
        result[index] = 50.0 if gains == losses == 0 else 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    return tuple(result)
