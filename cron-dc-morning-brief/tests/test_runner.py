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

FREEZE=NOW.replace(hour=7,minute=30)

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
    actionsproof={**proof,'content_sha256':digest([]),'evidence_ref':'synthetic-verified-empty-actions'}
    p=Provenance('https://example.test/caps','c'*64,'explicit-synthetic','fixture-cap')
    return {'memberships':{kind:asdict(MembershipSnapshot('members-v1',{kind:('AAAA',)},p)) for kind in ['sectors','konglo']},
        'caps':asdict(CapSnapshot('caps-v1',FREEZE-timedelta(hours=1),None,{'AAAA':100.},p)),
        'prices':{'AAAA':asdict(series)},'price_attestations':{'AAAA':proof},'actions':[],
        'actions_attestation':actionsproof,
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

def test_basket_cap_fallback_preserves_age_and_omits_only_unsupported_baskets(tmp_path,core):
    r=core('runner');store=RunStore(tmp_path/'runs.sqlite');data=numerical()
    current=data.pop('caps')
    prior={**current,'identity':'previous-week','collected_at':FREEZE-timedelta(days=4)}
    expired={**current,'identity':'expired','collected_at':FREEZE-timedelta(days=15)}
    data['memberships']['sectors']['groups']={name:('AAAA',) for name in ('Current','Previous','Expired','Missing')}
    data['caps_by_basket']={'sectors':{'Current':current,'Previous':prior,'Expired':expired},
                            'konglo':{'konglo':current}}
    runner=r.MorningRunner(store,Source(),HeartbeatDelivery(),FakeProjection(),clock=lambda:NOW)
    result=runner.run(calendar=calendar(),numerical=data,global_inputs=[],calendar_snapshots=[],
        model=None,model_version='fixture',prompt_version='v1',preview=True)
    assert result['phase']=='preview'
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    actual=store.get_frozen(run.run_id,'inputs').payload
    groups={row['name']:row for row in actual['groups']['sectors']}
    assert set(groups)=={'Current','Previous'}
    assert groups['Previous']['provenance']['cap_collection_status']=='extra_week'
    assert groups['Previous']['provenance']['cap_snapshot']=='previous-week'
    assert 'sectors:unsupported:Expired' in actual['gaps'] and 'sectors:unsupported:Missing' in actual['gaps']

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

def test_direct_live_preparation_and_recovery_wait_until_default_target(tmp_path,core):
    clock=[NOW-timedelta(minutes=4)]
    delivery=HeartbeatDelivery(); projection=FakeProjection(); source=Source()
    runner=core('runner').MorningRunner(RunStore(tmp_path/'runs'),source,delivery,projection,clock=lambda:clock[0])
    args=dict(calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],model=None,
        model_version='v',prompt_version='v',preview=False,destination=DEST,reviewed_config='reviewed-injection')
    assert runner.run(**args)['phase']=='prepared'
    assert runner.run(**args)['phase']=='prepared'
    assert not [op for op in delivery.sent if op.target['channel_id']==DEST]
    assert not projection.requests and source.captures==1
    clock[0]=NOW
    assert runner.run(**args)['phase']=='projected'
    assert len([op for op in delivery.sent if op.target['channel_id']==DEST])==3
    assert len(projection.requests)==1 and source.captures==1

@pytest.mark.parametrize('accepted,after_wait',[
    ('pending','delivered'),('pending_reconciliation','pending_reconciliation'),
    ('retrying','retrying'),('delivering','delivered'),('delivered',None),('failed',None),
])
def test_heartbeat_waits_on_same_operation_only_for_nonterminal_receipts(tmp_path,core,accepted,after_wait):
    from dataclasses import replace
    from bursawatch_discord_delivery import DELIVERY_RECEIPT_WAIT_SECONDS
    class Delivery(FakeDelivery):
        def wait(self,key,timeout_seconds):
            self.waits.append((key,timeout_seconds))
            receipt=self.status(key)
            return replace(receipt,status=after_wait)
    delivery=Delivery(); delivery.statuses[1]=accepted
    runner=core('runner').MorningRunner(RunStore(tmp_path/'runs'),Source(),delivery,FakeProjection(),clock=lambda:NOW)
    result=runner._heartbeat({'phase':'prepared'},preview=False,preview_dir=None,accounting={})
    assert len(delivery.sent)==1
    assert delivery.waits==([(delivery.sent[0].key,DELIVERY_RECEIPT_WAIT_SECONDS)] if after_wait else [])
    assert result['heartbeat']['status']==(after_wait or accepted)


