"""Grounded structured source assessment with a non-blocking facts-only deadline."""
from datetime import datetime, time
import json
import math
from threading import BoundedSemaphore, Event, Thread
from time import monotonic
from zoneinfo import ZoneInfo
from .calendar import aware
from .config import retained_operator_config, timing_for
from .store import canonical, digest, FreezeConflict
from .global_markets import format_global_rows
from .economic_calendar import format_calendar_events
from .formatting import format_claims, format_scenario
from .outlook_validation import validate_outlook

# One possibly stuck worker maximum per process, including retries and new runs.
# Daemon threads do not join at interpreter exit. There is no executor context.
_WORKER_GATE=BoundedSemaphore(1)
_CLAIM_CONTRACT={
    'revision':'source-scenario-v2',
    'format':{'claims':'0 to 3 {evidence_id, excerpt} exact complete source sentences',
              'scenario':{'base_case':'exact full-source reference {evidence_id, excerpt}',
                          'supporting':'0 to 3 full-source references',
                          'opposing':'0 to 3 full-source references',
                          'change_conditions':'1 to 3 full-source references',
                          'pulse':{'optimistic':'0 to 3 full-source references','cautious':'0 to 3 full-source references'}}},
    'support':'scenario refs quote full untruncated frozen source text, maximum 600 characters each; at most 3 unique sources',
    'assessment':'roles are model assessment of attributed commentary, never certified stance or verified facts',
    'conditional':'base and change conditions must retain explicit sourced conditional language',
    'forbidden':'freeform prose, invented direction/levels, numerical probabilities, independent-opinion counts'}



def freeze_bundle(store,run_id,*,model_version: str,prompt_version: str,lease,now):
    if not model_version or not prompt_version:
        raise ValueError('model and prompt versions required')
    run=store.get_run(run_id)
    existing=store.get_frozen(run_id,'writer_bundle')
    if existing is not None:
        if existing.payload['versions']!={'model':model_version,'prompt':prompt_version}:
            raise FreezeConflict('writer versions already frozen')
        return existing
    fields={}; dependencies={}
    for slot,default in [('evidence',{'items':[],'facts_only':True,'degraded_reasons':['missing_evidence']}),
                         ('globals',{'quotes':[]}),('calendar_events',{'events':[]}),('inputs',{})]:
        record=store.get_frozen(run_id,slot)
        fields[slot]=record.payload if record else default
        if record: dependencies[slot]=record.digest
    configuration=store.get_frozen(run_id,'operator_config')
    if configuration: dependencies['operator_config']=configuration.digest
    payload=dict(fields,cutoff=run.freeze_at,publication_session=run.session,
                 fallback_at=timing_for(datetime.fromisoformat(run.session).date(),retained_operator_config(store,run_id))['fallback'].isoformat(),
                 versions={'model':model_version,'prompt':prompt_version},claim_contract=_CLAIM_CONTRACT)
    return store.freeze(run_id,'writer_bundle',payload,lease=lease,now=now,dependencies=dependencies)


def _facts_text(payload):
    sections=[]
    # Values and labels are deterministic upstream inputs, never model prose.
    for fact in payload.get('inputs',{}).get('facts',[]):
        if (type(fact) is dict and set(fact)=={'label','value','unit'}
                and type(fact['label']) is str and type(fact['unit']) is str
                and type(fact['value']) in (int,float) and math.isfinite(fact['value'])):
            sections.append(f"{fact['label']}: {fact['value']:g} {fact['unit']}")
    globals_text=format_global_rows(payload.get('globals',{}).get('quotes',[]),logos={})
    if globals_text: sections.append('Pasar global\n'+globals_text)
    calendar_text=format_calendar_events(payload.get('calendar_events',{'events':[]}))
    if calendar_text: sections.append('Agenda Ekonomi Indonesia\n'+calendar_text)
    return '\n\n'.join(sections)


MODEL_ATTEMPTS = 2


def _evidence_floor(payload):
    """Use only the verified numerical close and dated upstream facts, not opinion."""
    inputs=payload.get('inputs',{})
    previous=inputs.get('previous_session')
    if not previous or not inputs.get('benchmark_version'):
        return False
    close=any(type(fact) is dict and fact.get('label')=='IHSG close '+previous
              and fact.get('unit')=='poin' and type(fact.get('value')) in (int,float)
              and math.isfinite(fact['value']) and fact['value']>0
              for fact in inputs.get('facts',[]))
    if not close: return False
    lower=payload['evidence'].get('previous_cutoff')
    cutoff=aware(datetime.fromisoformat(payload['cutoff']))
    for quote in payload.get('globals',{}).get('quotes',[]):
        try:
            observed=aware(datetime.fromisoformat(quote['price_at']))
            if (quote['status']=='available' and lower
                    and aware(datetime.fromisoformat(lower))<=observed<=cutoff):
                return True
        except (KeyError,TypeError,ValueError): pass
    for event in payload.get('calendar_events',{}).get('events',[]):
        try:
            if event['date']>=cutoff.astimezone(ZoneInfo('Asia/Jakarta')).date().isoformat() and event['source_url']:
                return True
        except (KeyError,TypeError): pass
    return False


