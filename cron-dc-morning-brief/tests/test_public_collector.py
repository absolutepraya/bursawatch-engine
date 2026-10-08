from datetime import datetime, timedelta, timezone
from pathlib import Path

from morning_brief.public_collector import collect_public
from morning_brief.host import load_inputs
from test_host import setup_host, snapshot, FREEZE
from test_public_sources import native


class Transport:
    def __init__(self, observed, *, fail_benchmark=False):
        self.observed=observed;self.fail_benchmark=fail_benchmark;self.calls=[]

    def get(self,name,interval):
        self.calls.append((name,interval))
        if name=='IHSG' and self.fail_benchmark:
            raise TimeoutError('synthetic transport fixture')
        symbol,zone=('^JKSE','Asia/Jakarta') if name=='IHSG' else ('SPY','America/New_York')
        payload=native(symbol,zone,interval)
        if name=='IHSG':
            rows=[dict(start=int(datetime(2026,10,d,2,tzinfo=timezone.utc).timestamp()),
                       end=int(datetime(2026,10,d,9,tzinfo=timezone.utc).timestamp())) for d in (1,2)]
            result=payload['chart']['result'][0]
            result['meta'].update(tradingPeriods=[[r] for r in rows],currentTradingPeriod={'regular':rows[-1]})
            result.update(timestamp=[r['start'] for r in rows])
        return dict(source_url='https://fixture.test/native',retrieved_at=self.observed.isoformat(),
                    source_sha256='0'*64,payload=payload)


def prepared(tmp_path):
    config,_=setup_host(tmp_path);snap=snapshot(delivery_days='idx_sessions');snap['config']['instruments']=['SPY']
    from morning_brief.store import digest
    snap['config_sha256']=digest(snap['config'])
    import json
    reference=json.loads(Path(config.input_manifest).read_text())['calendar']['path']
    value=json.loads(Path(reference).read_text())
    value['sessions']=[day for day in value['sessions'] if day not in ('2026-10-03','2026-10-04')]
    Path(reference).write_text(json.dumps(value));Path(reference).chmod(0o600)
    return config,snap,reference


def test_collector_writes_actual_retained_inputs_without_posting_or_run_state(tmp_path):
    config,snap,reference=prepared(tmp_path);observed=FREEZE-timedelta(minutes=1)
    transport=Transport(observed)
    result=collect_public(config,snapshot=snap,calendar_path=reference,
        source_cache=tmp_path/'sources',now=observed,transport=transport,clock=lambda:observed)
    assert result['manifest_written'] and result['posts'] is False and result['paid_requests']==0
    assert len(transport.calls)==4 and not Path(config.run_store).exists()
    official,manifest=load_inputs(config.input_manifest,cutoff=FREEZE)
    assert manifest['provenance']=='live-retained'
    assert manifest['numerical']['benchmark']['2026-10-02']==102.
    # Native schedule coverage is insufficient for Sunday US time. Never fill it
    # with guessed hours, but keep the configured instrument's unavailable row.
    assert manifest['global_inputs'][0]['name']=='SPY'
    assert manifest['global_inputs'][0]['sessions']['verified'] is False
    assert 'SPY:verification:ValueError' in result['gaps']
    assert Path(config.input_manifest).stat().st_mode & 0o077==0
    assert len(list((tmp_path/'sources').glob('manifest-*.json')))==1


def test_failed_or_post_cutoff_benchmark_does_not_replace_existing_manifest(tmp_path):
    config,snap,reference=prepared(tmp_path);previous=Path(config.input_manifest).read_bytes()
    for transport in [Transport(FREEZE-timedelta(seconds=30),fail_benchmark=True),Transport(FREEZE+timedelta(seconds=1))]:
        result=collect_public(config,snapshot=snap,calendar_path=reference,
            source_cache=tmp_path/'sources',now=FREEZE-timedelta(minutes=1),transport=transport,
            clock=lambda:FREEZE-timedelta(seconds=10))
        assert not result['manifest_written'] and Path(config.input_manifest).read_bytes()==previous
        assert result['posts'] is False and not Path(config.run_store).exists()


def test_collection_after_a_freeze_never_backfills_that_session(tmp_path):
    import pytest
    config,snap,reference=prepared(tmp_path);transport=Transport(FREEZE)
    # Fixture coverage ends on this session, so there is no authorized future
    # session. A collector must not change its cutoff to rescue today's data.
    with pytest.raises(ValueError):
        collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
            now=FREEZE+timedelta(minutes=1),transport=transport)
    assert transport.calls==[] and not Path(config.run_store).exists()


def test_late_preparation_never_backdates_manifest_availability(tmp_path):
    config,snap,reference=prepared(tmp_path);previous=Path(config.input_manifest).read_bytes()
    observed=FREEZE-timedelta(seconds=30)
    result=collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
        now=observed,transport=Transport(observed),clock=lambda:FREEZE+timedelta(seconds=1))
    assert not result['manifest_written'] and 'preparation_not_visible_at_cutoff' in result['gaps']
    assert Path(config.input_manifest).read_bytes()==previous