@pytest.mark.parametrize('manifest',['empty','raw_split'])
@pytest.mark.parametrize('proof_state',['valid','missing','unverified','late','changed','absent_manifest'])
def test_action_manifest_requires_exact_cutoff_attestation(tmp_path,core,manifest,proof_state):
    r=core('runner'); data=numerical()
    if manifest=='raw_split':
        row=data['prices']['AAAA']; effective=sorted(row['closes'])[-4]
        row['basis']='raw'
        row['closes']={day:value*2 if day<effective else value for day,value in row['closes'].items()}
        data['price_attestations']['AAAA']['content_sha256']=digest(row)
        data['actions']=[dict(symbol='AAAA',identity='synthetic-split',status='resolved',
            treatment='adjust_raw',ratio=2,evidence='synthetic-action-source',effective_session=effective)]
        data['actions_attestation']['content_sha256']=digest(data['actions'])
    if proof_state=='missing': data.pop('actions_attestation')
    elif proof_state=='unverified': data['actions_attestation']['verified']=False
    elif proof_state=='late': data['actions_attestation']['available_at']=(FREEZE+timedelta(seconds=1)).isoformat()
    elif proof_state=='changed':
        if manifest=='raw_split': data['actions'][0]['ratio']=3
        else: data['actions_attestation']['content_sha256']='a'*64
    elif proof_state=='absent_manifest': data.pop('actions')
    store=RunStore(tmp_path/'runs.sqlite')
    result=r.MorningRunner(store,Source(),HeartbeatDelivery(),FakeProjection(),clock=lambda:NOW).run(
        calendar=calendar(),numerical=data,global_inputs=[],calendar_snapshots=[],model=None,
        model_version='fixture',prompt_version='v1')
    assert result['phase']=='preview'
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    inputs=store.get_frozen(run.run_id,'inputs').payload
    selected=store.get_frozen(run.run_id,'selection').payload
    if proof_state=='valid':
        assert all(inputs['groups'][kind] for kind in ('sectors','konglo'))
        assert selected['images'][1] is not None and selected['images'][2] is not None
        assert store.get_frozen(run.run_id,'upstream').payload['numerical']['actions_attestation']==data['actions_attestation']
    else:
        assert inputs['groups']=={'sectors':[],'konglo':[]}
        assert 'actions_attestation_unavailable' in inputs['gaps']
        assert selected['images'][1:] == [None,None]


@pytest.mark.parametrize('minutes,returned_minutes',[(0,0),(15,15),(-15,-15),(0,15)])
def test_chart_request_requires_exact_frozen_cutoff(tmp_path,core,minutes,returned_minutes):
    from datetime import timezone
    from io import BytesIO
    from PIL import Image
    from chart_img_client.models import RenderRequest, AsOfVerification, validate_image
    def request(offset):
        return RenderRequest('synthetic','synthetic','IDX:COMPOSITE','1D','3M',
            (FREEZE+timedelta(minutes=offset)).astimezone(timezone.utc),width=800,height=600)
    supplied=request(minutes); returned=request(returned_minutes)
    stream=BytesIO(); Image.new('RGB',(800,600),'white').save(stream,format='PNG')
    artifact=validate_image(stream.getvalue(),'image/png',returned,returned.cutoff)
    previous=calendar().last_sessions(NOW.date(),2)[0].isoformat()
    artifact=artifact.with_verification(AsOfVerification(artifact.sha256,returned.identity,
        previous,returned.cutoff,'synthetic','synthetic-only','3M'))
    class Chart:
        calls=0
        def render(self,actual,*,cache_only):
            assert actual==supplied and cache_only is True
            self.calls+=1
            return artifact
    chart=Chart(); delivery=HeartbeatDelivery(); store=RunStore(tmp_path/'runs.sqlite')
    result=core('runner').MorningRunner(store,Source(),delivery,FakeProjection(),clock=lambda:NOW).run(
        calendar=calendar(),numerical=numerical(),global_inputs=[],calendar_snapshots=[],model=None,
        model_version='fixture',prompt_version='v1',chart_client=chart,chart_request=supplied,
        preview=False,destination=DEST,reviewed_config='local-fake-only')
    assert result['phase']=='projected'
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    selected=store.get_frozen(run.run_id,'selection').payload
    ihsg_posts=[op for op in delivery.sent if op.key.endswith(':ihsg_image')]
    if minutes==0 and returned_minutes==0:
        assert chart.calls==1 and len(ihsg_posts)==1
        manifest=selected['images'][0]['manifest']
        assert datetime.fromisoformat(manifest['request_cutoff'])==FREEZE
        assert manifest['request_identity']==supplied.identity
    else:
        assert chart.calls==(1 if minutes==0 else 0)
        assert selected['images'][0] is None
        assert selected['omissions'][0]=='ihsg_image_unavailable'
        assert not ihsg_posts


@pytest.mark.parametrize('first_preview', [True,False])
def test_preview_and_live_cannot_reuse_each_others_frozen_state(tmp_path,core,first_preview):
    import json
    r=core('runner'); store=RunStore(tmp_path/'runs'); delivery=HeartbeatDelivery(); source=Source()
    runner=r.MorningRunner(store,source,delivery,FakeProjection(),clock=lambda:NOW)
    args=dict(calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],model=None,
        model_version='v',prompt_version='v',destination=DEST,reviewed_config='local-fake',preview_dir=tmp_path/'preview')
    assert runner.run(**args,preview=first_preview)['phase']==('preview' if first_preview else 'projected')
    before=[op.digest for op in delivery.sent if op.target['channel_id']==DEST]
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    assert store.get_frozen(run.run_id,'run_mode').payload['mode']==('preview' if first_preview else 'live')
    original=store.get_frozen(run.run_id,'selection').digest
    result=runner.run(**args,preview=not first_preview)
    assert result['phase']=='fatal' and result['reason']=='FreezeConflict'
    assert [op.digest for op in delivery.sent if op.target['channel_id']==DEST]==before
    assert source.captures==1 and store.get_frozen(run.run_id,'selection').digest==original
    if first_preview:
        provenance=json.loads((tmp_path/'preview/selection.json').read_text())
        assert provenance['mode']=='preview' and 'synthetic_or_attested' not in provenance


