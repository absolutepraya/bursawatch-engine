from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone, date
import json

import pytest

from morning_brief.public_sources import yahoo_sessions, ihsg_benchmark
from morning_brief.global_markets import parse_yahoo_chart
from morning_brief.economic_calendar import SnapshotCache, select_calendar_events
from test_runner import calendar


CUTOFF=datetime(2026,10,5,0,30,tzinfo=timezone.utc)
RETRIEVED=CUTOFF-timedelta(seconds=30)


def native(symbol='SPY', zone='America/New_York', granularity='60m'):
    # Explicit synthetic provider fixture; these dates never become live inputs.
    spans=[(datetime(2026,10,d,13,30,tzinfo=timezone.utc),datetime(2026,10,d,20,tzinfo=timezone.utc)) for d in (1,2)]
    rows=[dict(start=int(s.timestamp()),end=int(e.timestamp())) for s,e in spans]
    return {'chart':{'error':None,'result':[{'meta':dict(symbol=symbol,exchangeTimezoneName=zone,
        dataGranularity=granularity,currency='USD',tradingPeriods=[[row] for row in rows],
        currentTradingPeriod={'regular':rows[-1]}),
        'timestamp':[r['start'] for r in rows],
        'indicators':{'quote':[{'close':[100.,102.]}]}}]}}


def test_native_periods_cannot_guess_coverage_after_last_exchange_session():
    with pytest.raises(ValueError):
        yahoo_sessions('SPY',native(),retrieved_at=RETRIEVED,cutoff=CUTOFF)


def test_native_regular_periods_and_completed_us_closes_are_bound_to_source():
    # US local cutoff is still Friday; current regular metadata includes Friday.
    cutoff=datetime(2026,10,3,0,30,tzinfo=timezone.utc)
    schedule=native(); daily=native(granularity='1d')
    proof=yahoo_sessions('SPY',schedule,retrieved_at=cutoff-timedelta(seconds=10),cutoff=cutoff)
    daily['chart']['result'][0]['meta']['regularMarketPrice']=999.
    quote=parse_yahoo_chart('SPY',daily,freeze_at=cutoff,retrieved_at=cutoff,sessions=proof)
    assert quote['status']=='available' and quote['price']==102. and quote['previous_close']==100.
    assert proof['evidence_kind']=='native_regular_trading_periods'


@pytest.mark.parametrize('change',['missing_periods','wrong_symbol','wrong_zone','after_cutoff','overlap'])
def test_native_schedule_failure_never_supplies_weekday_or_hour_defaults(change):
    cutoff=datetime(2026,10,3,0,30,tzinfo=timezone.utc); observed=cutoff
    payload=native(); meta=payload['chart']['result'][0]['meta']
    if change=='missing_periods':del meta['tradingPeriods']
    if change=='wrong_symbol':meta['symbol']='QQQ'
    if change=='wrong_zone':meta['exchangeTimezoneName']='UTC'
    if change=='after_cutoff':observed+=timedelta(seconds=1)
    if change=='overlap':meta['tradingPeriods'][1][0]['start']=meta['tradingPeriods'][0][0]['start']+60
    with pytest.raises((ValueError,KeyError)):
        yahoo_sessions('SPY',payload,retrieved_at=observed,cutoff=cutoff)


def test_fx_rollover_comes_from_native_provider_windows():
    cutoff=datetime(2026,10,2,12,tzinfo=timezone.utc)
    payload=native('IDR=X','Europe/London');meta=payload['chart']['result'][0]['meta']
    rows=[dict(start=int((datetime(2026,10,d,tzinfo=timezone.utc)-timedelta(hours=1)).timestamp()),
               end=int(datetime(2026,10,d,22,59,tzinfo=timezone.utc).timestamp())) for d in (1,2)]
    meta.update(tradingPeriods=[[r] for r in rows],currentTradingPeriod={'regular':rows[-1]})
    proof=yahoo_sessions('USDIDR',payload,retrieved_at=cutoff,cutoff=cutoff)
    assert proof['market_type']=='fx' and proof['baseline_policy']=='provider_daily_close'
    assert proof['sessions'][0]['start'].endswith('23:00:00+00:00')


def test_ihsg_fact_requires_expected_official_completed_session():
    payload=native('^JKSE','Asia/Jakarta');meta=payload['chart']['result'][0]['meta']
    rows=[dict(start=int(datetime(2026,10,d,2,tzinfo=timezone.utc).timestamp()),
               end=int(datetime(2026,10,d,9,tzinfo=timezone.utc).timestamp())) for d in (1,2,5)]
    meta.update(tradingPeriods=[[r] for r in rows],currentTradingPeriod={'regular':rows[-1]})
    proof=yahoo_sessions('IHSG',payload,retrieved_at=RETRIEVED,cutoff=CUTOFF)
    daily=deepcopy(payload);daily['chart']['result'][0]['meta']['dataGranularity']='1d'
    daily['chart']['result'][0].update(timestamp=[r['start'] for r in rows],
        indicators={'quote':[{'close':[100.,102.,999.]}]})
    verified=replace(calendar(),sessions=tuple(s for s in calendar().sessions if s not in (date(2026,10,3),date(2026,10,4))))
    values=ihsg_benchmark(daily,proof,verified,publication_session=date(2026,10,5),
        retrieved_at=RETRIEVED,cutoff=CUTOFF)
    assert values['benchmark']['2026-10-02']==102. and '2026-10-05' not in values['benchmark']
    daily['chart']['result'][0]['indicators']['quote'][0]['close'][1]=None
    with pytest.raises(ValueError):
        ihsg_benchmark(daily,proof,verified,publication_session=date(2026,10,5),retrieved_at=RETRIEVED,cutoff=CUTOFF)


def bps_snapshot(tmp_path, events):
    body='0:{"a":"$@1"}\n1:'+json.dumps(events)+'\n'
    return SnapshotCache(tmp_path).put(authority='BPS',source_url='https://www.bps.go.id/id/arc',
        html=body,retrieved_at=RETRIEVED.isoformat(),verified_at=RETRIEVED.isoformat(),
        amendment='native-fixture-v1',verified=True,source_format='bps-native-flight-v1')


def test_actual_bps_schema_keeps_unknown_time_period_and_source_scoped_identity(tmp_path):
    events=[dict(id=str(i),title=title,type='brs',date='2026-11-02',status='Belum Rilis') for i,title in
        enumerate(['Perkembangan Indeks Harga Konsumen','Perkembangan Ekspor dan Impor','Pertumbuhan Ekonomi',
                   'Keadaan Ketenagakerjaan','Perkembangan Pariwisata'],1)]
    result=select_calendar_events([bps_snapshot(tmp_path,events)],freeze_at=CUTOFF)
    assert len(result['events'])==3 and result['unavailable']==[]
    assert all(e['time_wib'] is None and e['reference_period']=='periode belum diumumkan' for e in result['events'])
    assert all(e['release_id'] is None for e in result['events'])


def test_bps_publication_and_empty_or_changed_native_response_are_unavailable(tmp_path):
    for i,events in enumerate([[],[dict(id='1',type='publikasi',title='Produk Domestik Bruto',date='2026-10-16',status='Belum Rilis')]]):
        result=select_calendar_events([bps_snapshot(tmp_path/str(i),events)],freeze_at=CUTOFF)
        assert result['events']==[] and result['unavailable']
