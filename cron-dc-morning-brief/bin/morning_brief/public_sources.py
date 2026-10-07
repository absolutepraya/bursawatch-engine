"""Validate native public-source records before they enter live manifests.

No IO and no guessed exchange hours, holidays, FX rollovers or release times.
Quote and schedule responses are separate, cutoff-visible retained artifacts.
"""
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from .calendar import aware
from .global_markets import WATCHLIST, _sessions, _number
from .store import digest, stamp


def yahoo_result(payload, *, symbol, granularity):
    results = payload['chart']['result']
    if payload['chart']['error'] is not None or len(results) != 1:
        raise ValueError('single successful native Yahoo result required')
    result = results[0]
    native_intervals={'60m','1h'} if granularity=='60m' else {granularity}
    if result['meta']['symbol'] != symbol or result['meta']['dataGranularity'] not in native_intervals:
        raise ValueError('native Yahoo identity mismatch')
    return result


def yahoo_sessions(name, payload, *, retrieved_at, cutoff):
    """Use Yahoo's explicit regular periods, including its FX day boundaries.

    Intraday chart responses expose historical tradingPeriods; daily responses
    do not. Only native regular periods and currentTradingPeriod.regular enter
    coverage. Pre/post hours and daily bar timestamp guesses never enter it.
    """
    if name not in WATCHLIST and name != 'IHSG':
        raise ValueError('unsupported instrument')
    symbol, expected_zone, _ = WATCHLIST.get(name, ('^JKSE', 'Asia/Jakarta', 'points'))
    retrieved_at, cutoff = aware(retrieved_at), aware(cutoff)
    if retrieved_at > cutoff:
        raise ValueError('schedule observed after cutoff')
    result = yahoo_result(payload, symbol=symbol, granularity='60m')
    meta = result['meta']; zone = meta['exchangeTimezoneName']
    if expected_zone is not None and zone != expected_zone:
        raise ValueError('native Yahoo exchange timezone mismatch')
    periods = meta['tradingPeriods']
    if type(periods) is not list or not 1 <= len(periods) <= 1000:
        raise ValueError('bounded native regular periods required')
    native = []
    for day in periods:
        if type(day) is not list or len(day) != 1:
            raise ValueError('unrecognized native regular period structure')
        native.append(day[0])
    native.append(meta['currentTradingPeriod']['regular'])
    intervals = set()
    for row in native:
        if any(type(row[k]) is not int for k in ('start', 'end')):
            raise ValueError('native regular period timestamps required')
        start = datetime.fromtimestamp(row['start'], timezone.utc)
        end = datetime.fromtimestamp(row['end'], timezone.utc)
        if not timedelta(0) < end-start <= timedelta(days=1):
            raise ValueError('invalid native regular duration')
        intervals.add((start, end))
    intervals = sorted(intervals)
    dates = [start.astimezone(ZoneInfo(zone)).date() for start, _ in intervals]
    proof = dict(verified=True, timezone=zone, version='yahoo-native-periods-v1:'+digest(payload),
        digest=digest(payload), verified_at=stamp(retrieved_at),
        valid_from=min(dates).isoformat(), valid_through=max(dates).isoformat(),
        sessions=[{'start': stamp(start), 'end': stamp(end)} for start, end in intervals],
        evidence_kind='native_regular_trading_periods', symbol=symbol)
    if name == 'USDIDR':
        proof.update(market_type='fx', baseline_policy='provider_daily_close')
    # IHSG is a previous-session fact. Its expected date is independently checked
    # against the official calendar below; no upcoming IDX hours are inferred.
    _sessions(proof, cutoff, zone, fx=name == 'USDIDR',coverage_day=dates[-1] if name=='IHSG' else None)
    return proof


def ihsg_benchmark(payload, sessions, calendar, *, publication_session, retrieved_at, cutoff):
    """Independently verify the latest IDX close for facts, not rotation prices.

    The official IDX calendar supplies the expected previous session. Native
    quote identity and regular-period metadata must match it and a completed
    daily bar. Missing expected bars cannot silently select an older close.
    """
    cutoff, retrieved_at = aware(cutoff), aware(retrieved_at)
    if retrieved_at > cutoff or not calendar.is_session(publication_session):
        raise ValueError('cutoff-visible publication session required')
    previous = calendar.last_sessions(publication_session, 2)[0]
    result = yahoo_result(payload, symbol='^JKSE', granularity='1d')
    if result['meta']['exchangeTimezoneName'] != 'Asia/Jakarta':
        raise ValueError('IHSG exchange timezone mismatch')
    intervals = _sessions(sessions, cutoff, 'Asia/Jakarta',coverage_day=previous)
    values, timestamps = result['indicators']['quote'][0]['close'], result['timestamp']
    if len(values) != len(timestamps) or not 1 <= len(values) <= 1000:
        raise ValueError('bounded matching IHSG bars required')
    benchmark = {}
    for raw, close in zip(timestamps, values, strict=True):
        if type(raw) is not int:
            raise ValueError('native IHSG bar timestamp required')
        bar = datetime.fromtimestamp(raw, timezone.utc)
        matches = [(start, end) for start, end in intervals if start <= bar < end and end <= retrieved_at]
        if not matches or close is None:
            continue
        if len(matches) != 1:
            raise ValueError('ambiguous native IHSG session')
        session = matches[0][0].astimezone(ZoneInfo('Asia/Jakarta')).date()
        if session > previous or not calendar.is_session(session):
            continue
        if session.isoformat() in benchmark:
            raise ValueError('duplicate native IHSG session bar')
        benchmark[session.isoformat()] = _number(close)
    if previous.isoformat() not in benchmark:
        raise ValueError('latest verified IDX close unavailable')
    proof = dict(kind='caller_attestation', verified=True, content_sha256=digest(benchmark),
        available_at=stamp(max(retrieved_at, datetime.fromisoformat(sessions['verified_at']))),
        source_url='https://finance.yahoo.com/quote/%5EJKSE/',
        evidence_ref='native-yahoo:'+digest(payload)+':'+sessions['digest'],
        version='yahoo-ihsg-close-v1:'+digest(payload))
    numerical = {'benchmark': benchmark, 'benchmark_attestation': proof}
    # The same retained daily source supplies the tracker. No independent quote
    # fetch, adjusted-close substitution or sliding across a missing baseline.
    try:
        from yahoo_market_data import parse_closes, close_performance
        closes = parse_closes(payload, symbol='^JKSE', exchange_timezone='Asia/Jakarta',
                              through=previous, session_dates=calendar.sessions)
        tracker = close_performance(closes,
                                    sessions=calendar.sessions, through=previous)
        if tracker['latest_price'] != benchmark[previous.isoformat()]:
            raise ValueError('tracker and verified close differ')
        numerical['ihsg_tracker'] = tracker
        numerical['ihsg_tracker_attestation'] = {**proof, 'content_sha256':digest(tracker)}
    except (ValueError, KeyError, TypeError):
        pass
    return numerical
