from datetime import timedelta
from itertools import islice, product
import json

import pytest
from sectors_client import Config, SectorsClient
from sectors_client.models import TransportFailure
from morning_brief.sectors_caps import collect_caps, configured_rotation
from morning_brief.scheduled import ProducerConfig
from test_rotation_collector import setup


class Pages:
    def __init__(self,count=201,fail=False):
        self.rows=[dict(symbol=''.join(s),query_values=dict(market_cap=100))
                   for s in islice(product('ABCDEFGHIJKLMNOPQRSTUVWXYZ',repeat=4),count)]
        self.fail=fail;self.calls=[]

    def get(self,identity):
        self.calls.append(identity)
        if self.fail:raise TransportFailure('fixture')
        offset=dict(identity.query)['offset'];rows=self.rows[offset:offset+200]
        more=offset+len(rows)<len(self.rows)
        return dict(results=rows,pagination=dict(total_count=len(self.rows),limit=200,offset=offset,
            showing=len(rows),has_next=more,next_offset=offset+len(rows) if more else None))


def invoke(tmp_path,index,pages,now,limit=3):
    cache=tmp_path/'sources';cache.mkdir(mode=0o700,exist_ok=True)
    client=SectorsClient(Config(store_path=tmp_path/'shared.sqlite3',caller='morning-brief',
        billing_window='2026-10',cache_only=False,api_key='fixture'),transport=pages,clock=lambda:now)
    return collect_caps(client,cache=cache,index=index,persist=lambda:None,now=now,
                        cutoff=now+timedelta(hours=1),request_limit=limit)


def test_partial_refresh_resumes_shared_pages_and_fresh_snapshot_fetches_nothing(tmp_path):
    now=setup()[3];index={};pages=Pages()
    raw,calls,gaps=invoke(tmp_path,index,pages,now,limit=1)
    assert raw is None and calls==1 and gaps==['caps:refresh_incomplete']
    generation=index['sectors_caps']['pending']
    raw,calls,gaps=invoke(tmp_path,index,pages,now,limit=1)
    assert len(raw['values'])==201 and calls==1 and not gaps
    assert raw['identity']==generation and len(pages.calls)==2
    initial=dict(raw)
    raw,calls,gaps=invoke(tmp_path,index,pages,now+timedelta(days=29))
    assert raw==initial and calls==0 and not gaps and len(pages.calls)==2
    renewed,calls,gaps=invoke(tmp_path,index,pages,now+timedelta(days=30))
    assert calls==2 and not gaps and renewed['identity']!=generation
    assert renewed['collected_at']!=(initial['collected_at'])


def test_incomplete_expired_refresh_never_replaces_complete_snapshot(tmp_path):
    now=setup()[3];index={};pages=Pages()
    original,_,_=invoke(tmp_path,index,pages,now)
    raw,calls,gaps=invoke(tmp_path,index,pages,now+timedelta(days=30),limit=1)
    assert raw==original and calls==1 and gaps==['caps:refresh_incomplete']
    renewed,calls,gaps=invoke(tmp_path,index,pages,now+timedelta(days=30),limit=1)
    assert len(renewed['values'])==201 and calls==1 and not gaps


def test_retained_cap_corruption_and_future_evidence_fail_closed(tmp_path):
    now=setup()[3];index={}
    invoke(tmp_path,index,Pages(2),now)
    with pytest.raises(ValueError,match='future'):invoke(tmp_path,index,Pages(2),now-timedelta(seconds=1))
    identity=index['sectors_caps']['current']['sha256']
    (tmp_path/'sources'/('sectors-caps-'+identity+'.json')).write_text('{}')
    with pytest.raises(ValueError,match='digest'):invoke(tmp_path,index,Pages(2),now)


def test_duplicate_pagination_cannot_replace_prior_snapshot(tmp_path):
    now=setup()[3];index={};pages=Pages()
    original,_,_=invoke(tmp_path,index,pages,now)
    pages.rows[-1]=pages.rows[0]
    raw,_,gaps=invoke(tmp_path,index,pages,now+timedelta(days=30))
    assert raw==original and gaps==['caps:ValueError']


def test_configuration_is_paired_lazy_and_uses_shared_store(tmp_path,monkeypatch):
    producer=ProducerConfig(1,str(tmp_path/'calendar'),str(tmp_path/'refs'),str(tmp_path/'sources'),
        sectors_store_path=str(tmp_path/'shared.sqlite3'),sectors_key_file=str(tmp_path/'key'))
    with pytest.raises(ValueError):ProducerConfig(1,'/calendar','/refs','/sources',sectors_store_path='/store')
    seen=[]
    wrapped=configured_rotation(producer,lambda **kw:seen.append(kw) or 'result')
    assert not (tmp_path/'shared.sqlite3').exists()
    (tmp_path/'key').write_text('SECTORS_API_KEY=fixture\n')
    now=setup()[3]
    assert wrapped(now=now,clock=lambda:now)=='result'
    client=seen[0]['sectors_client']
    assert client.config.store_path==tmp_path/'shared.sqlite3'
    assert client.config.billing_window=='2026-10'
    assert client.config.caller_limit is None


def test_cap_pages_stop_when_network_latency_crosses_cutoff(tmp_path):
    now=setup()[3];cutoff=now+timedelta(seconds=1);cache=tmp_path/'sources';cache.mkdir(mode=0o700)
    pages=Pages();index={};ticks=iter([now,now,cutoff])
    client=SectorsClient(Config(store_path=tmp_path/'shared.sqlite3',caller='morning-brief',
        billing_window='2026-10',cache_only=False,api_key='fixture'),transport=pages,clock=lambda:now)
    raw,calls,gaps=collect_caps(client,cache=cache,index=index,persist=lambda:None,
        now=now,cutoff=cutoff,request_limit=3,clock=lambda:next(ticks))
    assert raw is None and calls==1 and gaps==['caps:cutoff_reached']
    assert len(pages.calls)==1 and 'current' not in index['sectors_caps']
