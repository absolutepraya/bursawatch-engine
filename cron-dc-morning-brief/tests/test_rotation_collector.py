from copy import deepcopy
from datetime import datetime, date, timedelta, timezone
import json

import pytest

from morning_brief.inputs import MembershipSnapshot, Provenance
from morning_brief.rotation_collector import collect_rotation, retained_rotation
from morning_brief.store import digest
from test_yahoo_chart import fixture


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

    def cap_quotes(self,symbols):
        self.fetches+=3 if self.crumb is None else 1;self.crumb='fixture';self.calls.append(('caps',tuple(symbols)))
        payload=dict(quoteResponse=dict(error=None,result=[dict(symbol=s+'.JK',currency='IDR',quoteType='EQUITY',
            exchangeTimezoneName='Asia/Jakarta',marketCap=1000 if s=='BBCA' else 2000) for s in symbols if s not in self.missing]))
        return self.record('v7/finance/quote',payload)

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


def collect(cache,values,transport,limit=24):
    calendar,session,cutoff,now,memberships=values
    return collect_rotation(memberships=memberships,calendar=calendar,publication_session=session,
        cutoff=cutoff,source_cache=cache,now=now,transport=transport,clock=lambda:now,request_limit=limit)


def read(cache):return json.loads((cache/'rotation-current.json').read_text())


def test_resumable_budget_includes_guest_handshake_and_frozen_sources(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values
    cache=tmp_path/'sources';first=Transport(now,calendar,session)
    result=collect(cache,values,first,limit=3)
    assert result['provider_fetches']==3 and result['prices_verified']==0
    second=Transport(now,calendar,session)
    result=collect(cache,values,second,limit=3)
    assert result['prices_verified']==2 and result['cap_baskets_verified']==3
    assert result['provider_fetches']==2 and all(c[0]=='history' for c in second.calls)
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


def test_partial_current_caps_fall_back_per_basket_without_relabeling_age(tmp_path):
    old=setup();cache=tmp_path/'sources';calendar,session,cutoff,now,memberships=old
    collect(cache,old,Transport(now,calendar,session))
    original=read(cache)['numerical']['caps_by_basket']
    new_session=date(2026,10,12);new_cutoff=cutoff+timedelta(days=7);new_now=now+timedelta(days=7)
    # Refresh calendar checking evidence, keep the same official session list.
    calendar=type(calendar)(**{**calendar.__dict__,'amendment_checked_at':new_now-timedelta(days=1)})
    values=calendar,new_session,new_cutoff,new_now,memberships
    collect(cache,values,Transport(new_now,calendar,new_session,missing=('DSSA',)))
    actual=read(cache)['numerical']['caps_by_basket']
    assert actual['sectors']['First']['collected_at']==new_now.isoformat()
    assert actual['sectors']['Second']==original['sectors']['Second']
    assert actual['konglo']['Both']==original['konglo']['Both']
    expired_session=date(2026,10,19);expired_cutoff=new_cutoff+timedelta(days=7);expired_now=new_now+timedelta(days=7)
    calendar=type(calendar)(**{**calendar.__dict__,'amendment_checked_at':expired_now-timedelta(days=1)})
    values=calendar,expired_session,expired_cutoff,expired_now,memberships
    result=collect(cache,values,Transport(expired_now,calendar,expired_session,missing=('DSSA',)))
    assert 'Second' not in read(cache)['numerical']['caps_by_basket']['sectors']
    assert not read(cache)['numerical']['caps_by_basket']['konglo']
    assert 'konglo:caps_unavailable:Both' in result['gaps']


def test_invalid_stock_is_retained_for_window_and_never_refetched_on_every_tick(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values;cache=tmp_path/'sources'
    result=collect(cache,values,Transport(now,calendar,session,zero_volume=True))
    assert result['prices_verified']==0 and result['provider_fetches']==5
    result=collect(cache,values,Transport(now,calendar,session))
    assert result['provider_fetches']==0 and result['prices_verified']==0


def test_history_failure_stops_pass_without_retry_or_provider_switch(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values
    transport=Transport(now,calendar,session,fail_history=True)
    result=collect(tmp_path/'sources',values,transport)
    assert result['provider_fetches']==4 and 'history:TimeoutError' in result['gaps']
    assert len([c for c in transport.calls if c[0]=='history'])==1


def test_preview_stale_calendar_or_future_window_cannot_enter_manifest(tmp_path):
    values=setup();calendar,session,cutoff,now,_=values;cache=tmp_path/'sources'
    collect(cache,values,Transport(now,calendar,session))
    value=read(cache)
    for key,replacement in [('provenance','preview'),('publication_session','2026-10-06'),
                            ('available_at',(cutoff+timedelta(seconds=1)).isoformat()),('calendar_sha256','c'*64)]:
        wrong=dict(value,**{key:replacement})
        with pytest.raises(ValueError):retained_rotation(wrong,calendar=calendar,publication_session=session,cutoff=cutoff)