@pytest.mark.parametrize('overlong',[False,True])
def test_generated_core_and_anchor_match_published_presentation_after_capture_grace(tmp_path,core,overlong):
    from datetime import timezone
    from test_evidence import source, manifest, checksum
    from test_outlook import structured_response
    r=core('runner');store=RunStore(tmp_path/'runs');delivery=HeartbeatDelivery()
    current=FREEZE+timedelta(seconds=4.2)
    class AvailableSource:
        def capture_window(self,previous,cutoff,limit=1000):
            self.rows=[source(1,text='Jika likuiditas pulih, IHSG bergerak terbatas. Jika tekanan bertambah, pandangan ini berubah.',
                accepted_at=cutoff,published_at=previous,observed_at=cutoff)]
            if overlong:
                self.rows=[source(1,text=self.rows[0]['text'],accepted_at=cutoff,published_at=previous,observed_at=cutoff,
                    source_url='https://example.com/'+('x'*1950))]
            captured=manifest(self.rows,previous_cutoff=previous,cutoff=cutoff,
                captured_at=current.astimezone(timezone.utc).isoformat(),capture_gap_seconds=4.2)
            return captured
        def read_versions(self,refs): return self.rows
    runner=r.MorningRunner(store,AvailableSource(),delivery,FakeProjection(),clock=lambda:current)
    from test_economic_calendar import saved, page
    calendars=core('economic_calendar')
    snapshot=saved(calendars,calendars.SnapshotCache(tmp_path/'calendars'),page([['2026-10-06','Inflasi','September 2026','','release-1',1,'nasional']]))
    result=runner.run(calendar=calendar(),numerical=numerical(),global_inputs=[],calendar_snapshots=[snapshot],
        model=structured_response,model_version='scenario-fixture',prompt_version='source-scenario-v2',
        preview=False,destination=DEST,reviewed_config='local-fake')
    assert result['phase']=='prepared'
    assert not runner.projection.requests
    current=NOW
    assert runner.run(calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],
        model=lambda _:pytest.fail('delivery reran writer'),model_version='changed',prompt_version='changed',
        preview=False,destination=DEST,reviewed_config='local-fake')['phase']=='projected'
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    anchor=runner.publisher.morning_anchor(run.run_id)
    assert anchor['text']==[op for op in delivery.sent if op.key.endswith(':ihsg_text')][0].payload['content']
    assert store.get_frozen(run.run_id,'evidence').payload['capture_gap_seconds']==4.2
    assert store.get_frozen(run.run_id,'outlook').payload['mode']=='supported'
    if overlong:
        assert result['fallback']=='facts_only' and anchor['scenario']['mode']=='facts_only'
        assert anchor['scenario']['scenario'] is None and 'bukti belum cukup' in anchor['text']
        assert 'Jika likuiditas' not in anchor['text']
    else:
        assert result['fallback']=='supported' and anchor['scenario']['scenario']['base_case']['excerpt'].startswith('Jika likuiditas')
        assert '**Skenario IHSG**' in anchor['text'] and '**Pandangan satu sumber**' in anchor['text']
    frozen_anchor=anchor
    assert runner.run(calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],
        model=lambda _:pytest.fail('recovery reran writer'),model_version='changed',prompt_version='changed',
        preview=False,destination=DEST,reviewed_config='local-fake')['phase']=='projected'
    assert runner.publisher.morning_anchor(run.run_id)==frozen_anchor


def test_unknown_legacy_mode_cannot_be_relabelled_as_live(tmp_path,core):
    store=RunStore(tmp_path/'legacy');run=store.create_run('2026-10-05',freeze_at=FREEZE)
    lease=store.acquire_lease(run.run_id,'legacy',now=NOW,seconds=600)
    original=store.freeze(run.run_id,'upstream',{'legacy':'unclassified'},lease=lease,now=NOW)
    store.release_lease(lease,now=NOW)
    delivery=HeartbeatDelivery();source=Source()
    result=core('runner').MorningRunner(store,source,delivery,FakeProjection(),clock=lambda:NOW).run(
        calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],model=None,
        model_version='v',prompt_version='v',preview=False,destination=DEST,reviewed_config='local-fake')
    assert result['phase']=='fatal' and result['reason']=='FreezeConflict'
    assert store.get_frozen(run.run_id,'upstream').digest==original.digest
    assert store.get_frozen(run.run_id,'run_mode') is None and source.captures==0
    assert not [op for op in delivery.sent if op.target['channel_id']==DEST]
