from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
import pytest
import sectors_client as sc

NOW = datetime(2026,10,5,tzinfo=timezone.utc)


def identity(offset=0,session='2026-10-02'):
    return sc.RequestIdentity('/v2/close/',dict(date=session,limit=2,offset=offset))


def page(offset=0,session='2026-10-02'):
    rows = [{'symbol':s,'date':session,'close':p} for s,p in ([('BBCA',8000),('BBRI',4000)] if offset==0 else [('TLKM',3000)])]
    return {'results':rows,'pagination':{'total_count':3,'showing':len(rows),'limit':2,'offset':offset,'has_next':offset==0,'has_previous':offset>0,'next_offset':2 if offset==0 else None,'previous_offset':0 if offset else None}}


def config(tmp_path,**kwargs):
    return sc.Config(**(dict(store_path=tmp_path/'cache.sqlite3',caller='morning',billing_window='oct',caller_limit=40,cache_only=False,api_key='fake-key') | kwargs))


def client(tmp_path,transport,**kwargs):
    return sc.SectorsClient(config(tmp_path,**kwargs),transport=transport,clock=lambda:NOW)


class Fake:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.requests = []
    def get(self,request):
        self.requests.append(request)
        outcome = next(self.outcomes)
        if isinstance(outcome,Exception):
            raise outcome
        return outcome


def test_success_is_durable_and_cutoff_scoped(tmp_path):
    fake = Fake([page()])
    a = client(tmp_path,fake)
    assert a.get(identity(),cutoff=NOW,max_cost=1).payload['results'][0]['close'] == 8000
    b = client(tmp_path,Fake([]),cache_only=True)
    assert b.get(identity(),cutoff=NOW,max_cost=1).payload['pagination']['total_count'] == 3
    with pytest.raises(sc.CacheMiss):
        b.get(identity(),cutoff=NOW-timedelta(seconds=1),max_cost=1)
    assert len(fake.requests)==1
    assert a.store.usage('oct','morning') == {'host_reserved':1,'caller_reserved':1}
    assert (tmp_path/'cache.sqlite3').stat().st_mode & 0o777 == 0o600


def test_identical_concurrent_clients_share_one_fetch(tmp_path):
    entered, release = Event(), Event()
    class Slow:
        requests = 0
        def get(self,request):
            self.requests += 1
            entered.set()
            assert release.wait(2)
            return page()
    fake = Slow()
    a,b = client(tmp_path,fake),client(tmp_path,fake,caller='other')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(a.get,identity(),cutoff=NOW,max_cost=1)
        assert entered.wait(2)
        second = pool.submit(b.get,identity(),cutoff=NOW,max_cost=1)
        release.set()
        assert first.result().payload == second.result().payload
    assert fake.requests == 1
    assert a.store.usage('oct','other') == {'host_reserved':1,'caller_reserved':0}


def test_budget_denial_never_fetches_and_higher_client_limit_cannot_bypass(tmp_path):
    fake = Fake([page()])
    a = client(tmp_path,fake,caller_limit=1,host_limit=1)
    a.get(identity(),cutoff=NOW,max_cost=1)
    b = client(tmp_path,fake,caller='other',caller_limit=40,host_limit=1000)
    with pytest.raises(sc.BudgetDenied):
        b.get(identity(2),cutoff=NOW,max_cost=1)
    assert len(fake.requests)==1


def test_uncertain_outcome_is_reserved_and_never_automatically_retried(tmp_path):
    fake = Fake([sc.UncertainOutcome('billing unknown'),page()])
    a = client(tmp_path,fake)
    with pytest.raises(sc.UncertainOutcome):
        a.get(identity(),cutoff=NOW,max_cost=2)
    b = client(tmp_path,fake)
    with pytest.raises(sc.UncertainOutcome):
        b.get(identity(),cutoff=NOW,max_cost=2,retry=True)
    assert len(fake.requests)==1
    assert b.store.usage('oct','morning')['host_reserved']==2


def test_crashed_expired_lease_cannot_be_stolen(tmp_path):
    fake = Fake([])
    a = client(tmp_path,fake,lease_seconds=1)
    a.store.reserve(identity(),a.config,max_cost=2,now=NOW)
    b = sc.SectorsClient(a.config,transport=fake,clock=lambda:NOW+timedelta(seconds=2))
    with pytest.raises(sc.UncertainOutcome):
        b.get(identity(),cutoff=NOW+timedelta(seconds=2),max_cost=2)
    assert fake.requests==[]
    assert b.store.usage('oct','morning')['host_reserved']==2


def test_throttle_requires_explicit_bounded_retry_with_new_reservation(tmp_path):
    fake = Fake([sc.Throttled(0),sc.Throttled(0),page()])
    a = client(tmp_path,fake,max_attempts=2)
    for retry in (False,True):
        with pytest.raises(sc.Throttled):
            a.get(identity(),cutoff=NOW,max_cost=2,retry=retry)
    with pytest.raises(sc.RetryExhausted):
        a.get(identity(),cutoff=NOW,max_cost=2,retry=True)
    assert len(fake.requests)==2
    assert a.store.usage('oct','morning')['host_reserved']==4


def test_retry_honors_cooldown_without_wait_or_fetch(tmp_path):
    fake = Fake([sc.Throttled(30),page()])
    a = client(tmp_path,fake)
    with pytest.raises(sc.Throttled):
        a.get(identity(),cutoff=NOW,max_cost=1)
    with pytest.raises(sc.Throttled) as error:
        a.get(identity(),cutoff=NOW,max_cost=1,retry=True)
    assert error.value.retry_after == 30
    assert len(fake.requests)==1


