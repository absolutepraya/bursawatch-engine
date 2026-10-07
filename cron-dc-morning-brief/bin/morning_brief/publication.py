"""Frozen six-step output, matching receipt gates and projection-only recovery."""
import base64
from dataclasses import asdict
from datetime import datetime, time
import hashlib
import re
from zoneinfo import ZoneInfo
from bursawatch_discord_delivery import (
    Attachment, OperationIntent, OperationReceipt, DELIVERY_RECEIPT_WAIT_SECONDS,
)
from bursawatch_discord_delivery.client import NON_TERMINAL_STATUSES
from bursawatch_discord_delivery.models import validate_receipt, parse_attempt_deadline
from .formatting import attachment_caption
from .config import retained_operator_config, timing_for
from .store import FreezeConflict, canonical, stamp

OWNER = 'bursawatch-dc-morning-brief'
KINDS = ('ihsg', 'sectors', 'konglo')


class Publisher:
    """Injected shared clients only. Acceptance uncertainty preserves the original intent.

    Attachment bytes live in immutable private RunStore slots. They are never
    regenerated, removed on acceptance or replaced by a service staging ref.
    """
    def __init__(self, store, delivery, projection, *, clock):
        self.store, self.delivery, self.projection, self.clock = store, delivery, projection, clock

    def freeze(self, run_id, *, texts, images, omissions, destination, lease):
        run = self.store.get_run(run_id)
        if len(texts) != 3 or len(images) != 3 or len(omissions) != 3:
            raise ValueError('three text/image selections required')
        if not isinstance(destination, str) or re.fullmatch(r'[0-9]{17,20}',destination) is None:
            raise ValueError('reviewed brief destination required')
        session = datetime.fromisoformat(run.session).date()
        times = timing_for(session, retained_operator_config(self.store,run_id))
        deadline = times['deadline']
        configuration=self.store.get_frozen(run_id,'operator_config')
        dependencies = {'operator_config':configuration.digest} if configuration else {}
        for slot in ('inputs','outlook','globals','calendar_events'):
            record = self.store.get_frozen(run_id,slot)
            if record is None: raise ValueError('selected inputs must freeze before publication')
            dependencies[slot] = record.digest
        steps = []
        # All six selections, bytes and digests precede any submit.
        for index, kind in enumerate(KINDS):
            for form in ('text','image'):
                name = kind+'_'+form
                image = images[index] if form == 'image' else None
                omission = omissions[index] if form == 'image' else None
                if form == 'image' and ((image is None) != bool(omission)):
                    raise ValueError('missing image needs a pre-submission omission')
                if omission is not None and (not isinstance(omission,str) or re.fullmatch(r'[a-z0-9_]{1,80}',omission) is None):
                    raise ValueError('bounded safe image omission required')
                attachments = ()
                media = None
                if image is not None:
                    if hashlib.sha256(image.data).hexdigest() != image.sha256:
                        raise ValueError('selected image digest mismatch')
                    media = dict(data=base64.b64encode(image.data).decode('ascii'),sha256=image.sha256,
                                 filename=kind+'.png',mime_type=image.content_type,manifest=image.manifest)
                    attachments = (Attachment(media['filename'],media['mime_type'],image.data),)
                content = texts[index] if form == 'text' else '' if image is not None else '-'
                operation = OperationIntent(key=f'{OWNER}:{run.session}:{name}',kind='channel_message_create',
                    ordering_key=f'{OWNER}:{run.session}',target={'channel_id':destination},
                    payload={'content':content,'allowed_mentions':{'parse':[]}},attachments=attachments,
                    attempt_deadline=deadline)
                selected = dict(name=name,operation_key=operation.key,digest=operation.digest,
                    attempt_deadline=operation.as_dict()['attempt_deadline'],target=dict(operation.target),
                    payload=dict(operation.payload),ordering_key=operation.ordering_key,media=media,
                    omission=omission,anchor=kind+'_text' if form=='image' else None)
                frozen = self.store.freeze(run_id,'operation:'+name,selected,lease=lease,now=self.clock(),dependencies=dependencies)
                steps.append(dict(name=name,slot=frozen.slot,digest=frozen.digest,omission=omission,
                                  attempt_deadline=selected['attempt_deadline']))
        return self.store.freeze(run_id,'publication',{'steps':steps,'destination':destination,
            'session':run.session,'owner_key':f'morning:{run.session}','version':1},
            lease=lease,now=self.clock(),dependencies={step['slot']:step['digest'] for step in steps})

    @staticmethod
    def _intent(step):
        attachments = ()
        if step['media'] is not None:
            media = step['media']
            try: raw = base64.b64decode(media['data'],validate=True)
            except (ValueError,KeyError,TypeError): raise FreezeConflict('frozen attachment bytes corrupt') from None
            if hashlib.sha256(raw).hexdigest() != media['sha256']:
                raise FreezeConflict('frozen attachment bytes corrupt')
            attachments = (Attachment(media['filename'],media['mime_type'],raw),)
        operation = OperationIntent(key=step['operation_key'],kind='channel_message_create',
            ordering_key=step['ordering_key'],target=step['target'],payload=step['payload'],
            attachments=attachments,attempt_deadline=parse_attempt_deadline(step['attempt_deadline']))
        if operation.digest != step['digest']: raise FreezeConflict('frozen operation payload conflict')
        return operation

    def _observe(self,run_id,slot,step,result,lease):
        try:
            result = OperationReceipt.from_json(asdict(result))
            if result.key != step['operation_key'] or result.digest != step['digest']:
                raise ValueError('receipt identity mismatch')
            previous = self.store.get_receipts(run_id,slot)
            if any(row['id'] != result.id for row in previous):
                raise ValueError('receipt operation id changed')
            if result.status == 'delivered':
                if result.receipt is None or result.receipt.get('channel_id') != step['target']['channel_id']:
                    raise ValueError('receipt destination mismatch')
                validate_receipt(result.receipt,'channel_message_create',step['target'])
                if any(row['status']=='delivered' and row['receipt']!=result.receipt for row in previous):
                    raise ValueError('receipt message changed')
        except (ValueError,TypeError): raise FreezeConflict('receipt does not match frozen operation') from None
        self.store.append_receipt(run_id,slot,operation_key=result.key,payload_digest=result.digest,
                                  receipt=asdict(result),lease=lease,now=self.clock())
        return result

    def _summary(self,run_id,phase,lease,*,reason=None,omissions=0):
        now=self.clock(); run=self.store.get_run(run_id)
        target=timing_for(datetime.fromisoformat(run.session).date(),retained_operator_config(self.store,run_id))['target']
        result=dict(phase=phase,reason=reason,image_omissions=omissions,
                    lateness_seconds=max(0,int((now-target).total_seconds())),observed_at=stamp(now))
        self.store.set_checkpoint(run_id,'publication_summary',canonical(result),lease=lease,now=now)
        self.store.transition(run_id,phase,lease=lease,now=now)
        return result

    def publish(self,run_id,*,lease):
        frozen=self.store.get_frozen(run_id,'publication')
        if frozen is None: raise ValueError('publication selection not frozen')
        run=self.store.get_run(run_id)
        if self.clock()<timing_for(datetime.fromisoformat(run.session).date(),retained_operator_config(self.store,run_id))['target']:
            return self._summary(run_id,'prepared',lease)
        manifest=frozen.payload; omissions=sum(bool(s['omission']) for s in manifest['steps'])
        if self.store.get_checkpoint(run_id,'projection_ack') is not None:
            return self._summary(run_id,'projected',lease,omissions=omissions)
        legs=[]
        for entry in manifest['steps']:
            saved=self.store.get_frozen(run_id,entry['slot'])
            if saved is None or saved.digest != entry['digest']:
                raise FreezeConflict('publication step manifest mismatch')
            step=saved.payload
            if step['omission'] is not None: continue
            previous=self.store.get_receipts(run_id,entry['slot'])
            result=next((OperationReceipt.from_json(row) for row in reversed(previous) if row['status']=='delivered'),None)
            if result is None:
                # Read acceptance before needing retained bytes. Response loss never
                # authorizes a replacement key, nor a send after the deadline.
                try:
                    result=self.delivery.status(step['operation_key'])
                    if result is None:
                        if self.clock() >= parse_attempt_deadline(step['attempt_deadline']):
                            return self._summary(run_id,'unresolved',lease,reason='attempt_expired',omissions=omissions)
                        operation=self._intent(step)
                        self.store.set_checkpoint(run_id,'submitted:'+step['name'],stamp(self.clock()),lease=lease,now=self.clock())
                        result=self.delivery.submit(operation)
                except FreezeConflict: raise
                except Exception:
                    return self._summary(run_id,'unresolved',lease,reason='delivery_unavailable',omissions=omissions)
                result=self._observe(run_id,entry['slot'],step,result,lease)
                if result.status in NON_TERMINAL_STATUSES:
                    try: updated=self.delivery.wait(step['operation_key'],DELIVERY_RECEIPT_WAIT_SECONDS)
                    except Exception:
                        return self._summary(run_id,'unresolved',lease,reason='receipt_unavailable',omissions=omissions)
                    result=self._observe(run_id,entry['slot'],step,updated,lease)
            else:
                result=self._observe(run_id,entry['slot'],step,result,lease)
            if result.status != 'delivered':
                return self._summary(run_id,'unresolved',lease,reason='receipt_'+result.status,omissions=omissions)
            media=step['media']
            legs.append(dict(operation_key=result.key,operation_digest=result.digest,receipt_operation_id=result.id,
                destination=step['target']['channel_id'],receipt_id=result.receipt['message_id'],status='delivered',
                message_url=None,text=step['payload']['content'] or None,attachments=[] if media is None else [
                    dict(filename=media['filename'],content_type=media['mime_type'],discord_url=None)]))
        selected=self.store.get_frozen(run_id,'projection')
        if selected is None:
            run=self.store.get_run(run_id)
            configuration=self.store.get_frozen(run_id,'operator_config')
            payload=dict(api_version=1,owner_key=manifest['owner_key'],version=1,supersedes_version=None,
                type='morning_brief',route='morning_brief',source_event_key=None,source_name='Bursawatch morning brief',
                source_url=None,source_published_at=None,market_data_as_of=run.freeze_at,delivery_confirmed_at=stamp(self.clock()),
                title='Morning brief '+run.session,ticker=None,broker_levels=None,parent_publication_id=None,
                board_episode_id=None,config_revision=configuration.payload['revision'] if configuration else None,renderer_version='morning-v1',source_version=frozen.digest,
                required_operation_keys=[leg['operation_key'] for leg in legs],legs=legs)
            selected=self.store.freeze(run_id,'projection',payload,lease=lease,now=self.clock(),dependencies={'publication':frozen.digest})
        try:
            ack=self.projection.submit(selected.payload)
            identity=hashlib.sha256(canonical([OWNER,manifest['owner_key']]).encode()).hexdigest()
            if (not isinstance(ack,dict) or ack.get('publication_id')!=identity or ack.get('version')!=1
                    or not isinstance(ack.get('digest'),str) or re.fullmatch('[a-f0-9]{64}',ack['digest']) is None):
                raise ValueError('projection ack mismatch')
        except Exception:
            return self._summary(run_id,'projection_pending',lease,reason='projection_unavailable',omissions=omissions)
        self.store.set_checkpoint(run_id,'projection_ack',canonical(ack),lease=lease,now=self.clock())
        return self._summary(run_id,'projected',lease,omissions=omissions)

    def morning_anchor(self,run_id):
        """Closing consumers receive the original selected scenario and receipt."""
        step=self.store.get_frozen(run_id,'operation:ihsg_text')
        outlook=self.store.get_frozen(run_id,'presentation') or self.store.get_frozen(run_id,'outlook')
        if step is None or outlook is None: return None
        receipts=self.store.get_receipts(run_id,step.slot)
        confirmed=next((row for row in reversed(receipts) if row['status']=='delivered'),None)
        if confirmed is None: return None
        return dict(text=step.payload['payload']['content'],scenario=outlook.payload,
                    receipt=confirmed,operation_key=step.payload['operation_key'],digest=step.payload['digest'])
