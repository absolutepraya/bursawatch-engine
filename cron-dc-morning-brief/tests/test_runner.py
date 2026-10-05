from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'lib-chart-img/bin')]
from morning_brief.calendar import SessionCalendar
from morning_brief.inputs import Provenance, MembershipSnapshot, CapSnapshot, PriceSeries
from morning_brief.store import RunStore, digest
from test_publication import NOW, DEST, FakeDelivery, FakeProjection

FREEZE=NOW.replace(minute=30)

class Source:
    def __init__(self): self.captures=0
    def capture_window(self,previous,cutoff,limit=1000):
        self.captures+=1
        return {'status':'unavailable','previous_cutoff':previous,'cutoff':cutoff}
    def read_versions(self,refs): raise AssertionError('unavailable corpus cannot read')

class HeartbeatDelivery(FakeDelivery):
    def submit(self,op):
        if op.target['channel_id']=='1505162000420835388':
            self.sent.append(op)
            from bursawatch_discord_delivery import OperationReceipt
            return OperationReceipt('heartbeat',op.key,op.digest,'delivered',{'channel_id':op.target['channel_id'],'message_id':'987654321098765432'})
        return super().submit(op)

def calendar():
    days=tuple(date(2026,9,1)+timedelta(days=n) for n in range(34))+(date(2026,10,5),)
    return SessionCalendar('explicit-synthetic','amend','IDX','https://example.test/calendar','a'*64,'b'*64,
        FREEZE-timedelta(days=1),date(2026,9,1),date(2026,10,31),days)

def numerical():
    sessions=calendar().last_sessions(date(2026,10,4),18)
    series=PriceSeries('AAAA',{s.isoformat():100*(1.001+n/10000)**n for n,s in enumerate(sessions)},'split_adjusted','fixture-price-v1',True)
    proof={'kind':'caller_attestation','verified':True,'content_sha256':digest(asdict(series)),
        'available_at':(FREEZE-timedelta(hours=1)).isoformat(),'source_url':'https://example.test/closes','evidence_ref':'synthetic-eligibility-action-proof'}
    benchmark={s.isoformat():100. for s in sessions}
    benchproof={**proof,'content_sha256':digest(benchmark),'evidence_ref':'synthetic-benchmark-v1','version':'benchmark-v1'}
    p=Provenance('https://example.test/caps','c'*64,'explicit-synthetic','fixture-cap')
    return {'memberships':{kind:asdict(MembershipSnapshot('members-v1',{kind:('AAAA',)},p)) for kind in ['sectors','konglo']},
        'caps':asdict(CapSnapshot('caps-v1',FREEZE-timedelta(hours=1),None,{'AAAA':100.},p)),
        'prices':{'AAAA':asdict(series)},'price_attestations':{'AAAA':proof},'actions':[],
        'benchmark':benchmark,'benchmark_attestation':benchproof}

def test_end_to_end_preview_freezes_inputs_artifacts_and_heartbeat_without_posts(tmp_path,core):
    r=core('runner'); store=RunStore(tmp_path/'runs.sqlite'); source=Source()
    delivery=HeartbeatDelivery(); projection=FakeProjection()
    runner=r.MorningRunner(store,source,delivery,projection,clock=lambda:NOW)
    result=runner.run(calendar=calendar(),numerical=numerical(),global_inputs=[],calendar_snapshots=[],
        model=lambda _:pytest.fail('missing evidence uses facts only'),model_version='fixture-model',prompt_version='v1',
        preview=True,preview_dir=tmp_path/'preview')
    assert result['phase']=='preview' and not delivery.sent and not projection.requests
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    assert store.get_frozen(run.run_id,'upstream').payload['numerical']['benchmark_attestation']['version']=='benchmark-v1'
    assert store.get_frozen(run.run_id,'selection').payload['images'][1]['data']
    assert (tmp_path/'preview/preview.md').read_text().count('\n\n---\n\n')==5
    assert (tmp_path/'preview/heartbeat.json').exists()
    assert source.captures==1

