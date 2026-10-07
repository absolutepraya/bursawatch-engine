"""Native ordinary-close, action and cap parsing, without provider IO."""
from datetime import datetime, timezone
import math
import re
from zoneinfo import ZoneInfo

from . import parse_daily


def _positive(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('finite positive market value required')
    return float(value)


def parse_caps(payload, *, symbols):
    """Keep missing caps missing; do not use tradeable as IDX eligibility."""
    wanted = set(symbols)
    if not wanted or len(wanted)!=len(symbols) or len(wanted) > 100 or any(not re.fullmatch(r'[A-Z]{4}\.JK', s) for s in wanted):
        raise ValueError('bounded exact IDX cap symbols required')
    try:
        response = payload['quoteResponse']
        if response['error'] is not None or len(response['result']) > len(wanted):
            raise ValueError('successful exact Yahoo quotes required')
        caps = {}; seen = set()
        for row in response['result']:
            symbol = row['symbol']
            if symbol not in wanted or symbol in seen:
                raise ValueError('unexpected or duplicate cap quote')
            seen.add(symbol)
            if (row.get('currency') != 'IDR' or row.get('quoteType') != 'EQUITY'
                    or row.get('exchangeTimezoneName') != 'Asia/Jakarta'):
                continue
            try:
                caps[symbol.removesuffix('.JK')] = _positive(row['marketCap'])
            except (KeyError, ValueError):
                continue
        return caps
    except (KeyError, TypeError) as error:
        raise ValueError('malformed native cap quotes') from error


def parse_rotation_history(payload, *, symbol, sessions):
    """Use split-adjusted ordinary Close; exclude dividend additions.

    Every required session must show actual positive trading volume. This is
    evidence of trading during the closing window, not a claim about future
    suspensions or Yahoo's account-specific tradeable flag.
    """
    if not re.fullmatch(r'[A-Z]{4}\.JK', symbol) or len(sessions) != 18 or tuple(sorted(set(sessions))) != tuple(sessions):
        raise ValueError('exact symbol and eighteen aligned sessions required')
    bars = parse_daily(payload, symbol=symbol, exchange_timezone='Asia/Jakarta',
                       through=sessions[-1], session_dates=set(sessions))
    if tuple(bar.session for bar in bars) != tuple(sessions):
        raise ValueError('incomplete rotation closing window')
    try:
        row = payload['chart']['result'][0]
        if row['meta'].get('currency') != 'IDR' or row['meta'].get('instrumentType') != 'EQUITY':
            raise ValueError('native IDX equity required')
        volumes = row['indicators']['quote'][0]['volume']
        if len(volumes) != len(row['timestamp']):
            raise ValueError('native volume lengths differ')
        zone = ZoneInfo('Asia/Jakarta'); observed = {}
        for stamp, volume in zip(row['timestamp'], volumes, strict=True):
            day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date()
            if day in sessions:
                observed[day] = _positive(volume)
        if set(observed) != set(sessions):
            raise ValueError('observed trading evidence unavailable')
        events = row.get('events', {})
        if not isinstance(events, dict) or set(events) - {'splits', 'dividends'}:
            raise ValueError('unresolved native corporate action')
        actions = []
        for kind, records in events.items():
            if not isinstance(records, dict) or len(records) > 1000:
                raise ValueError('bounded native action map required')
            for identity, event in records.items():
                stamp = event['date']
                if type(stamp) is not int or identity != str(stamp):
                    raise ValueError('native action identity mismatch')
                day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date()
                if kind == 'splits':
                    numerator, denominator = _positive(event['numerator']), _positive(event['denominator'])
                    if event['splitRatio'] != f'{numerator:g}:{denominator:g}':
                        raise ValueError('inconsistent native split ratio')
                    treatment, ratio = 'already_adjusted', _positive(numerator / denominator)
                else:
                    _positive(event['amount'])
                    treatment, ratio = 'exclude_dividend', None
                if sessions[0] <= day <= sessions[-1]:
                    if day not in sessions:
                        raise ValueError('action outside verified trading sessions')
                    actions.append(dict(identity=f'yahoo:{symbol}:{kind}:{identity}',
                                        treatment=treatment, ratio=ratio,
                                        effective_session=day.isoformat()))
        return dict(closes={bar.session.isoformat(): bar.close for bar in bars},
                    basis='split_adjusted', trading_eligible=True,
                    eligibility_method='positive-native-volume-every-required-closing-session',
                    actions=sorted(actions, key=lambda a: a['identity']))
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError('malformed native rotation evidence') from error
