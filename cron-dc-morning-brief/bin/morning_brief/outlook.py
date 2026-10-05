"""Extractive, evidence-attributed writer with a non-blocking facts-only deadline."""
from datetime import datetime, time
import json
import math
import re
from threading import BoundedSemaphore, Event, Thread
from time import monotonic
from zoneinfo import ZoneInfo
from .calendar import aware
from .store import canonical, digest, FreezeConflict
from .global_markets import format_global_rows
from .economic_calendar import format_calendar_events

# One possibly stuck worker maximum per process, including retries and new runs.
# Daemon threads do not join at interpreter exit. There is no executor context.
_WORKER_GATE=BoundedSemaphore(1)
_CLAIM_CONTRACT={'format':'claims: [{evidence_id, excerpt}]','maximum_claims':3,
                 'support':'exact complete frozen sentence, attributed as source statement',
                 'forbidden':'freeform direction, derived levels, probabilities, independent-opinion counts'}


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
    payload=dict(fields,cutoff=run.freeze_at,publication_session=run.session,
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
    if calendar_text: sections.append('Agenda Indonesia\n'+calendar_text)
    return '\n\n'.join(sections)


def _claims(response,payload):
    if type(response) is not dict or set(response)!={'claims'} or type(response['claims']) is not list or not 1<=len(response['claims'])<=3:
        raise ValueError('structured supported claims required')
    evidence={row['evidence_id']:row for row in payload['evidence']['items']}
    claims=[]; seen=set()
    for claim in response['claims']:
        if type(claim) is not dict or set(claim)!={'evidence_id','excerpt'}:
            raise ValueError('claim contains unsupported fields')
        identity,excerpt=claim['evidence_id'],claim['excerpt']
        if type(identity) is not str or identity not in evidence or type(excerpt) is not str or not 1<=len(excerpt)<=600:
            raise ValueError('claim support missing')
        row=evidence[identity]
        # Line wraps retain preceding negation/conditions inside the source span.
        # Only punctuation followed by whitespace marks a sentence boundary.
        sentences=re.split(r'(?<=[.!?])\s+',row['text'].strip())
        if excerpt not in sentences or row.get('text_truncated'):
            raise ValueError('claim is not a complete supported excerpt')
        if re.search(r'(?:probabilitas|probability|peluang).{0,40}\d|\d.{0,40}(?:probabilitas|probability)',excerpt,re.I):
            raise ValueError('calibrated probability is outside writer contract')
        if (identity,excerpt) in seen: raise ValueError('duplicate claim')
        seen.add((identity,excerpt))
        # No freeform inference is rendered. The source owns the quoted statement.
        publisher=re.sub(r'([\\\[\]()*_`])',r'\\\1',row['publisher_id'])
        claims.append(dict(evidence_id=identity,excerpt=excerpt,publisher_id=row['publisher_id'],
                           source_url=row['source_url'],text=f"Menurut [{publisher}]({row['source_url']}): {excerpt}"))
    return claims


def write_outlook(bundle,model,*,now: datetime,timeout_seconds: float=30) -> dict:
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
    result=dict(mode='facts_only',reason=None,claims=[],text='Ringkasan faktual. Outlook belum tersedia.'+('\n\n'+facts if facts else ''),
                market_facts=payload.get('inputs',{}).get('facts',[]),global_facts=payload.get('globals',{}).get('quotes',[]),
                calendar_facts=payload.get('calendar_events',{}).get('events',[]),bundle_digest=identity,
                versions=payload['versions'])
    cutoff=aware(datetime.fromisoformat(payload['cutoff']))
    day=cutoff.astimezone(ZoneInfo('Asia/Jakarta')).date()
    deadline=datetime.combine(day,time(7,55),tzinfo=ZoneInfo('Asia/Jakarta'))
    remaining=(deadline-instant).total_seconds()
    if remaining<=monotonic()-started_at:
        result['reason']='fallback_deadline'; return result
    if payload['evidence'].get('facts_only',True):
        result['reason']='incomplete_evidence'; return result
    if not _WORKER_GATE.acquire(blocking=False):
        result['reason']='model_busy'; return result
    finished=Event(); output=[]
    # The model gets its own serialization copy, including nested global facts.
    model_input=json.loads(canonical(payload))
    def worker():
        try:
            response=model(model_input)
            try:
                claims=_claims(response,payload)
                encoded=canonical(claims)
                output.append(('supported',encoded) if len(encoded.encode())<=8192 else ('unsupported_claim',None))
            except (ValueError,KeyError,TypeError):
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
    claims=json.loads(output[0][1])
    result.update(mode='supported',reason=None,claims=claims,
                  text='\n'.join(claim['text'] for claim in claims)+('\n\n'+facts if facts else ''))
    return result
