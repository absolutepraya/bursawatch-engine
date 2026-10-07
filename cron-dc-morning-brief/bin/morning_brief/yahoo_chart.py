"""Cutoff-bound IHSG chart preparation from the shared retained Yahoo snapshot."""
from calendar import monthrange
from datetime import date, datetime
from urllib.parse import urlsplit, unquote

from yahoo_market_data import parse_daily, simple_moving_average, wilder_rsi
from .calendar import aware
from .public_sources import ihsg_benchmark
from .store import digest

PROFILE = 'ihsg-yahoo-candles-sma-rsi-v1'
MA_PERIODS = (10, 20, 50, 100)


def prepare_chart(context, calendar, *, publication_session, cutoff):
    """No fetch or inferred sessions; missing candles or warm-up fail closed."""
    try:
        cutoff = aware(cutoff)
        if (context['provider'] != 'yahoo' or context['profile_revision'] != PROFILE
                or aware(datetime.fromisoformat(context['cutoff'])) != cutoff):
            raise ValueError('unsupported frozen Yahoo chart profile')
        daily = context['daily']; payload = daily['payload']
        observed = aware(datetime.fromisoformat(daily['retrieved_at']))
        url = urlsplit(daily['source_url'])
        source_hash = daily['source_sha256']
        if (daily['payload_sha256'] != digest(payload) or observed > cutoff
                or type(source_hash) is not str or len(source_hash) != 64
                or any(char not in '0123456789abcdef' for char in source_hash)
                or url.scheme != 'https' or url.hostname not in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com')
                or unquote(url.path) != '/v8/finance/chart/^JKSE'):
            raise ValueError('cutoff-visible bound Yahoo history required')
        # Native regular periods establish completion of the expected latest
        # close; official calendar sessions establish the historical alignment.
        ihsg_benchmark(payload, context['sessions'], calendar,
            publication_session=publication_session, retrieved_at=observed, cutoff=cutoff)
        previous = calendar.last_sessions(publication_session, 2)[0]
        bars = parse_daily(payload, symbol='^JKSE', exchange_timezone='Asia/Jakarta', through=previous,
                           session_dates=calendar.sessions)
        month_index = previous.year * 12 + previous.month - 1 - 3
        year, month = divmod(month_index, 12); month += 1
        start = date(year, month, min(previous.day, monthrange(year, month)[1]))
        if start < calendar.valid_from:
            raise ValueError('chart window outside verified calendar')
        visible = tuple(day for day in calendar.sessions if start <= day <= previous)
        if not visible or visible[-1] != previous:
            raise ValueError('verified chart window unavailable')
        prior = tuple(day for day in calendar.sessions if day < visible[0])
        if len(prior) < 99:
            raise ValueError('verified MA100 warm-up unavailable')
        required = prior[-99:] + visible
        by_session = {bar.session: bar for bar in bars}
        if any(day not in by_session for day in required):
            raise ValueError('missing chart or indicator warm-up candle')
        # Use all contiguous verified history available for a stable RSI seed.
        earlier = tuple(day for day in prior if day >= bars[0].session)
        history = earlier + visible
        if any(day not in by_session for day in history):
            raise ValueError('gap in retained indicator history')
        aligned = tuple(by_session[day] for day in history)
        closes = tuple(bar.close for bar in aligned)
        offset = len(earlier)
        averages = {str(period): simple_moving_average(closes, period)[offset:] for period in MA_PERIODS}
        rsi = wilder_rsi(closes, 14)[offset:]
        if any(value is None for values in (*averages.values(), rsi) for value in values):
            raise ValueError('incomplete visible indicators')
        provenance = dict(profile_revision=PROFILE, symbol='^JKSE', interval='1d',
            cutoff=cutoff.isoformat(), last_bar_date=previous.isoformat(), source_url=daily['source_url'],
            retrieved_at=daily['retrieved_at'], payload_sha256=daily['payload_sha256'],
            source_sha256=daily['source_sha256'], calendar_version=calendar.version,
            calendar_digest=calendar.import_digest, sessions_digest=digest(context['sessions']),
            history_sessions=[day.isoformat() for day in history],
            visible_start=start.isoformat(), ma_type='SMA', rsi_period=14, rsi_method='Wilder')
        return dict(bars=aligned[offset:], averages=averages, rsi=rsi, provenance=provenance)
    except (KeyError, TypeError, IndexError) as error:
        raise ValueError('invalid retained Yahoo chart context') from error
