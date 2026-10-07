from copy import deepcopy
from datetime import datetime, date, timedelta, timezone
import json

import pytest

from morning_brief.inputs import MembershipSnapshot, Provenance
from morning_brief.rotation_collector import collect_rotation, retained_rotation
from morning_brief.store import digest
from test_yahoo_chart import fixture
from sectors_client import Config, SectorsClient
from sectors_client.models import TransportFailure


def setup():
    calendar,_=fixture()
    days=tuple(date(2026,1,1)+timedelta(days=i) for i in range(365)
               if (date(2026,1,1)+timedelta(days=i)).weekday()<5)
    calendar=type(calendar)(**{**calendar.__dict__,'sessions':days})
    session=date(2026,10,5); cutoff=datetime(2026,10,5,0,30,tzinfo=timezone.utc)
    now=cutoff-timedelta(hours=1)
    provenance=Provenance('https://fixture.test/membership','a'*64,'synthetic-explicit','test')
    memberships=dict(sectors=MembershipSnapshot('fixture',{'First':('BBCA',),'Second':('DSSA',)},provenance),
        konglo=MembershipSnapshot('fixture',{'Both':('BBCA','DSSA')},provenance))
    return calendar,session,cutoff,now,memberships


class Transport:
    def __init__(self,now,calendar,session,*,missing=(),fail_history=False,zero_volume=False):
        self.now=now;self.calendar=calendar;self.session=session;self.missing=missing
        self.fail_history=fail_history;self.zero_volume=zero_volume
        self.fetches=0;self.crumb=None;self.calls=[]

    def stock_history(self,ticker):
        self.fetches+=1;self.calls.append(('history',ticker))
        if self.fail_history: raise TimeoutError('synthetic')
        through=self.calendar.last_sessions(self.session,2)[0]
        sessions=self.calendar.last_sessions(through,18)
        stamps=[int(datetime(day.year,day.month,day.day,2,tzinfo=timezone.utc).timestamp()) for day in sessions]
        prices=[100+i for i in range(18)];volumes=[1000]*18
        if self.zero_volume:volumes[-1]=0
        row=dict(meta=dict(symbol=ticker+'.JK',exchangeTimezoneName='Asia/Jakarta',dataGranularity='1d',
            currency='IDR',instrumentType='EQUITY'),timestamp=stamps,
            indicators=dict(quote=[dict(open=prices,high=prices,low=prices,close=prices,volume=volumes)]))
        return self.record('v8/finance/chart/'+ticker+'.JK?events=div%2Csplits',dict(chart=dict(error=None,result=[row])))

    def record(self,path,payload):
        return dict(source_url='https://query1.finance.yahoo.com/'+path,
                    retrieved_at=self.now.isoformat(),source_sha256='a'*64,payload=payload)


class CapTransport:
    def __init__(self, *, missing=(), fail=False):
        self.missing=missing;self.fail=fail;self.calls=[]

    def get(self,identity):
        self.calls.append(identity)
        if self.fail:raise TransportFailure('fixture failure')
        rows=[dict(symbol=s+'.JK',query_values=dict(market_cap=1000 if s=='BBCA' else 2000))
              for s in ('BBCA','DSSA') if s not in self.missing]
        return dict(results=rows,pagination=dict(total_count=len(rows),limit=200,offset=0,
                    showing=len(rows),has_next=False,next_offset=None))


def cap_client(cache,now,transport=None):
    config=Config(store_path=cache.parent/'shared-sectors.sqlite3',caller='morning-brief',
                  billing_window='2026-10',cache_only=False,api_key='fixture')
    return SectorsClient(config,transport=transport or CapTransport(),clock=lambda:now)


def collect(cache,values,transport,limit=24,cap_transport=None):
    calendar,session,cutoff,now,memberships=values
    return collect_rotation(memberships=memberships,calendar=calendar,publication_session=session,
        cutoff=cutoff,source_cache=cache,now=now,transport=transport,clock=lambda:now,request_limit=limit,
        sectors_client=cap_client(cache,now,cap_transport))


def read(cache):return json.loads((cache/'rotation-current.json').read_text())


