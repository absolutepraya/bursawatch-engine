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


@pytest.mark.parametrize('hint',[None,'invalid','999999999999999999'])
def test_unknown_throttle_reconciliation_is_audited_and_explicit(tmp_path,hint):
    import io
    from urllib.error import HTTPError
    requests=[]
    class Response(io.BytesIO):
        status=200
        headers={}
        def geturl(self):
            return identity().url
    def open_(request,timeout):
        import json
        requests.append(request.full_url)
        if len(requests)==1:
            headers={} if hint is None else {'Retry-After':hint}
            raise HTTPError(request.full_url,429,'synthetic throttle',headers,io.BytesIO(b'{}'))
        return Response(json.dumps(page()).encode())
    a=client(tmp_path,sc.HTTPTransport(config(tmp_path),opener=open_))
    with pytest.raises(sc.Throttled) as error:
        a.get(identity(),cutoff=NOW,max_cost=2)
    assert error.value.retry_after is None
    status=a.store.request_status(identity())
    with pytest.raises(sc.Throttled):
        a.get(identity(),cutoff=NOW,max_cost=2,retry=True)
    assert len(requests)==1
    assert a.store.usage('oct','morning')['host_reserved']==2
    for changes in ({'token':'incorrect'},{'evidence_digest':'invalid'},{'charged_cost':3}):
        with pytest.raises(sc.ValidationError):
            a.store.reconcile(identity(),**(dict(token=status['token'],charged_cost=1,evidence_digest='a'*64,now=NOW)|changes))
    assert a.store.usage('oct','morning')['host_reserved']==2
    a.store.reconcile(identity(),token=status['token'],charged_cost=1,evidence_digest='a'*64,now=NOW)
    b=client(tmp_path,a.transport)
    with b.store.connection() as db:
        audit=dict(db.execute('SELECT * FROM reconciliations WHERE token=?',(status['token'],)).fetchone())
    assert audit=={'token':status['token'],'reserved_cost':2,'charged_cost':1,'evidence_digest':'a'*64}
    assert b.store.usage('oct','morning')['host_reserved']==1
    with pytest.raises(sc.UncertainOutcome):
        b.get(identity(),cutoff=NOW,max_cost=2)
    assert len(requests)==1
    assert b.get(identity(),cutoff=NOW,max_cost=2,retry=True).payload['pagination']['total_count']==3
    assert len(requests)==2
    assert b.store.usage('oct','morning')['host_reserved']==3


def test_reconciled_throttle_still_enforces_shared_attempt_ceiling(tmp_path):
    fake=Fake([sc.Throttled(None),page()])
    a=client(tmp_path,fake,max_attempts=1)
    with pytest.raises(sc.Throttled):
        a.get(identity(),cutoff=NOW,max_cost=2)
    status=a.store.request_status(identity())
    a.store.reconcile(identity(),token=status['token'],charged_cost=0,evidence_digest='a'*64,now=NOW)
    with pytest.raises(sc.RetryExhausted):
        a.get(identity(),cutoff=NOW,max_cost=2,retry=True)
    assert len(fake.requests)==1
    assert a.store.usage('oct','morning')['host_reserved']==0


def test_throttle_reconciliation_preserves_verified_cooldown(tmp_path):
    a=client(tmp_path,Fake([sc.Throttled(30)]))
    with pytest.raises(sc.Throttled):
        a.get(identity(),cutoff=NOW,max_cost=2)
    status=a.store.request_status(identity())
    with pytest.raises(sc.ValidationError):
        a.store.reconcile(identity(),token=status['token'],charged_cost=1,evidence_digest='a'*64,now=NOW)
    assert a.store.usage('oct','morning')['host_reserved']==2
    a.store.reconcile(identity(),token=status['token'],charged_cost=1,evidence_digest='a'*64,now=NOW+timedelta(seconds=30))
    assert a.store.request_status(identity())['state']=='resolved'