def test_full_ihsg_history_is_shared_with_chart_and_reused_without_another_daily_fetch(tmp_path):
    from dataclasses import asdict
    import json
    from morning_brief.runner import jsonable
    from test_yahoo_chart import fixture
    config,snap,reference=prepared(tmp_path)
    calendar,context=fixture()
    cal=jsonable(asdict(calendar));cal.pop('import_digest');cal['verified']=True
    Path(reference).write_text(json.dumps(cal));Path(reference).chmod(0o600)
    observed=FREEZE-timedelta(minutes=1)
    class FullHistory(Transport):
        def get(self,name,interval):
            record=super().get(name,interval)
            if name=='IHSG' and interval=='1d':
                record['payload']=context['daily']['payload']
                record['source_url']=context['daily']['source_url']
            return record
    first=FullHistory(observed)
    result=collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
        now=observed,transport=first,clock=lambda:observed)
    assert result['manifest_written'] and 'ihsg_chart' not in result['incomplete_sections']
    manifest=json.loads(Path(config.input_manifest).read_text())
    assert manifest['chart']['provider']=='yahoo' and len(first.calls)==4
    original=manifest['chart']['daily']
    second=FullHistory(observed+timedelta(seconds=10))
    result=collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
        now=second.observed,transport=second,clock=lambda:second.observed)
    assert result['provider_fetches']==3 and result['history_cache_hits']==1
    assert ('IHSG','1d') not in second.calls
    assert json.loads(Path(config.input_manifest).read_text())['chart']['daily']==original


def test_yahoo_429_persists_shared_cooldown_without_retry_or_next_symbol_fetch(tmp_path,monkeypatch):
    from email.message import Message
    from io import BytesIO
    import json
    from urllib.error import HTTPError
    import pytest
    import morning_brief.public_collector as module
    cache=tmp_path/'source-cache';cache.mkdir(mode=0o700)
    headers=Message();headers['Retry-After']='3600'
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url,429,'rate limited',headers,BytesIO(b''))
    monkeypatch.setattr(module,'build_opener',lambda *_:Opener())
    transport=module.YahooTransport(cache)
    with pytest.raises(HTTPError):transport.get('IHSG','1d')
    assert 'range=1y' in calls[0] and transport.fetches==1
    policy=json.loads((cache/'yahoo-rate-limit.json').read_text())
    assert datetime.fromisoformat(policy['not_before'])-datetime.fromisoformat(policy['observed_at'])==timedelta(hours=1)
    assert (cache/'yahoo-rate-limit.json').stat().st_mode & 0o077==0
    restarted=module.YahooTransport(cache)
    with pytest.raises(ValueError,match='cooldown'):restarted.get('SPY','1d')
    assert len(calls)==1 and restarted.fetches==0


def test_cap_guest_handshake_is_counted_and_never_retained_in_source_url(tmp_path,monkeypatch):
    import json
    import morning_brief.public_collector as module
    cache=tmp_path/'source-cache';cache.mkdir(mode=0o700)
    transport=module.YahooTransport(cache);calls=[]
    def download(url):
        calls.append(url);transport.fetches+=1
        if url.endswith('/getcrumb'):return b'private-guest-value'
        if url=='https://fc.yahoo.com':return b''
        return json.dumps(dict(quoteResponse=dict(error=None,result=[]))).encode()
    monkeypatch.setattr(transport,'_download',download)
    record=transport.cap_quotes(['BBCA'])
    assert transport.fetches==3 and 'crumb=' in calls[-1]
    assert 'private-guest-value' not in json.dumps(record) and 'crumb=' not in record['source_url']
    transport.cap_quotes(['DSSA'])
    assert transport.fetches==4 and not list(cache.iterdir())


def test_bad_or_stale_rotation_cannot_override_verified_benchmark(tmp_path):
    import json
    config,snap,reference=prepared(tmp_path);observed=FREEZE-timedelta(minutes=1)
    from morning_brief.store import digest
    wrong=dict(version=1,provenance='live-retained',available_at=observed.isoformat(),
        calendar_sha256=digest({}),publication_session='2026-10-05',closing_session='2026-10-02',
        numerical={'benchmark':{'2026-10-02':99999}})
    result=collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
        now=observed,transport=Transport(observed),clock=lambda:observed,rotation_snapshot=wrong)
    assert result['manifest_written'] and 'rotation:retained_window_unavailable' in result['gaps']
    actual=json.loads(Path(config.input_manifest).read_text())
    assert actual['numerical']['benchmark']['2026-10-02']==102.