def write_outlook(bundle,model,*,now: datetime,timeout_seconds: float=75) -> dict:
    """Pass a JSON-isolated frozen bundle to one bounded injected callable.

    Timeout selects an already-built facts-only result; late worker output never
    touches this result or owner state. A hung worker keeps the gate until it
    exits, so later calls degrade busy without spawning more threads. No attempt
    is made to kill a Python thread or to claim a canceled external model call.
    """
    started_at=monotonic()
    instant=aware(now)
    if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or not 0<timeout_seconds<=1500:
        raise ValueError('bounded positive writer timeout required')
    raw=bundle.payload if hasattr(bundle,'payload') else bundle
    payload=json.loads(canonical(raw))
    identity=bundle.digest if hasattr(bundle,'digest') else digest(payload)
    facts=_facts_text(payload)
    result=dict(mode='facts_only',reason=None,claims=[],scenario=None,text='Ringkasan faktual. Outlook belum tersedia.'+('\n\n'+facts if facts else ''),
                market_facts=payload.get('inputs',{}).get('facts',[]),global_facts=payload.get('globals',{}).get('quotes',[]),
                calendar_facts=payload.get('calendar_events',{}).get('events',[]),bundle_digest=identity,
                versions=payload['versions'])
    cutoff=aware(datetime.fromisoformat(payload['cutoff']))
    day=cutoff.astimezone(ZoneInfo('Asia/Jakarta')).date()
    deadline=aware(datetime.fromisoformat(payload['fallback_at'])) if 'fallback_at' in payload else datetime.combine(day,time(7,55),tzinfo=ZoneInfo('Asia/Jakarta'))
    remaining=(deadline-instant).total_seconds()
    if remaining<=monotonic()-started_at:
        result['reason']='fallback_deadline'; return result
    if payload['evidence'].get('facts_only',True):
        result['reason']='incomplete_evidence'; return result
    if not _evidence_floor(payload):
        result['reason']='evidence_floor'; return result
    if not _WORKER_GATE.acquire(blocking=False):
        result['reason']='model_busy'; return result
    finished=Event(); output=[]
    # The model gets its own serialization copy, including nested global facts.
    model_input=json.loads(canonical(payload))
    def worker():
        try:
            feedback=None
            for attempt in range(MODEL_ATTEMPTS):
                # One bounded correction pass inside the same worker, deadline and gate. The
                # retry carries only our own fixed validation message, never source or model text.
                response=model(model_input if feedback is None else {**model_input,'retry_feedback':feedback})
                try:
                    validated=validate_outlook(response,payload)
                    encoded=canonical({'claims':format_claims(validated.claims),'scenario':validated.scenario.value,
                                       'text':format_scenario(validated.scenario)})
                    output.append(('supported',encoded) if len(encoded.encode())<=32768 else ('unsupported_claim',None))
                    break
                except (ValueError,KeyError,TypeError) as error:
                    feedback=str(error)[:160] if isinstance(error,ValueError) else 'structure invalid'
                    if attempt+1==MODEL_ATTEMPTS:
                        output.append(('unsupported_claim',None))
        except Exception:
            output.append(('model_unavailable',None))
        finally:
            finished.set(); _WORKER_GATE.release()
    thread=Thread(target=worker,name='morning-brief-writer',daemon=True)
    try: thread.start()
    except Exception:
        _WORKER_GATE.release(); result['reason']='model_unavailable'; return result
    budget=min(timeout_seconds,max(0,remaining-(monotonic()-started_at)-0.001))
    if not finished.wait(budget):
        result['reason']='model_timeout'; return result
    if monotonic()-started_at>=remaining:
        result['reason']='model_timeout'; return result
    if not output or output[0][0]!='supported':
        result['reason']=output[0][0] if output else 'model_unavailable'; return result
    structured=json.loads(output[0][1]); claims=structured['claims']
    result.update(mode='supported',reason=None,claims=claims,scenario=structured['scenario'],
                  text=structured['text']+('\n\n'+facts if facts else ''))
    return result