def test_shared_caps_and_history_respect_budget_and_frozen_sources(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values
    cache=tmp_path/'sources';first=Transport(now,calendar,session)
    result=collect(cache,values,first,limit=3)
    assert result['provider_fetches']==2 and result['sectors_request_attempts']==1 and result['prices_verified']==2
    second=Transport(now,calendar,session)
    result=collect(cache,values,second,limit=3)
    assert result['prices_verified']==2 and result['cap_baskets_verified']==3
    assert result['provider_fetches']==0 and result['sectors_request_attempts']==0
    third=Transport(now,calendar,session)
    result=collect(cache,values,third)
    assert result['provider_fetches']==0 and result['history_cache_hits']==2
    value=read(cache);assert retained_rotation(value,calendar=calendar,publication_session=session,cutoff=cutoff)==value['numerical']
    assert all(p.stat().st_mode & 0o077==0 for p in cache.iterdir())
    # Index contains only references, not duplicated full provider responses.
    assert 'payload' not in (cache/'rotation-index.json').read_text()
    first_source=next(iter(value['numerical']['price_attestations'].values()))['evidence_ref']
    from pathlib import Path
    Path(first_source).write_text('{}')
    with pytest.raises(ValueError,match='digest'):collect(cache,values,third)


def test_failed_expired_refresh_keeps_original_caps_and_collects_new_prices(tmp_path):
    old=setup();cache=tmp_path/'sources';calendar,session,cutoff,now,memberships=old
    collect(cache,old,Transport(now,calendar,session))
    original=read(cache)['numerical']['caps_by_basket']
    new_session=date(2026,11,9);new_cutoff=cutoff+timedelta(days=35);new_now=now+timedelta(days=35)
    calendar=type(calendar)(**{**calendar.__dict__,'amendment_checked_at':new_now-timedelta(days=1)})
    values=calendar,new_session,new_cutoff,new_now,memberships
    failed=CapTransport(fail=True)
    result=collect(cache,values,Transport(new_now,calendar,new_session),cap_transport=failed)
    assert read(cache)['numerical']['caps_by_basket']==original
    assert result['prices_verified']==2 and result['sectors_request_attempts']==1
    assert 'caps:TransportFailure' in result['gaps']
    # Same pending generation does not silently retry a failed paid request.
    result=collect(cache,values,Transport(new_now,calendar,new_session),cap_transport=failed)
    assert len(failed.calls)==1
    assert read(cache)['numerical']['caps_by_basket']==original


def test_missing_caps_only_exclude_unknown_members(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values;cache=tmp_path/'sources'
    result=collect(cache,values,Transport(now,calendar,session),cap_transport=CapTransport(missing=('DSSA',)))
    actual=read(cache)['numerical']
    assert actual['caps_by_basket']['konglo']['Both']['values']=={'BBCA':1000.}
    assert set(actual['prices'])=={'BBCA'}
    assert result['cap_baskets_verified']==2


def test_invalid_stock_is_retained_for_window_and_never_refetched_on_every_tick(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values;cache=tmp_path/'sources'
    result=collect(cache,values,Transport(now,calendar,session,zero_volume=True))
    assert result['prices_verified']==0 and result['provider_fetches']==2
    result=collect(cache,values,Transport(now,calendar,session))
    assert result['provider_fetches']==0 and result['prices_verified']==0


def test_history_failure_stops_pass_without_retry_or_provider_switch(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values
    transport=Transport(now,calendar,session,fail_history=True)
    result=collect(tmp_path/'sources',values,transport)
    assert result['provider_fetches']==1 and 'history:TimeoutError' in result['gaps']
    assert len([c for c in transport.calls if c[0]=='history'])==1


def test_preview_stale_calendar_or_future_window_cannot_enter_manifest(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values;cache=tmp_path/'sources'
    collect(cache,values,Transport(now,calendar,session))
    value=read(cache)
    for key,replacement in [('provenance','preview'),('publication_session','2026-10-06'),
                            ('available_at',(cutoff+timedelta(seconds=1)).isoformat()),('calendar_sha256','c'*64)]:
        wrong=dict(value,**{key:replacement})
        with pytest.raises(ValueError):retained_rotation(wrong,calendar=calendar,publication_session=session,cutoff=cutoff)


def test_network_latency_does_not_reject_cutoff_visible_fresh_prices(tmp_path):
    calendar,session,cutoff,now,memberships=setup();cache=tmp_path/'sources'
    observed=now+timedelta(seconds=1)
    result=collect_rotation(memberships=memberships,calendar=calendar,publication_session=session,
        cutoff=cutoff,source_cache=cache,now=now,transport=Transport(observed,calendar,session),
        clock=lambda:observed,sectors_client=cap_client(cache,observed))
    assert result['prices_verified']==2 and not result['gaps']