def test_reviewed_live_injection_projects_and_restart_ignores_later_input_correction(tmp_path,core):
    r=core('runner'); store=RunStore(tmp_path/'runs.sqlite'); source=Source(); clock=[NOW]
    delivery=HeartbeatDelivery(); projection=FakeProjection()
    runner=r.MorningRunner(store,source,delivery,projection,clock=lambda:clock[0])
    args=dict(calendar=calendar(),numerical=numerical(),global_inputs=[],calendar_snapshots=[],model=None,
        model_version='fixture-model',prompt_version='v1',preview=False,destination=DEST,reviewed_config='explicit-local-fake')
    result=runner.run(**args)
    assert result['phase']=='projected'
    original=projection.requests[0]
    clock[0]+=timedelta(minutes=11)
    args['numerical']={}; args['model']=lambda _:pytest.fail('restart never rewrites')
    assert runner.run(**args)['phase']=='projected'
    assert len(projection.requests)==1 and projection.requests[0]==original
    assert source.captures==1
    assert len([op for op in delivery.sent if op.target['channel_id']==DEST])==5
    assert len([op for op in delivery.sent if op.target['channel_id']=='1505162000420835388'])==2

@pytest.mark.parametrize('mode',['no_session','no_data','fatal'])
def test_every_noop_degraded_and_fatal_attempt_has_safe_heartbeat(tmp_path,core,mode):
    r=core('runner'); store=RunStore(tmp_path/'runs.sqlite'); source=Source(); delivery=HeartbeatDelivery()
    c=calendar(); data=numerical()
    if mode=='no_session': c=SessionCalendar(**{**c.__dict__,'sessions':c.sessions[:-1]})
    if mode=='no_data': data={}
    if mode=='fatal': c=SessionCalendar(**{**c.__dict__,'amendment_checked_at':FREEZE+timedelta(seconds=1)})
    result=r.MorningRunner(store,source,delivery,FakeProjection(),clock=lambda:NOW).run(
        calendar=c,numerical=data,global_inputs=[],calendar_snapshots=[],model=None,
        model_version='fixture-model',prompt_version='v1',preview=False,destination=DEST,reviewed_config='explicit-local-fake')
    assert result['phase']=={'no_session':'no_session','no_data':'projected','fatal':'fatal'}[mode]
    beats=[op for op in delivery.sent if op.target['channel_id']=='1505162000420835388']
    assert len(beats)==1
    assert 'reserved=' in beats[0].payload['content'] or mode=='fatal'
    assert len([op for op in delivery.sent if op.target['channel_id']==DEST])==(3 if mode=='no_data' else 0)

def test_unattested_positive_prices_cannot_qualify_rotations(tmp_path,core):
    r=core('runner'); data=numerical(); data['price_attestations']={}
    store=RunStore(tmp_path/'runs.sqlite')
    result=r.MorningRunner(store,Source(),HeartbeatDelivery(),FakeProjection(),clock=lambda:NOW).run(
        calendar=calendar(),numerical=data,global_inputs=[],calendar_snapshots=[],model=None,model_version='fixture',prompt_version='v1')
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    assert result['phase']=='preview'
    inputs=store.get_frozen(run.run_id,'inputs').payload
    assert inputs['groups']=={'sectors':[],'konglo':[]}
    assert inputs['gaps']

def test_live_requires_explicit_reviewed_destination_before_any_delivery(tmp_path,core):
    delivery=HeartbeatDelivery(); r=core('runner')
    with pytest.raises(ValueError,match='reviewed'):
        r.MorningRunner(RunStore(tmp_path/'r'),Source(),delivery,FakeProjection(),clock=lambda:NOW).run(
            calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],model=None,model_version='v',prompt_version='v',preview=False)
    assert not delivery.sent

def test_completed_attempt_releases_fenced_lease_for_immediate_recovery(tmp_path,core):
    r=core('runner'); store=RunStore(tmp_path/'runs'); delivery=HeartbeatDelivery(); projection=FakeProjection()
    runner=r.MorningRunner(store,Source(),delivery,projection,clock=lambda:NOW)
    args=dict(calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],model=None,
        model_version='v',prompt_version='v',preview=False,destination=DEST,reviewed_config='local-fake')
    assert runner.run(**args)['phase']=='projected'
    assert runner.run(**args)['phase']=='projected'
    assert len(projection.requests)==1