def test_interrupted_pagination_resumes_only_missing_page(tmp_path):
    fake = Fake([page(),sc.Throttled(0),page(2)])
    a = client(tmp_path,fake)
    with pytest.raises(sc.Throttled):
        a.close_session('2026-10-02',cutoff=NOW,page_limit=2,max_cost=1)
    result = a.close_session('2026-10-02',cutoff=NOW,page_limit=2,max_cost=1,retry=True)
    assert result.complete
    assert [r['symbol'] for r in result.rows] == ['BBCA','BBRI','TLKM']
    assert [dict(r.query)['offset'] for r in fake.requests] == [0,2,2]


def test_cache_only_partial_pagination_reports_missing_pages(tmp_path):
    a = client(tmp_path,Fake([page()]))
    a.get(identity(),cutoff=NOW,max_cost=1)
    b = client(tmp_path,Fake([]),cache_only=True)
    result = b.close_session('2026-10-02',cutoff=NOW,page_limit=2,max_cost=1)
    assert not result.complete
    assert result.total==3 and result.missing_offsets==(2,)


@pytest.mark.parametrize('mutate',[
    lambda p:p['results'][0].update(date='2026-10-01'),
    lambda p:p['results'][0].update(symbol='bad symbol'),
    lambda p:p['pagination'].update(offset=30),
    lambda p:p['pagination'].update(total_count=1),
    lambda p:p['pagination'].update(next_offset=0),
])
def test_invalid_pages_are_never_cached(tmp_path,mutate):
    p=page();mutate(p)
    a=client(tmp_path,Fake([p]))
    with pytest.raises(sc.ValidationError):
        a.get(identity(),cutoff=NOW,max_cost=1)
    with pytest.raises(sc.CacheMiss):
        a.store.get(identity(),cutoff=NOW)


def test_per_session_pagination_does_not_reuse_another_dates_offsets(tmp_path):
    fake=Fake([page(),page(2),page(session='2026-09-11'),page(2,session='2026-09-11')])
    a=client(tmp_path,fake)
    a.close_session('2026-10-02',cutoff=NOW,page_limit=2,max_cost=1)
    a.close_session('2026-09-11',cutoff=NOW,page_limit=2,max_cost=1)
    assert [(dict(r.query)['date'],dict(r.query)['offset']) for r in fake.requests] == [('2026-10-02',0),('2026-10-02',2),('2026-09-11',0),('2026-09-11',2)]


def test_cache_cutoff_never_triggers_a_paid_refetch(tmp_path):
    fake=Fake([page(),page()])
    a=client(tmp_path,fake)
    a.get(identity(),cutoff=NOW,max_cost=1)
    with pytest.raises(sc.CacheMiss):
        a.get(identity(),cutoff=NOW-timedelta(seconds=1),max_cost=1)
    assert len(fake.requests)==1


def test_page_total_changes_or_duplicate_members_make_session_incomplete(tmp_path):
    for duplicate in (True,False):
        folder=tmp_path/str(duplicate);folder.mkdir()
        p=page(2)
        if duplicate:
            p['results'][0]['symbol']='BBCA'
        else:
            p['pagination']['total_count']=4
            p['pagination']['has_next']=True
            p['pagination']['next_offset']=4
        a=client(folder,Fake([page(),p]))
        with pytest.raises(sc.ValidationError):
            a.close_session('2026-10-02',cutoff=NOW,page_limit=2)


def test_unexpected_transport_exception_is_sanitized_and_reserved(tmp_path):
    a=client(tmp_path,Fake([RuntimeError('private-key')]))
    with pytest.raises(sc.UncertainOutcome) as error:
        a.get(identity(),cutoff=NOW,max_cost=1)
    assert 'private-key' not in str(error.value)
    assert error.value.__suppress_context__
    assert a.store.usage('oct','morning')['host_reserved']==1


def test_invalid_zero_credit_cost_never_fetches(tmp_path):
    fake=Fake([])
    a=client(tmp_path,fake)
    for cost in (0,-1,True,0.5):
        with pytest.raises(sc.ValidationError):
            a.get(identity(),cutoff=NOW,max_cost=cost)
    assert fake.requests==[]


def test_authoritative_reconciliation_is_explicit_and_durable(tmp_path):
    a=client(tmp_path,Fake([sc.UncertainOutcome('unknown'),page()]))
    with pytest.raises(sc.UncertainOutcome):
        a.get(identity(),cutoff=NOW,max_cost=2)
    status=a.store.request_status(identity())
    assert status['state']=='uncertain'
    with pytest.raises(sc.ValidationError):
        a.store.reconcile(identity(),token=status['token'],charged_cost=0,evidence_digest='unverified')
    a.store.reconcile(identity(),token=status['token'],charged_cost=0,evidence_digest='a'*64)
    assert a.store.usage('oct','morning')['host_reserved']==0
    with pytest.raises(sc.UncertainOutcome):
        a.get(identity(),cutoff=NOW,max_cost=2)
    assert a.get(identity(),cutoff=NOW,max_cost=2,retry=True).payload['pagination']['total_count']==3
    assert a.store.usage('oct','morning')['host_reserved']==2


def test_correction_versions_preserve_prior_cutoff_and_survive_store_reopen(tmp_path):
    a=client(tmp_path,Fake([page()]))
    a.get(identity(),cutoff=NOW,max_cost=1)
    correction=page();correction['results'][0]['close']=8100
    a.store.save(identity(),correction,available_at=NOW+timedelta(hours=1),provenance='provider-https')
    b=client(tmp_path,Fake([]),cache_only=True)
    assert b.get(identity(),cutoff=NOW,max_cost=1).payload['results'][0]['close']==8000
    assert b.get(identity(),cutoff=NOW+timedelta(hours=1),max_cost=1).payload['results'][0]['close']==8100
