"""Injected cache-only owner pipeline; previews never discover credentials or post."""
import base64
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import uuid
from zoneinfo import ZoneInfo
from bursawatch_discord_delivery import OperationIntent
from .calendar import aware, SessionCalendar
from .inputs import (Provenance, MembershipSnapshot, CapSnapshot, PriceSeries, ActionDecision,
                     prepare_numerical_inputs, InputUnavailable)
from .rotation import BasketResult, Position, calculate_from_inputs, UnsupportedBasket, select_groups, unselected_letters
from .evidence import freeze_source_evidence
from .global_markets import parse_yahoo_chart, freeze_globals
from .economic_calendar import freeze_calendar_events
from .outlook import freeze_bundle, write_outlook
from .rendering import RenderedArtifact, render_rotation, render_ihsg
from .formatting import format_brief, attachment_caption, six_block_markdown
from .publication import Publisher, OWNER
from .store import canonical, digest, stamp

ZONE=ZoneInfo('Asia/Jakarta')
HEARTBEAT_DESTINATION='1505162000420835388'


def jsonable(value):
    if is_dataclass(value): return jsonable(asdict(value))
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,dict): return {k:jsonable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [jsonable(v) for v in value]
    return value


def _attested(payload,proof,cutoff,records):
    """External caller attestation, never certification from positive close rows."""
    try:
        return (proof['kind']=='caller_attestation' and proof['verified'] is True
            and proof['content_sha256']==digest(payload)
            and aware(datetime.fromisoformat(proof['available_at']))<=cutoff
            and bool(proof['source_url']) and bool(proof['evidence_ref'])
            and (proof.get('provider_record_digest') is None or proof['provider_record_digest'] in records))
    except (KeyError,ValueError,TypeError): return False


def _basket(payload):
    return BasketResult(**{**payload,'trail':tuple(Position(**p) for p in payload['trail']),
        'action_decisions':tuple(ActionDecision(**a) for a in payload['action_decisions']),
        'aligned_closes':{k:tuple(v) for k,v in payload['aligned_closes'].items()}})


def _artifact(payload):
    if payload is None: return None
    return RenderedArtifact(base64.b64decode(payload['data'],validate=True),payload['content_type'],
        payload['sha256'],payload['width'],payload['height'],payload['manifest'])


class MorningRunner:
    def __init__(self,store,source,delivery,projection,*,clock):
        self.store,self.source,self.delivery,self.projection,self.clock=store,source,delivery,projection,clock
        self.publisher=Publisher(store,delivery,projection,clock=clock)

    def _heartbeat(self,result,*,preview,preview_dir,accounting):
        now=aware(self.clock()).astimezone(ZONE)
        if result['phase']=='fatal':
            content=f'❌ {OWNER} · {now:%H:%M} WIB · failed: {result["reason"]}'
        else:
            counts={k:accounting.get(k,'unknown') for k in ('cache_hits','cache_misses','reserved','spent','uncertain')}
            for key,value in counts.items():
                if value!='unknown' and (type(value) not in (int,float) or not 0<=value<=100000):
                    counts[key]='unknown'
            tokens=' '.join(f'{k}={v}' for k,v in counts.items())
            content=(f'🫀 {OWNER} · {now:%H:%M} WIB · phase={result["phase"]} {tokens} '
                f'gaps={result.get("gaps",0)} fallback={result.get("fallback","none")} '
                f'images_omitted={result.get("image_omissions",0)} receipts={result.get("receipt_outcome","none")} '
                f'late_s={result.get("lateness_seconds",0)}')
            if result.get('gaps') or result.get('image_omissions') or result['phase'] in {'unresolved','projection_pending'}:
                content+=' ⚠️'
        result['heartbeat']=dict(destination=HEARTBEAT_DESTINATION,text=content,simulated=preview)
        if preview:
            if preview_dir:
                path=Path(preview_dir); path.mkdir(parents=True,exist_ok=True,mode=0o700)
                (path/'heartbeat.json').write_text(canonical(result['heartbeat']))
        else:
            try:
                operation=OperationIntent(key=f'{OWNER}:heartbeat:{uuid.uuid4().hex}',kind='channel_message_create',
                    ordering_key=f'{OWNER}:heartbeat',target={'channel_id':HEARTBEAT_DESTINATION},
                    payload={'content':content,'allowed_mentions':{'parse':[]}})
                receipt=self.delivery.submit(operation)
                result['heartbeat']['status']=receipt.status
            except Exception: result['heartbeat']['status']='unresolved'
        return result

    def _inputs(self,run,upstream,calendar,lease):
        data=upstream.payload['numerical']; cutoff=aware(datetime.fromisoformat(run.freeze_at))
        groups={'sectors':[],'konglo':[]}; gaps=[]; facts=[]
        records={digest(row) for row in upstream.payload['provider_records']}
        benchmark=data.get('benchmark',{}); proof=data.get('benchmark_attestation',{})
        benchmark_valid=_attested(benchmark,proof,cutoff,records) and bool(proof.get('version'))
        previous=calendar.last_sessions(date.fromisoformat(run.session),2)[0]
        # Price rows outside the previous closing boundary cannot enter facts.
        if benchmark_valid and previous.isoformat() in benchmark:
            value=benchmark[previous.isoformat()]
            if type(value) in (int,float) and value>0:
                facts=[dict(label=f'IHSG close {previous.isoformat()}',value=value,unit='poin')]
        else: gaps.append('benchmark_attestation_unavailable')
        try:
            raw_caps=data['caps']
            caps=CapSnapshot(**{**raw_caps,'collected_at':datetime.fromisoformat(raw_caps['collected_at']),
                'effective_date':date.fromisoformat(raw_caps['effective_date']) if raw_caps['effective_date'] else None,
                'provenance':Provenance(**raw_caps['provenance'])})
            prices={}
            for symbol,row in data.get('prices',{}).items():
                attested=_attested(row,data.get('price_attestations',{}).get(symbol,{}),cutoff,records)
                prices[symbol]=PriceSeries(**{**row,'trading_eligible':row['trading_eligible'] is True and attested})
                if not attested: gaps.append('price_attestation_unavailable:'+symbol)
            actions=tuple(ActionDecision(**a) for a in data.get('actions',[]))
        except (KeyError,ValueError,TypeError):
            caps=None; prices={}; actions=(); gaps.append('numerical_inputs_unavailable')
        for kind in groups:
            try:
                if caps is None or not benchmark_valid: raise InputUnavailable('verified inputs unavailable')
                row=data['memberships'][kind]
                membership=MembershipSnapshot(**{**row,'provenance':Provenance(**row['provenance']),
                    'collected_at':datetime.fromisoformat(row['collected_at']) if row.get('collected_at') else None,
                    'ownership_as_of':date.fromisoformat(row['ownership_as_of']) if row.get('ownership_as_of') else None,
                    'groups':{k:tuple(v) for k,v in row['groups'].items()}})
                validated=prepare_numerical_inputs(calendar,membership,caps,prices,benchmark,through=previous,
                    publication_session=date.fromisoformat(run.session),freeze_at=cutoff,actions=actions)
                for name in sorted(membership.groups):
                    try: groups[kind].append(jsonable(calculate_from_inputs(name,validated)))
                    except UnsupportedBasket: gaps.append(kind+':unsupported:'+name)
            except (InputUnavailable,ValueError,KeyError,TypeError): gaps.append(kind+':unavailable')
        payload=dict(groups=groups,gaps=sorted(set(gaps)),facts=facts,cutoff=run.freeze_at,
            previous_session=previous.isoformat(),attestation_policy='external-caller/hash-and-cutoff-bound',
            upstream_digest=upstream.digest,benchmark_version=proof.get('version') if benchmark_valid else None)
        return self.store.freeze(run.run_id,'inputs',payload,lease=lease,now=self.clock(),dependencies={'upstream':upstream.digest})

    def _select(self,run,inputs,lease,*,model,model_version,prompt_version,chart_client,chart_request):
        existing=self.store.get_frozen(run.run_id,'selection')
        if existing: return existing
        bundle=freeze_bundle(self.store,run.run_id,model_version=model_version,prompt_version=prompt_version,lease=lease,now=self.clock())
        outlook=self.store.get_frozen(run.run_id,'outlook')
        if outlook is None:
            output=write_outlook(bundle,model,now=self.clock())
            outlook=self.store.freeze(run.run_id,'outlook',output,lease=lease,now=self.clock(),dependencies={'writer_bundle':bundle.digest})
        groups={kind:tuple(_basket(row) for row in inputs.payload['groups'][kind]) for kind in ('sectors','konglo')}
        letters=unselected_letters(groups['konglo'],select_groups(groups['konglo']))
        letter_record=self.store.freeze(run.run_id,'letters',letters,lease=lease,now=self.clock(),dependencies={'inputs':inputs.digest})
        images=[]; omissions=[]; session=date.fromisoformat(run.session)
        for kind in ('ihsg','sectors','konglo'):
            try:
                if kind=='ihsg':
                    if chart_client is None or chart_request is None: raise ValueError('chart unavailable')
                    artifact=chart_client.render(chart_request,cache_only=True)
                    rendered=render_ihsg(artifact,publication_session=session,latest_close=date.fromisoformat(inputs.payload['previous_session']))
                else:
                    if not groups[kind]: raise ValueError('rotation unavailable')
                    rendered=render_rotation(groups[kind],kind=kind,publication_session=session,letters=letters if kind=='konglo' else None)
                images.append(dict(data=base64.b64encode(rendered.data).decode('ascii'),content_type=rendered.content_type,
                    sha256=rendered.sha256,width=rendered.width,height=rendered.height,manifest=rendered.manifest))
                omissions.append(None)
            except ValueError:
                images.append(None); omissions.append(kind+'_image_unavailable')
            except Exception:
                images.append(None); omissions.append(kind+'_image_unavailable')
        globals_record=self.store.get_frozen(run.run_id,'globals'); calendar_record=self.store.get_frozen(run.run_id,'calendar_events')
        notices={kind:['Gambar belum tersedia.'] if omission else [] for kind,omission in zip(('ihsg','sectors','konglo'),omissions)}
        texts=format_brief(publication_session=session,cutoff=datetime.fromisoformat(run.freeze_at),
            target=datetime.combine(session,time(8),tzinfo=ZONE),outlook=outlook.payload,
            globals=globals_record.payload['quotes'],calendar=calendar_record.payload,
            sectors=groups['sectors'],konglo=groups['konglo'],notices=notices)
        deps={'inputs':inputs.digest,'outlook':outlook.digest,'letters':letter_record.digest,
              'globals':globals_record.digest,'calendar_events':calendar_record.digest}
        return self.store.freeze(run.run_id,'selection',dict(texts=list(texts),images=images,omissions=omissions),
                                 lease=lease,now=self.clock(),dependencies=deps)

    def run(self,*,calendar,numerical,global_inputs,calendar_snapshots,model,model_version,prompt_version,
            preview=True,preview_dir=None,destination=None,reviewed_config=None,
            sectors_client=None,sectors_requests=(),chart_client=None,chart_request=None,accounting=None):
        if type(preview) is not bool or (not preview and (not reviewed_config or not destination)):
            raise ValueError('live injection requires reviewed configuration and destination')
        accounting=dict(accounting or {})
        result={'phase':'fatal','reason':'owner_unavailable'}
        lease=None
        try:
            now=aware(self.clock()); session=now.astimezone(ZONE).date()
            cutoff=datetime.combine(session,time(7,30),tzinfo=ZONE)
            if now<cutoff:
                result={'phase':'before_freeze'}
            else:
                run=self.store.create_run(session.isoformat(),freeze_at=cutoff)
                lease=self.store.acquire_lease(run.run_id,uuid.uuid4().hex,now=now,seconds=600)
                saved=self.store.get_frozen(run.run_id,'publication')
                if saved and not preview:
                    # Destination correction needs a new reviewed rollout, never retarget an old key.
                    if destination!=saved.payload['destination']: raise ValueError('frozen destination mismatch')
                    result=self.publisher.publish(run.run_id,lease=lease)
                else:
                    upstream=self.store.get_frozen(run.run_id,'upstream')
                    if upstream:
                        raw=upstream.payload['calendar']
                        calendar=SessionCalendar(**{**raw,'amendment_checked_at':datetime.fromisoformat(raw['amendment_checked_at']),
                            'valid_from':date.fromisoformat(raw['valid_from']),'valid_through':date.fromisoformat(raw['valid_through']),
                            'sessions':tuple(date.fromisoformat(s) for s in raw['sessions'])})
                    checked=aware(calendar.amendment_checked_at)
                    if checked>cutoff or cutoff-checked>timedelta(days=7): raise ValueError('calendar amendment unavailable')
                    if not calendar.is_session(session):
                        result={'phase':'no_session'}
                        self.store.transition(run.run_id,'no_session',lease=lease,now=self.clock())
                    else:
                        if upstream is None:
                            records=[]
                            if sectors_requests and (sectors_client is None or sectors_client.config.cache_only is not True):
                                raise ValueError('cache-only shared provider required')
                            for identity in sectors_requests:
                                try:
                                    record=sectors_client.get(identity,cutoff=cutoff,max_cost=0)
                                    records.append(dict(identity=record.identity.key,request_url=record.identity.url,
                                        payload=record.payload,available_at=stamp(record.available_at),provenance=record.provenance))
                                except Exception: accounting['cache_misses']=accounting.get('cache_misses',0)+1
                            upstream=self.store.freeze(run.run_id,'upstream',jsonable(dict(calendar=calendar,numerical=numerical,
                                global_inputs=global_inputs,calendar_snapshots=calendar_snapshots,provider_records=records)),lease=lease,now=self.clock())
                        inputs=self.store.get_frozen(run.run_id,'inputs') or self._inputs(run,upstream,calendar,lease)
                        previous_cutoff=datetime.combine(calendar.last_sessions(session,2)[0],time(7,30),tzinfo=ZONE)
                        evidence=freeze_source_evidence(self.store,run.run_id,self.source,previous_cutoff=stamp(previous_cutoff),lease=lease,now=self.clock())
                        if self.store.get_frozen(run.run_id,'globals') is None:
                            quotes=[]
                            for row in upstream.payload['global_inputs']:
                                quotes.append(parse_yahoo_chart(row['name'],row['payload'],freeze_at=cutoff,
                                    retrieved_at=datetime.fromisoformat(row['retrieved_at']),sessions=row['sessions']))
                            freeze_globals(self.store,run.run_id,quotes,lease=lease,now=self.clock())
                        if self.store.get_frozen(run.run_id,'calendar_events') is None:
                            freeze_calendar_events(self.store,run.run_id,upstream.payload['calendar_snapshots'],lease=lease,now=self.clock())
                        selected=self._select(run,inputs,lease,model=model,model_version=model_version,prompt_version=prompt_version,
                            chart_client=chart_client,chart_request=chart_request)
                        if preview:
                            result={'phase':'preview','receipt_outcome':'simulated'}
                            if preview_dir: self._preview(run,selected,preview_dir)
                        else:
                            self.publisher.freeze(run.run_id,texts=selected.payload['texts'],images=tuple(_artifact(row) for row in selected.payload['images']),
                                omissions=selected.payload['omissions'],destination=destination,lease=lease)
                            result=self.publisher.publish(run.run_id,lease=lease)
                        result.update(gaps=len(inputs.payload['gaps'])+len(evidence.payload.get('degraded_reasons',[])),
                            fallback=self.store.get_frozen(run.run_id,'outlook').payload['mode'],image_omissions=sum(bool(v) for v in selected.payload['omissions']))
                result['receipt_outcome']=result.get('receipt_outcome',result['phase'])
                inputs=self.store.get_frozen(run.run_id,'inputs')
                evidence=self.store.get_frozen(run.run_id,'evidence')
                selected=self.store.get_frozen(run.run_id,'selection')
                outlook=self.store.get_frozen(run.run_id,'outlook')
                if inputs and evidence:
                    result['gaps']=len(inputs.payload['gaps'])+len(evidence.payload.get('degraded_reasons',[]))
                if selected: result['image_omissions']=sum(bool(v) for v in selected.payload['omissions'])
                if outlook: result['fallback']=outlook.payload['mode']
                self.store.set_checkpoint(run.run_id,'attempt_summary',canonical(result),lease=lease,now=self.clock())
        except Exception as error:
            result={'phase':'fatal','reason':type(error).__name__}
        finally:
            if lease is not None:
                try: self.store.release_lease(lease,now=self.clock())
                except Exception: pass
        return self._heartbeat(result,preview=preview,preview_dir=preview_dir,accounting=accounting)

    @staticmethod
    def _preview(run,selected,directory):
        path=Path(directory); path.mkdir(parents=True,exist_ok=True,mode=0o700); images=[]
        for kind,row in zip(('ihsg','sectors','konglo'),selected.payload['images']):
            if row is None: images.append(None); continue
            artifact=_artifact(row)
            (path/(kind+'.png')).write_bytes(artifact.data)
            (path/(kind+'-manifest.json')).write_text(canonical(artifact.manifest))
            images.append({'title':attachment_caption(kind,date.fromisoformat(run.session)),'path':kind+'.png'})
        (path/'preview.md').write_text(six_block_markdown(tuple(selected.payload['texts']),images))
        (path/'selection.json').write_text(canonical({'run_id':run.run_id,'digest':selected.digest,'synthetic_or_attested':True}))