def test_weekday_globals_manifest_does_not_require_or_invent_idx_calendar(tmp_path):
    config,snap,reference=prepared(tmp_path)
    snap['config']['delivery_days']='weekdays'
    from morning_brief.store import digest
    snap['config_sha256']=digest(snap['config'])
    Path(reference).unlink();observed=FREEZE-timedelta(minutes=1);transport=Transport(observed)
    result=collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
        now=observed,transport=transport,clock=lambda:observed)
    assert result['manifest_written'] and result['posts'] is False
    assert set(transport.calls)=={('SPY','1d'),('SPY','60m')}
    calendar,manifest=load_inputs(config.input_manifest,cutoff=FREEZE,allow_calendar_gap=True)
    assert calendar is None and manifest['calendar'] is None
    assert manifest['numerical']=={} and 'chart' not in manifest
    assert len(manifest['global_inputs'])==1 and 'IDX:calendar_unavailable' in result['gaps']


def test_native_session_proof_uses_actual_collection_time_not_future_cutoff(tmp_path,monkeypatch):
    import morning_brief.public_collector as module
    config,snap,reference=prepared(tmp_path);observed=FREEZE-timedelta(hours=3)
    seen=[];real=module.yahoo_sessions
    def spy(name,payload,*,retrieved_at,cutoff):
        seen.append(cutoff);return real(name,payload,retrieved_at=retrieved_at,cutoff=cutoff)
    monkeypatch.setattr(module,'yahoo_sessions',spy)
    collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources',
        now=observed,transport=Transport(observed),clock=lambda:observed)
    assert seen and all(value==observed for value in seen) and all(value<FREEZE for value in seen)
    seen.clear()
    collect_public(config,snapshot=snap,calendar_path=reference,source_cache=tmp_path/'sources2',
        now=observed,transport=Transport(observed),clock=lambda:FREEZE+timedelta(hours=1))
    assert seen and all(value<=FREEZE for value in seen)


def _repair_fixture(*, close=None, volume=1000):
    from datetime import datetime as dt
    stamp=lambda text:int(dt.fromisoformat(text).timestamp())
    rows=[(stamp('2026-10-06T09:00:00+07:00'),99.,101.,98.,100.,900),(stamp('2026-10-07T09:00:00+07:00'),100.,103.,99.,close,volume)]
    meta=dict(symbol='^JKSE',exchangeTimezoneName='Asia/Jakarta',dataGranularity='1d',regularMarketPrice=102.5,
              regularMarketTime=stamp('2026-10-07T16:00:00+07:00'),regularMarketDayHigh=103.,regularMarketDayLow=99.,regularMarketVolume=1000)
    quote={name:[row[i] for row in rows] for i,name in enumerate(('open','high','low','close','volume'),start=1)}
    payload={'chart':{'error':None,'result':[dict(meta=meta,timestamp=[r[0] for r in rows],indicators={'quote':[quote]})]}}
    proof={'sessions':[{'start':'2026-10-06T02:00:00+00:00','end':'2026-10-06T09:00:00+00:00'},
                       {'start':'2026-10-07T02:00:00+00:00','end':'2026-10-07T09:00:00+00:00'}]}
    return dict(payload=payload,source_sha256='a'*64,retrieved_at='2026-10-08T00:29:00+00:00'),dict(payload={},source_sha256='b'*64),proof


def test_null_latest_close_is_filled_with_provenance_and_the_raw_source_hash_is_kept():
    from morning_brief.public_collector import repaired_daily, needs_previous_close
    daily,hourly,proof=_repair_fixture();as_of=datetime(2026,10,8,0,29,tzinfo=timezone.utc)
    assert needs_previous_close('IHSG',daily,proof,as_of) is True
    fixed=repaired_daily('IHSG',daily,hourly,proof,as_of)
    assert fixed['payload']['chart']['result'][0]['indicators']['quote'][0]['close']==[100.,102.5]
    assert fixed['repair']['method']=='meta_regular_market_price' and fixed['repair']['source_sha256']=='a'*64
    assert fixed['source_sha256']=='a'*64 and needs_previous_close('IHSG',fixed,proof,as_of) is False
    assert daily['payload']['chart']['result'][0]['indicators']['quote'][0]['close'][-1] is None


def test_disagreeing_payload_and_fx_are_left_untouched():
    from morning_brief.public_collector import repaired_daily
    daily,hourly,proof=_repair_fixture(volume=500);as_of=datetime(2026,10,8,0,29,tzinfo=timezone.utc)
    assert repaired_daily('IHSG',daily,hourly,proof,as_of) is daily
    daily,hourly,proof=_repair_fixture()
    assert repaired_daily('USDIDR',daily,hourly,proof,as_of) is daily


def test_previous_close_request_is_a_single_one_day_chart(tmp_path,monkeypatch):
    import morning_brief.public_collector as module
    cache=tmp_path/'cache';cache.mkdir(mode=0o700)
    transport=module.YahooTransport(cache);urls=[]
    monkeypatch.setattr(transport,'_record',lambda url,**_:urls.append(url) or {})
    transport.get('KOSPI','prev');transport.get('KOSPI','1d')
    assert 'interval=1d&range=1d&' in urls[0] and 'interval=1d&range=1mo&' in urls[1]
    import pytest
    with pytest.raises(ValueError):transport.get('KOSPI','5d')
