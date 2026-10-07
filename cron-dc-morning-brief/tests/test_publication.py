from dataclasses import asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import hashlib
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'lib-bursawatch-discord-delivery/bin'), str(ROOT/'lib-bursawatch-control/bin'),
               str(ROOT/'service-bursawatch-control/bin')]
from bursawatch_discord_delivery import OperationReceipt, DeliveryClientError
from morning_brief.store import RunStore, FreezeConflict
from morning_brief.rendering import RenderedArtifact

NOW = datetime(2026,10,5,8,0,tzinfo=ZoneInfo('Asia/Jakarta'))
DEST = '123456789012345678'

class FakeDelivery:
    def __init__(self):
        self.operations = {}; self.sent = []; self.loss = False; self.statuses = {}; self.waits = []
    def submit(self, operation):
        if operation.key in self.operations:
            old = self.operations[operation.key]
            if old.digest != operation.digest: raise DeliveryClientError('conflict')
            return old
        self.sent.append(operation)
        result = OperationReceipt('op-'+str(len(self.sent)),operation.key,operation.digest,
            self.statuses.get(len(self.sent),'delivered'),{'channel_id':DEST,'message_id':str(987654321098765430+len(self.sent))})
        if result.status != 'delivered': result = OperationReceipt(result.id,result.key,result.digest,result.status,None)
        self.operations[operation.key] = result
        if self.loss:
            self.loss = False
            raise DeliveryClientError('network_error')
        return result
    def status(self, key): return self.operations.get(key)
    def wait(self,key,timeout_seconds): self.waits.append(timeout_seconds); return self.status(key)

class FakeProjection:
    def __init__(self): self.requests=[]; self.down=False
    def submit(self,payload):
        self.requests.append(payload)
        if self.down: raise OSError('local fake outage')
        from control_plane.publication_model import validate_publication
        accepted=validate_publication(payload,'bursawatch-dc-morning-brief')
        return {key:accepted[key] for key in ('publication_id','version','digest')}

@pytest.fixture
def owner(tmp_path,core):
    p=core('publication'); store=RunStore(tmp_path/'runs.sqlite')
    run=store.create_run('2026-10-05',freeze_at=NOW.replace(hour=7,minute=30))
    lease=store.acquire_lease(run.run_id,'test',now=NOW,seconds=3600)
    delivery=FakeDelivery(); projection=FakeProjection()
    pub=p.Publisher(store,delivery,projection,clock=lambda:NOW)
    return pub,store,run,lease,delivery,projection

def freeze(owner, images=None):
    pub,store,run,lease,delivery,projection=owner
    for slot in ['inputs','outlook','globals','calendar_events']:
        store.freeze(run.run_id,slot,{'fixture':'controlled'},lease=lease,now=NOW)
    if images is None:
        raw=b'controlled-frozen-PNG-bytes'
        artifact=RenderedArtifact(raw,'image/png',hashlib.sha256(raw).hexdigest(),1000,500,{'fixture':True})
        images=(artifact,artifact,artifact)
    return pub.freeze(run.run_id,texts=('original IHSG','original sectors','original konglo'),images=images,
        omissions=tuple('unsupported_image' if image is None else None for image in images),destination=DEST,lease=lease)

def test_freezes_six_steps_bytes_and_deadlines_before_any_submission(owner):
    manifest=freeze(owner); pub,store,run,lease,delivery,projection=owner
    assert len(manifest.payload['steps'])==6
    assert not delivery.sent
    assert [s['name'] for s in manifest.payload['steps']]==['ihsg_text','ihsg_image','sectors_text','sectors_image','konglo_text','konglo_image']
    assert all(s['attempt_deadline']=='2026-10-05T01:15:00.000000Z' for s in manifest.payload['steps'])
    assert pub.publish(run.run_id,lease=lease)['phase']=='projected'
    assert len(delivery.sent)==6
    assert delivery.sent[1].attachments[0].data==b'controlled-frozen-PNG-bytes'
    assert projection.requests[0]['legs'][0]['text']=='original IHSG'

