"""Bounded Yahoo chart parsing with explicit regular exchange session evidence.

No network transport or weekday/holiday inference. Yahoo access and display
permissions remain a separately verified rollout input.
"""
from datetime import datetime, timezone, timedelta, date
import math
import re
from zoneinfo import ZoneInfo
from .calendar import aware
from .store import digest, stamp

WATCHLIST = {'KOSPI': ('^KS11','Asia/Seoul','points'),
             'Nikkei': ('^N225','Asia/Tokyo','points'),
             'QQQ': ('QQQ','America/New_York','USD')}
GREEN = '<:green:1531274822221434911>'
RED = '<:red:1531274756853202974>'


def _instant(value):
    return aware(datetime.fromisoformat(value.replace('Z','+00:00')))


def _number(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
        raise ValueError('positive finite quote required')
    return float(value)


def _sessions(snapshot, cutoff, zone):
    if (snapshot.get('verified') is not True or snapshot['timezone'] != zone
            or not snapshot['version'] or re.fullmatch('[0-9a-f]{64}',snapshot['digest']) is None
            or _instant(snapshot['verified_at']) > cutoff
            or not date.fromisoformat(snapshot['valid_from']) <= cutoff.astimezone(ZoneInfo(zone)).date() <= date.fromisoformat(snapshot['valid_through'])):
        raise ValueError('verified covering exchange sessions required')
    rows = [(_instant(row['start']),_instant(row['end'])) for row in snapshot['sessions']]
    if len(rows) < 2 or rows != sorted(set(rows)) or any(s >= e for s,e in rows):
        raise ValueError('ordered regular exchange sessions required')
    for index,(start,end) in enumerate(rows):
        if (start.astimezone(ZoneInfo(zone)).date() != end.astimezone(ZoneInfo(zone)).date()
                or not date.fromisoformat(snapshot['valid_from']) <= start.astimezone(ZoneInfo(zone)).date() <= date.fromisoformat(snapshot['valid_through'])
                or (index and rows[index-1][1] >= start)):
            raise ValueError('invalid regular session intervals')
    return rows


def parse_yahoo_chart(name: str, payload: dict, *, freeze_at: datetime, retrieved_at: datetime,
                      sessions: dict) -> dict:
    """Read daily Yahoo chart bars, plus timestamped regular meta for open Asia.

    Daily bar timestamps identify the session; a completed price is explicitly
    stamped at that verified session's end, never presented as a live quote.
    The caller supplies reviewed exchange coverage including holidays and DST.
    """
    if name not in WATCHLIST:
        raise ValueError('market is outside the three-row watchlist')
    symbol,zone,unit = WATCHLIST[name]
    cutoff, retrieved = aware(freeze_at), aware(retrieved_at)
    base = dict(name=name,symbol=symbol,timezone=zone,unit=unit,status='unavailable',reason=None,
                price=None,previous_close=None,change=None,percent=None,price_at=None,previous_close_at=None,
                bar_at=None,comparison=None,market_status=None,delay_minutes=None,delay_status='unknown',
                cutoff=stamp(cutoff),retrieved_at=stamp(retrieved),source_url='https://finance.yahoo.com/quote/'+symbol+'/',
                source_digest=None,session_version=sessions.get('version'),session_digest=sessions.get('digest'))
    try:
        base['source_digest'] = digest(payload)
        if retrieved > cutoff:
            raise ValueError('snapshot_retrieved_after_cutoff')
        intervals = _sessions(sessions,cutoff,zone)
        results = payload['chart']['result']
        if payload['chart']['error'] is not None or len(results) != 1:
            raise ValueError('chart_unavailable')
        result = results[0]
        meta = result['meta']
        if meta['symbol'] != symbol or meta['exchangeTimezoneName'] != zone or meta['dataGranularity'] != '1d':
            raise ValueError('chart_provenance_mismatch')
        if unit == 'USD' and meta['currency'] != 'USD':
            raise ValueError('quote_currency_mismatch')
        delay = meta.get('exchangeDataDelayedBy')
        if delay is not None:
            if type(delay) not in (int,float) or not math.isfinite(delay) or not 0 <= delay <= 1440:
                raise ValueError('invalid_quote_delay')
            base.update(delay_minutes=delay,delay_status='delayed' if delay else 'live')
        stamps = result['timestamp']
        closes = result['indicators']['quote'][0]['close']
        if len(stamps) != len(closes) or len(stamps) > 1000:
            raise ValueError('chart_bar_bounds')
        bars = {}
        for value,close in zip(stamps,closes,strict=True):
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError('invalid_bar_timestamp')
            timestamp = datetime.fromtimestamp(value,timezone.utc)
            matches = [i for i,(start,end) in enumerate(intervals) if start <= timestamp < end]
            if len(matches) == 1:
                index = matches[0]
                if index in bars:
                    raise ValueError('duplicate_session_bars')
                bars[index] = (timestamp, close)
        complete = [i for i,(_,end) in enumerate(intervals) if end <= cutoff]
        opened = [i for i,(start,end) in enumerate(intervals) if start <= cutoff < end]
        use_open = name != 'QQQ' and bool(opened)
        if use_open:
            index = opened[-1]
            raw_time = meta['regularMarketTime']
            if type(raw_time) not in (int,float) or not math.isfinite(raw_time):
                raise ValueError('invalid_regular_timestamp')
            price_at = datetime.fromtimestamp(raw_time,timezone.utc)
            if not intervals[index][0] <= price_at <= cutoff:
                raise ValueError('regular_timestamp_outside_cutoff_session')
            price = _number(meta['regularMarketPrice'])
            comparison, market_status = 'open_regular_snapshot', 'open'
            base['status'] = 'stale' if cutoff-price_at > timedelta(minutes=(delay or 0)+5) else 'available'
            if base['status'] == 'stale': base['reason'] = 'regular_snapshot_stale'
            bar_at = None
        else:
            if not complete:
                raise ValueError('completed_regular_session_unavailable')
            index = complete[-1]
            if index not in bars or bars[index][1] is None:
                base.update(status='stale',reason='latest_completed_session_missing')
                return base
            bar_at, raw = bars[index]
            price, price_at = _number(raw), intervals[index][1]
            comparison, market_status = 'completed_regular_session', 'closed' if not opened else 'open'
            base['status'] = 'available'
        if price_at > retrieved:
            raise ValueError('quote_observed_after_retrieval')
        if index == 0 or index-1 not in bars:
            raise ValueError('prior_regular_close_unavailable')
        previous = _number(bars[index-1][1])
        change = price-previous
        base.update(price=price,previous_close=previous,change=change,percent=100*change/previous,
                    price_at=stamp(price_at),previous_close_at=stamp(intervals[index-1][1]),
                    bar_at=stamp(bar_at) if bar_at else None,comparison=comparison,market_status=market_status)
    except (ValueError,TypeError,KeyError,IndexError,OverflowError):
        base.update(status='unavailable',reason='regular_session_provenance_unavailable',price=None,
                    previous_close=None,change=None,percent=None,price_at=None,previous_close_at=None)
    return base


def format_global_rows(quotes: list[dict], *, logos: dict[str,str], markdown=False) -> str:
    """Supplied real logo IDs only; existing status IDs and Unicode exact-flat."""
    if len(quotes) > 3 or len({q['name'] for q in quotes}) != len(quotes):
        raise ValueError('at most three distinct global rows')
    rows = []
    for quote in quotes:
        name = quote['name']
        if name not in WATCHLIST: raise ValueError('unknown market')
        logo = logos.get(name,'')
        if logo and re.fullmatch(r'<:[A-Za-z0-9_]+:[0-9]{15,22}>',logo) is None:
            raise ValueError('actual custom-logo markup required')
        prefix = (logo+' ') if logo else ''
        if quote['status'] != 'available':
            rows.append(prefix+name+': '+('data kedaluwarsa' if quote['status']=='stale' else 'data belum tersedia'))
            continue
        change, percent = quote['change'],quote['percent']
        marker = GREEN if change > 0 else RED if change < 0 else '⚪'
        unit = 'USD' if quote['unit']=='USD' else 'poin'
        local = _instant(quote['price_at']).astimezone(ZoneInfo('Asia/Jakarta'))
        delay = f"delayed {quote['delay_minutes']:g}m" if quote['delay_status']=='delayed' else quote['delay_status']
        rows.append(f"{prefix}{name}: {change:+.2f} {unit} ({percent:+.2f}%) {marker} · {local:%d/%m %H:%M} WIB · {quote['market_status']} · {delay}")
    return ('  \n' if markdown else '\n').join(rows)


def freeze_globals(store,run_id,quotes: list[dict],*,lease,now):
    if len(quotes)>3 or len({q['name'] for q in quotes}) != len(quotes):
        raise ValueError('at most three distinct global rows')
    run = store.get_run(run_id)
    if any(q['name'] not in WATCHLIST or q['cutoff'] != run.freeze_at for q in quotes):
        raise ValueError('quote watchlist/cutoff does not match run')
    return store.freeze(run_id,'globals',{'quotes':quotes,'cutoff':run.freeze_at},lease=lease,now=now)
