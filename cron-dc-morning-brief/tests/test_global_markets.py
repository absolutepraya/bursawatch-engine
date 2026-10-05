"""Synthetic Yahoo chart responses and reviewed exchange sessions, no network."""
from datetime import datetime
import pytest


def at(value): return datetime.fromisoformat(value)
def unix(value): return int(at(value).timestamp())


def schedule(zone, rows, through='2026-10-06'):
    return dict(verified=True, version='synthetic-sessions-1', digest='a'*64,
                verified_at='2026-10-01T00:00:00+00:00', timezone=zone,
                valid_from='2026-09-25', valid_through=through,
                sessions=[dict(start=s,end=e) for s,e in rows])


def chart(symbol, zone, dates, closes, *, price=999, quote_at='2026-10-05T07:30:00+07:00', currency='USD'):
    return {'chart':{'error':None,'result':[dict(meta=dict(symbol=symbol,exchangeTimezoneName=zone,currency=currency,
        dataGranularity='1d',regularMarketPrice=price,regularMarketTime=unix(quote_at),exchangeDataDelayedBy=15),
        timestamp=[unix(d) for d in dates],indicators={'quote':[{'close':closes}]})]}}


US_ROWS = [('2026-10-01T09:30:00-04:00','2026-10-01T16:00:00-04:00'),
           ('2026-10-02T09:30:00-04:00','2026-10-02T16:00:00-04:00'),
           ('2026-10-05T09:30:00-04:00','2026-10-05T16:00:00-04:00')]
ASIA_ROWS = [('2026-10-01T09:00:00+09:00','2026-10-01T15:30:00+09:00'),
             ('2026-10-02T09:00:00+09:00','2026-10-02T15:30:00+09:00'),
             ('2026-10-05T09:00:00+09:00','2026-10-05T15:30:00+09:00')]
FREEZE = at('2026-10-05T07:30:00+07:00')


def test_qqq_uses_completed_regular_close_not_afterhours_and_previous_denominator(core):
    module = core('global_markets')
    raw = chart('QQQ','America/New_York',[s for s,e in US_ROWS[:2]],[100,102],price=110,quote_at='2026-10-02T20:00:00-04:00')
    quote = module.parse_yahoo_chart('QQQ',raw,freeze_at=FREEZE,retrieved_at=FREEZE,sessions=schedule('America/New_York',US_ROWS))
    assert (quote['price'],quote['previous_close'],quote['change'],quote['percent'],quote['unit']) == (102,100,2,2,'USD')
    assert quote['price_at'] == '2026-10-02T20:00:00+00:00'
    assert quote['comparison'] == 'completed_regular_session' and quote['status'] == 'available'
    assert quote['delay_status'] == 'delayed' and quote['delay_minutes'] == 15


def test_open_asian_regular_snapshot_preserves_time_points_and_delay(core):
    module = core('global_markets')
    raw = chart('^KS11','Asia/Seoul',[s for s,e in ASIA_ROWS[:2]],[3000,3100],price=3131,quote_at='2026-10-05T09:15:00+09:00',currency='KRW')
    quote = module.parse_yahoo_chart('KOSPI',raw,freeze_at=FREEZE,retrieved_at=FREEZE,sessions=schedule('Asia/Seoul',ASIA_ROWS))
    assert (quote['price'],quote['previous_close'],quote['change'],quote['percent'],quote['unit']) == (3131,3100,31,1,'points')
    assert quote['comparison'] == 'open_regular_snapshot' and quote['status'] == 'available'
    assert quote['price_at'] == '2026-10-05T00:15:00+00:00'


@pytest.mark.parametrize('mutation,status', [('stale','stale'),('future','unavailable'),('no_time','unavailable'),('zero_close','unavailable'),('nan','unavailable'),('coverage','unavailable')])
def test_missing_stale_or_future_open_quote_is_not_fabricated_zero(core, mutation, status):
    module = core('global_markets')
    raw = chart('^N225','Asia/Tokyo',[s for s,e in ASIA_ROWS[:2]],[40000,41000],price=41410,quote_at='2026-10-05T09:20:00+09:00',currency='JPY')
    sessions = schedule('Asia/Tokyo',ASIA_ROWS)
    meta = raw['chart']['result'][0]['meta']
    if mutation == 'stale': meta['regularMarketTime'] = unix('2026-10-05T09:00:00+09:00')
    elif mutation == 'future': meta['regularMarketTime'] = unix('2026-10-05T09:31:00+09:00')
    elif mutation == 'no_time': del meta['regularMarketTime']
    elif mutation == 'zero_close': raw['chart']['result'][0]['indicators']['quote'][0]['close'][1] = 0
    elif mutation == 'nan': meta['regularMarketPrice'] = float('nan')
    elif mutation == 'coverage': sessions['valid_through'] = '2026-10-02'
    result = module.parse_yahoo_chart('Nikkei',raw,freeze_at=FREEZE,retrieved_at=FREEZE,sessions=sessions)
    assert result['status'] == status
    if status == 'unavailable': assert result['price'] is None and result['percent'] is None