def test_response_loss_and_restart_never_duplicate_accepted_operation(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    delivery.loss=True
    assert pub.publish(run.run_id,lease=lease)['phase']=='unresolved'
    restarted=type(pub)(RunStore(store.path),delivery,projection,clock=lambda:NOW)
    assert restarted.publish(run.run_id,lease=lease)['phase']=='projected'
    assert len(delivery.sent)==6

def test_direct_publisher_waits_until_default_target_without_operator_config(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    pub.clock=lambda:NOW-timedelta(seconds=1)
    assert pub.publish(run.run_id,lease=lease)['phase']=='prepared'
    assert not delivery.sent and not projection.requests
    pub.clock=lambda:NOW
    assert pub.publish(run.run_id,lease=lease)['phase']=='projected'
    assert len(delivery.sent)==6 and len(projection.requests)==1

def test_projection_outage_retries_projection_alone_and_keeps_original(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    projection.down=True
    assert pub.publish(run.run_id,lease=lease)['phase']=='projection_pending'
    projection.down=False
    assert pub.publish(run.run_id,lease=lease)['phase']=='projected'
    assert len(delivery.sent)==6
    assert projection.requests[0]==projection.requests[1]
    assert pub.morning_anchor(run.run_id)['text']=='original IHSG'
    assert pub.publish(run.run_id,lease=lease)['phase']=='projected'
    assert len(projection.requests)==2

@pytest.mark.parametrize('status',['rejected','pending','ambiguous','blocked'])
def test_text_without_matching_confirmation_cannot_release_image(owner,status):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    delivery.statuses[1]=status
    assert pub.publish(run.run_id,lease=lease)['phase']=='unresolved'
    assert len(delivery.sent)==1 and not projection.requests
    if status=='pending': assert delivery.waits==[10]

def test_omitted_image_is_explicit_and_only_available_operations_project(owner):
    manifest=freeze(owner,images=(None,None,None))
    pub,store,run,lease,delivery,projection=owner
    assert manifest.payload['steps'][1]['omission']=='unsupported_image'
    assert pub.publish(run.run_id,lease=lease)['phase']=='projected'
    assert len(delivery.sent)==3
    assert len(projection.requests[0]['required_operation_keys'])==3

def test_pending_image_stays_unresolved_and_is_never_omitted(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    delivery.statuses[2]='pending'
    assert pub.publish(run.run_id,lease=lease)['phase']=='unresolved'
    assert len(delivery.sent)==2
    assert store.get_frozen(run.run_id,'publication').payload['steps'][1]['omission'] is None

def test_expired_missing_operation_never_sends_and_accepted_earlier_can_reconcile(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    delivery.loss=True; pub.publish(run.run_id,lease=lease)
    pub.clock=lambda:NOW.replace(hour=8,minute=16)
    assert pub.publish(run.run_id,lease=lease)['phase']=='unresolved'
    assert len(delivery.sent)==1 and not projection.requests
    assert store.get_receipts(run.run_id,'operation:ihsg_text')[-1]['status']=='delivered'

def test_digest_conflict_receipt_and_wrong_destination_fail_closed(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    first=store.get_frozen(run.run_id,'operation:ihsg_text').payload
    delivery.operations[first['operation_key']]=OperationReceipt('x',first['operation_key'],'b'*64,'delivered',{'channel_id':DEST,'message_id':'987654321098765432'})
    with pytest.raises(FreezeConflict,match='receipt'): pub.publish(run.run_id,lease=lease)
    delivery.operations[first['operation_key']]=OperationReceipt('x',first['operation_key'],first['digest'],'delivered',{'channel_id':'123456789012345679','message_id':'987654321098765432'})
    with pytest.raises(FreezeConflict,match='receipt'): pub.publish(run.run_id,lease=lease)
    assert not delivery.sent and not projection.requests

def test_changed_selected_text_cannot_replace_frozen_payload(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    with pytest.raises(FreezeConflict):
        pub.freeze(run.run_id,texts=('changed','original sectors','original konglo'),images=(None,None,None),
            omissions=('unavailable',)*3,destination=DEST,lease=lease)
    assert not delivery.sent

def test_crash_before_receipt_persistence_recovers_accepted_id_without_new_send(owner,monkeypatch):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    original=store.append_receipt
    class Crash(BaseException): pass
    def crash(*args,**kwargs): raise Crash()
    monkeypatch.setattr(store,'append_receipt',crash)
    with pytest.raises(Crash): pub.publish(run.run_id,lease=lease)
    assert len(delivery.sent)==1 and not store.get_receipts(run.run_id,'operation:ihsg_text')
    monkeypatch.setattr(store,'append_receipt',original)
    assert pub.publish(run.run_id,lease=lease)['phase']=='projected'
    assert len(delivery.sent)==6

def test_operation_id_cannot_change_during_reconciliation(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    delivery.statuses[1]='pending'; pub.publish(run.run_id,lease=lease)
    key=delivery.sent[0].key; row=delivery.operations[key]
    delivery.operations[key]=OperationReceipt('different-id',key,row.digest,'delivered',{'channel_id':DEST,'message_id':'987654321098765432'})
    with pytest.raises(FreezeConflict,match='receipt'): pub.publish(run.run_id,lease=lease)
    assert len(delivery.sent)==1

@pytest.mark.parametrize('change',['missing','corrupt'])
def test_missing_corrupt_frozen_bytes_never_submit_image(owner,monkeypatch,change):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    original=store.get_frozen
    from dataclasses import replace
    def broken(run_id,slot):
        record=original(run_id,slot)
        if slot=='operation:ihsg_image':
            payload=dict(record.payload); media=dict(payload['media'])
            if change=='missing': media.pop('data')
            else: media['data']='Y29ycnVwdA=='
            payload['media']=media; return replace(record,payload=payload)
        return record
    monkeypatch.setattr(store,'get_frozen',broken)
    with pytest.raises(FreezeConflict,match='bytes'): pub.publish(run.run_id,lease=lease)
    assert len(delivery.sent)==1 and not projection.requests

def test_send_started_before_expiry_may_confirm_after_it(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    original=delivery.submit
    def crossing(op):
        result=original(op)
        pub.clock=lambda:NOW.replace(hour=8,minute=16)
        return result
    delivery.submit=crossing
    assert pub.publish(run.run_id,lease=lease)['phase']=='unresolved'
    assert store.get_receipts(run.run_id,'operation:ihsg_text')[-1]['status']=='delivered'
    assert len(delivery.sent)==1

def test_uncertain_status_after_expiry_never_becomes_omission_or_new_create(owner):
    freeze(owner); pub,store,run,lease,delivery,projection=owner
    delivery.statuses[1]='ambiguous'; pub.publish(run.run_id,lease=lease)
    pub.clock=lambda:NOW.replace(hour=8,minute=16)
    result=pub.publish(run.run_id,lease=lease)
    assert result['reason']=='receipt_ambiguous' and result['lateness_seconds']==960
    assert len(delivery.sent)==1


def test_attachment_only_messages_project_without_caption_and_recover_exact_bytes(owner):
    manifest=freeze(owner);pub,store,run,lease,delivery,projection=owner
    for step in manifest.payload['steps']:
        if step['name'].endswith('_image'):
            op=store.get_frozen(run.run_id,step['slot']).payload
            assert op['payload']['content']=='' and op['media'] is not None
    assert pub.publish(run.run_id,lease=lease)['phase']=='projected'
    image_legs=[leg for leg in projection.requests[0]['legs'] if leg['attachments']]
    assert len(image_legs)==3 and all(leg['text'] is None for leg in image_legs)
    assert all(op.payload['content']=='' for op in delivery.sent if op.attachments)
