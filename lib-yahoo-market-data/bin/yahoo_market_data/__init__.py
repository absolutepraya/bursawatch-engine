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



def parse_closes(payload, *, symbol, exchange_timezone, through, session_dates):
    """Ordinary daily closes with explicit null/missing anchors, for trackers."""
    if type(through) is not date:
        raise ValueError('explicit closing session required')
    allowed = frozenset(session_dates)
    if not 1 <= len(allowed) <= 2000 or any(type(day) is not date for day in allowed):
        raise ValueError('explicit bounded sessions required')
    try:
        chart = payload['chart']
        if chart['error'] is not None or len(chart['result']) != 1:
            raise ValueError('single native Yahoo result required')
        row = chart['result'][0]; meta = row['meta']
        if (meta['symbol'] != symbol or meta['exchangeTimezoneName'] != exchange_timezone
                or meta['dataGranularity'] != '1d'):
            raise ValueError('native daily close identity mismatch')
        stamps = row['timestamp']; quotes = row['indicators']['quote']
        if len(quotes) != 1 or not 1 <= len(stamps) <= 2000:
            raise ValueError('bounded daily closes required')
        closes = quotes[0]['close']
        if len(closes) != len(stamps):
            raise ValueError('matching daily close arrays required')
        zone = ZoneInfo(exchange_timezone); values = {}; previous = None; previous_day = None
        for stamp, close in zip(stamps, closes, strict=True):
            if type(stamp) is not int or previous is not None and stamp <= previous:
                raise ValueError('ordered native close timestamps required')
            previous = stamp
            day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date()
            if previous_day is not None and day <= previous_day:
                raise ValueError('unique native daily sessions required')
            previous_day = day
            if day > through or day not in allowed:
                continue
            values[day.isoformat()] = (float(close) if type(close) in (int,float)
                and math.isfinite(close) and close > 0 else None)
        return values
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError('invalid native close response') from error

def close_performance(closes, *, sessions, through):
    """Pure 1/5/22/66-session changes, preserving explicit missing anchors."""
    sessions = tuple(sessions)
    if type(through) is not date or any(type(day) is not date for day in sessions):
        raise ValueError('explicit dates required')
    days = tuple(day for day in sessions if day <= through)
    if (not days or days[-1] != through
            or len(days) > 2000 or any(type(day) is not date for day in days)
            or days != tuple(sorted(set(days)))):
        raise ValueError('ordered explicit closing sessions required')
    def value(day):
        raw = closes.get(day.isoformat())
        return float(raw) if type(raw) in (int, float) and math.isfinite(raw) and raw > 0 else None
    latest = value(through)
    result = dict(latest_price=latest, session=through.isoformat(), basis='ordinary-close',
                  horizon_policy='1-5-22-66-verified-sessions')
    for name, offset in (('one_day', 1), ('one_week', 5), ('one_month', 22), ('three_month', 66)):
        baseline = value(days[-offset-1]) if len(days) > offset else None
        change = latest-baseline if latest is not None and baseline is not None else None
        result[name+'_change'] = change
        result[name+'_percent'] = 100*change/baseline if change is not None else None
    return result