def test_holiday_closed_asia_uses_reviewed_previous_session_not_weekdays(core):
    module = core('global_markets')
    raw = chart('^KS11','Asia/Seoul',[s for s,e in ASIA_ROWS[:2]],[3000,3000],price=3500,quote_at='2026-10-05T09:20:00+09:00',currency='KRW')
    result = module.parse_yahoo_chart('KOSPI',raw,freeze_at=FREEZE,retrieved_at=FREEZE,sessions=schedule('Asia/Seoul',ASIA_ROWS[:2]))
    assert result['comparison'] == 'completed_regular_session' and result['percent'] == 0
    row = module.format_global_rows([result],logos={'KOSPI':'<:kospi:123456789012345678>'})
    assert '⚪' in row and '+0.00' in row and 'closed' in row


def test_dst_qqq_close_timestamp_follows_verified_offset_and_gap_is_stale(core):
    module = core('global_markets')
    rows = [('2026-10-30T09:30:00-04:00','2026-10-30T16:00:00-04:00'),
            ('2026-11-02T09:30:00-05:00','2026-11-02T16:00:00-05:00')]
    sessions = schedule('America/New_York',rows,through='2026-11-04')
    freeze = at('2026-11-03T07:30:00+07:00')
    raw = chart('QQQ','America/New_York',[s for s,e in rows],[100,99],quote_at=rows[-1][1])
    result = module.parse_yahoo_chart('QQQ',raw,freeze_at=freeze,retrieved_at=freeze,sessions=sessions)
    assert result['price_at'] == '2026-11-02T21:00:00+00:00' and result['percent'] == -1
    raw['chart']['result'][0]['indicators']['quote'][0]['close'][-1] = None
    gap = module.parse_yahoo_chart('QQQ',raw,freeze_at=freeze,retrieved_at=freeze,sessions=sessions)
    assert gap['status'] == 'stale' and gap['reason'] == 'latest_completed_session_missing'


def test_rows_have_actual_icons_signed_units_and_real_linebreaks_without_invented_logos(core):
    module = core('global_markets')
    quotes = []
    for name,zone,symbol,currency in [('KOSPI','Asia/Seoul','^KS11','KRW'),('Nikkei','Asia/Tokyo','^N225','JPY')]:
        quotes.append(module.parse_yahoo_chart(name,chart(symbol,zone,[s for s,e in ASIA_ROWS[:2]],[100,100],price=101,quote_at='2026-10-05T09:20:00+09:00',currency=currency),freeze_at=FREEZE,retrieved_at=FREEZE,sessions=schedule(zone,ASIA_ROWS)))
    rendered = module.format_global_rows(quotes,logos={},markdown=True)
    assert '  \n' in rendered and '<:green:1531274822221434911>' in rendered
    assert ':kospi:' not in rendered and '+1.00 poin (+1.00%)' in rendered


def test_quote_cannot_claim_observation_after_retrieval_and_freeze_rejects_other_cutoff(core,tmp_path):
    from test_evidence import owner
    module=core('global_markets')
    quote=module.parse_yahoo_chart('KOSPI',chart('^KS11','Asia/Seoul',[s for s,e in ASIA_ROWS[:2]],[100,100],price=101,quote_at='2026-10-05T09:20:00+09:00',currency='KRW'),freeze_at=FREEZE,retrieved_at=at('2026-10-05T07:10:00+07:00'),sessions=schedule('Asia/Seoul',ASIA_ROWS))
    assert quote['status']=='unavailable'
    store,run,lease=owner(core,tmp_path)
    quote['cutoff']='2026-10-06T00:30:00+00:00'
    with pytest.raises(ValueError): module.freeze_globals(store,run.run_id,[quote],lease=lease,now=FREEZE)