def test_same_generation_deduplicates_and_new_generation_is_separately_budgeted(tmp_path):
    entered,release=Event(),Event()
    class Weekly:
        requests=[]
        def get(self,request):
            self.requests.append(request)
            if len(self.requests)==1:
                entered.set()
                assert release.wait(2)
            return {'results':[{'symbol':'BBCA','market_cap':100}]}
    fake=Weekly()
    first=sc.RequestIdentity('/v2/companies/',{'offset':0,'limit':200},generation='caps:2026-W41')
    next_week=sc.RequestIdentity('/v2/companies/',{'offset':0,'limit':200},generation='caps:2026-W42')
    beyond_limit=sc.RequestIdentity('/v2/companies/',{'offset':0,'limit':200},generation='caps:2026-W43')
    a,b=client(tmp_path,fake,caller_limit=2,host_limit=2),client(tmp_path,fake,caller='other',caller_limit=2,host_limit=2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(a.get,first,cutoff=NOW,max_cost=1)
        assert entered.wait(2)
        duplicate=pool.submit(b.get,first,cutoff=NOW,max_cost=1)
        release.set()
        assert one.result().identity.generation==duplicate.result().identity.generation=='caps:2026-W41'
    assert len(fake.requests)==1
    assert a.get(next_week,cutoff=NOW,max_cost=1).identity.generation=='caps:2026-W42'
    assert len(fake.requests)==2 and fake.requests[0].url==fake.requests[1].url
    assert a.store.usage('oct','morning')=={'host_reserved':2,'caller_reserved':2}
    with pytest.raises(sc.BudgetDenied):
        b.get(beyond_limit,cutoff=NOW,max_cost=1)
    assert len(fake.requests)==2


def test_generation_cache_cutoffs_and_uncertain_reservations_are_isolated(tmp_path):
    fake=Fake([{'results':[{'symbol':'BBCA','market_cap':100}]},sc.UncertainOutcome('unknown')])
    first=sc.RequestIdentity('/v2/companies/',generation='caps:2026-W41')
    next_week=sc.RequestIdentity('/v2/companies/',generation='caps:2026-W42')
    a=client(tmp_path,fake)
    a.get(first,cutoff=NOW,max_cost=1)
    b=sc.SectorsClient(a.config,transport=fake,clock=lambda:NOW+timedelta(days=7))
    with pytest.raises(sc.UncertainOutcome):
        b.get(next_week,cutoff=NOW+timedelta(days=7),max_cost=2)
    with pytest.raises(sc.UncertainOutcome):
        a.get(next_week,cutoff=NOW,max_cost=2,retry=True)
    assert len(fake.requests)==2
    assert a.store.usage('oct','morning')['host_reserved']==3
    a.store.save(next_week,{'results':[{'symbol':'BBCA','market_cap':110}]},available_at=NOW+timedelta(days=7),provenance='provider-https')
    with pytest.raises(sc.CacheMiss):
        a.get(next_week,cutoff=NOW,max_cost=1)
    assert a.get(first,cutoff=NOW+timedelta(days=7),max_cost=1).payload['results'][0]['market_cap']==100
    assert a.get(next_week,cutoff=NOW+timedelta(days=7),max_cost=1).payload['results'][0]['market_cap']==110
    assert a.store.usage('oct','morning')['host_reserved']==3


def test_uncapped_calls_need_no_cap_or_cost_and_keep_accounting(tmp_path):
    fake = Fake([page(), page(2)])
    config = sc.Config(store_path=tmp_path/'cache.sqlite3', caller='morning',
                       billing_window='oct', cache_only=False, api_key='fake-key')
    a = sc.SectorsClient(config, transport=fake, clock=lambda: NOW)
    assert a.close_session('2026-10-02', cutoff=NOW, page_limit=2).complete
    assert a.get(identity(), cutoff=NOW).payload == page()
    assert len(fake.requests) == 2
    assert a.store.usage('oct', 'morning') == {'host_reserved': 2, 'caller_reserved': 2}


def test_uncapped_configuration_does_not_inherit_old_optional_limits(tmp_path):
    fake = Fake([page(), page(2)])
    capped = client(tmp_path, fake, caller_limit=1, host_limit=1)
    capped.get(identity(), cutoff=NOW)
    uncapped = client(tmp_path, fake, caller_limit=None, host_limit=None)
    assert uncapped.get(identity(2), cutoff=NOW).payload == page(2)
    assert len(fake.requests) == 2


def test_optional_caller_limit_still_applies_without_host_limit(tmp_path):
    fake = Fake([page()])
    a = client(tmp_path, fake, caller_limit=1, host_limit=None)
    a.get(identity(), cutoff=NOW)
    with pytest.raises(sc.BudgetDenied):
        a.get(identity(2), cutoff=NOW)
    assert len(fake.requests) == 1
