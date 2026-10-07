"""Bounded, resumable Yahoo input production; no writer or publication calls."""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from zoneinfo import ZoneInfo

from yahoo_market_data.rotation import parse_caps, parse_rotation_history
from .calendar import aware
from .host import private_file
from .inputs import CapSnapshot, Provenance, cap_status, symbol
from .public_collector import YahooTransport, write_once
from .runner import jsonable
from .store import canonical, digest, stamp


def _replace(path, value):
    if path.is_symlink():
        raise ValueError('producer pointer cannot be a symlink')
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        output.write(canonical(value).encode())
        temporary=Path(output.name)
    os.replace(temporary,path)


def _retain(cache, record, *, now, cutoff):
    observed=aware(datetime.fromisoformat(record['retrieved_at']))
    if not observed<=now<=cutoff:
        raise ValueError('source visibility outside producer boundary')
    if (record['source_sha256'] is None or len(record['source_sha256'])!=64
            or not record['source_url'].startswith('https://query1.finance.yahoo.com/')):
        raise ValueError('native Yahoo source provenance required')
    encoded=canonical(record).encode(); identity=hashlib.sha256(encoded).hexdigest()
    path=cache/(identity+'.json'); write_once(path,encoded)
    return dict(record,artifact_path=str(path),record_sha256=identity)


def _proof(value, *, available_at, evidence, method):
    return dict(kind='caller_attestation',verified=True,content_sha256=digest(value),
        available_at=stamp(available_at),source_url='https://query1.finance.yahoo.com/v8/finance/chart/',
        evidence_ref=evidence,method=method)


def _cap_snapshot(raw):
    return CapSnapshot(**{**raw,'collected_at':aware(datetime.fromisoformat(raw['collected_at'])),
        'effective_date':None,'provenance':Provenance(**raw['provenance'])})


def _reference(record):
    return {key:record[key] for key in ('artifact_path','record_sha256')}


def _source(cache, reference):
    identity=reference['record_sha256']
    if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{64}',identity):
        raise ValueError('source digest identity required')
    path=cache/(identity+'.json')
    if reference['artifact_path']!=str(path):
        raise ValueError('source reference outside shared cache')
    raw=private_file(path,max_bytes=2_100_000)
    if hashlib.sha256(raw).hexdigest()!=identity:
        raise ValueError('retained Yahoo source digest mismatch')
    return dict(json.loads(raw),**reference)


def collect_rotation(*, memberships, calendar, publication_session, cutoff, source_cache,
                     now, request_limit=24, transport=None, clock=None):
    """Resume at most request_limit HTTP calls in one explicit no-post pass.

    A cap quote batch needs two guest-handshake calls on the first use. Partial
    refreshes never overwrite a complete basket's current/previous-week caps.
    The cache stores original sources and immutable per-basket snapshots.
    """
    now=aware(now); cutoff=aware(cutoff)
    if (now>cutoff or not calendar.is_session(publication_session)
            or cutoff.astimezone(ZoneInfo('Asia/Jakarta')).date()!=publication_session
            or type(request_limit) is not int or not 3<=request_limit<=64
            or set(memberships)!={'sectors','konglo'}):
        raise ValueError('bounded explicit rotation production required')
    if calendar.amendment_checked_at>now or cutoff-calendar.amendment_checked_at>timedelta(days=7):
        raise ValueError('calendar amendment evidence unavailable')
    through=calendar.last_sessions(publication_session,2)[0]
    sessions=calendar.last_sessions(through,18)
    if now.astimezone(ZoneInfo('Asia/Jakarta')).date()<=through:
        raise ValueError('closing session completion not yet established')
    all_symbols=sorted({symbol(s) for membership in memberships.values()
                        for members in membership.groups.values() for s in members})
    if not all_symbols or len(all_symbols)>2000:
        raise ValueError('bounded fixed membership required')
    cache=Path(source_cache)
    if not cache.is_absolute() or cache.is_symlink():
        raise ValueError('explicit private source cache required')
    cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    if cache.stat().st_mode & 0o077:
        raise ValueError('private source cache required')
    fd=os.open(cache/'rotation-producer.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'r+b') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode) or os.fstat(lock.fileno()).st_mode & 0o077:
            raise ValueError('private producer lock required')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _collect(cache,memberships,calendar,publication_session,cutoff,now,request_limit,
                        transport or YahooTransport(cache),clock or (lambda:datetime.now(timezone.utc)),
                        all_symbols,sessions)


def _collect(cache,memberships,calendar,session,cutoff,now,limit,transport,clock,tickers,sessions):
    index_path=cache/'rotation-index.json'
    index=json.loads(private_file(index_path)) if index_path.exists() else dict(version=1,history={},caps={},baskets={})
    if index.get('version')!=1:
        raise ValueError('rotation cache version mismatch')
    week=calendar.first_session_of_week(session).isoformat()
    generation=digest(dict(week=week,symbols=tickers))
    refresh=index['caps'].setdefault(generation,dict(week=week,batches={}))
    before=transport.fetches; failures=[]; cache_hits=0

    # Stable exact quote batches avoid the incomplete Indonesia screener and
    # retain missing native cap rows as missing, with no shares reconstruction.
    for offset in range(0,len(tickers),100):
        batch=tickers[offset:offset+100]; key=digest(batch)
        if key in refresh['batches']: continue
        cost=3 if getattr(transport,'crumb',None) is None else 1
        if transport.fetches-before+cost>limit: break
        try:
            record=transport.cap_quotes(batch)
            record=_retain(cache,record,now=aware(clock()),cutoff=cutoff)
            parse_caps(record['payload'],symbols=[s+'.JK' for s in batch])
            refresh['batches'][key]=dict(record=_reference(record),symbols=batch)
            _replace(index_path,index)
        except Exception as error:
            failures.append('caps:'+type(error).__name__)
            # Stop this pass after a provider failure. Do not cycle other symbols
            # through a failed guest session, retry or silently switch routes.
            break

    values={}; cap_sources=[]
    for entry in refresh['batches'].values():
        record=_source(cache,entry['record'])
        if aware(datetime.fromisoformat(record['retrieved_at']))<=now:
            values.update(parse_caps(record['payload'],symbols=[s+'.JK' for s in entry['symbols']]))
            cap_sources.append(record)
    caps_by_basket={kind:{} for kind in memberships}; cap_gaps=[]
    membership_key=digest({kind:jsonable(asdict(m)) for kind,m in memberships.items()})
    saved=index['baskets'].setdefault(membership_key,{})
    for kind,membership in memberships.items():
        for name,members in membership.groups.items():
            key=digest(dict(kind=kind,name=name,members=members))
            if all(s in values for s in members):
                collected=max(aware(datetime.fromisoformat(r['retrieved_at'])) for r in cap_sources)
                raw=dict(identity=digest(dict(generation=generation,members=members,values={s:values[s] for s in members})),
                    collected_at=stamp(collected),effective_date=None,values={s:values[s] for s in members},
                    provenance=dict(source_url='https://query1.finance.yahoo.com/v7/finance/quote',
                        digest=digest(cap_sources),method='yahoo-native-cap/collection-date-economic-date-unverified',
                        reference=','.join(r['artifact_path'] for r in cap_sources)))
                saved[key]=raw
            raw=saved.get(key)
            if raw and aware(datetime.fromisoformat(raw['collected_at']))<=now and cap_status(_cap_snapshot(raw),session,calendar) in {'current_week','extra_week'}:
                caps_by_basket[kind][name]=raw
            else: cap_gaps.append(kind+':caps_unavailable:'+name)
    _replace(index_path,index)

    # History is keyed by the actual final close, not by collection wall time.
    # Even invalid native responses are retained for this window, so a halted
    # stock cannot cause a request on every tick. The next close gets a new key.
    price_symbols=sorted({ticker for kind,membership in memberships.items()
        for name,members in membership.groups.items() if name in caps_by_basket[kind]
        for ticker in members})
    prices={}; proofs={}; actions=[]; history_gaps=[]
    for ticker in price_symbols:
        key=digest(dict(symbol=ticker,sessions=[s.isoformat() for s in sessions]))
        reference=index['history'].get(key)
        record=_source(cache,reference) if reference is not None else None
        if record is None and not failures and transport.fetches-before<limit:
            try:
                record=_retain(cache,transport.stock_history(ticker),now=aware(clock()),cutoff=cutoff)
                index['history'][key]=_reference(record); _replace(index_path,index)
            except Exception as error:
                failures.append('history:'+type(error).__name__)
        elif record is not None:
            cache_hits+=1
        if record is None:
            history_gaps.append(ticker+':not_collected'); continue
        try:
            if aware(datetime.fromisoformat(record['retrieved_at']))>now:
                raise ValueError('future history record')
            parsed=parse_rotation_history(record['payload'],symbol=ticker+'.JK',sessions=sessions)
            price=dict(symbol=ticker,closes=parsed['closes'],basis=parsed['basis'],
                       version=record['record_sha256'],trading_eligible=True)
            prices[ticker]=price
            proofs[ticker]=_proof(price,available_at=datetime.fromisoformat(record['retrieved_at']),
                evidence=record['artifact_path'],method=parsed['eligibility_method'])
            actions.extend(dict(a,symbol=ticker,status='resolved',evidence=record['artifact_path']) for a in parsed['actions'])
        except (KeyError,ValueError,TypeError,OverflowError):
            history_gaps.append(ticker+':native_price_or_trading_evidence_unavailable')
    completed=aware(clock())
    if not now<=completed<=cutoff:
        return dict(manifest_written=False,reason='preparation_not_visible_at_cutoff',posts=False,
                    paid_requests=0,provider_fetches=transport.fetches-before)
    actions=sorted(actions,key=lambda a:a['identity'])
    evidence=cache/('actions-'+digest(dict(actions=actions,proofs=proofs))+'.json')
    write_once(evidence,canonical(dict(actions=actions,price_sources=proofs)).encode())
    numerical=dict(memberships={kind:jsonable(asdict(m)) for kind,m in memberships.items()},
        caps_by_basket=caps_by_basket,prices=prices,price_attestations=proofs,actions=actions,
        actions_attestation=_proof(actions,available_at=completed,evidence=str(evidence),
            method='native-requested-splits-dividends/ordinary-close-no-dividend-additions'))
    value=dict(version=1,provenance='live-retained',available_at=stamp(completed),
        publication_session=session.isoformat(),closing_session=sessions[-1].isoformat(),
        calendar_sha256=calendar.import_digest,membership_sha256=membership_key,numerical=numerical)
    identity=digest(value); write_once(cache/('rotation-'+identity+'.json'),canonical(value).encode())
    _replace(cache/'rotation-current.json',value)
    return dict(manifest_written=True,manifest_sha256=identity,posts=False,paid_requests=0,
        provider_fetches=transport.fetches-before,history_cache_hits=cache_hits,
        prices_verified=len(prices),symbols_required=len(price_symbols),cap_symbols_required=len(tickers),
        cap_baskets_verified=sum(len(v) for v in caps_by_basket.values()),
        gaps=sorted([*failures,*cap_gaps,*history_gaps]))


def retained_rotation(value, *, calendar, publication_session, cutoff, observed_at=None):
    """Accept only a matching producer window, never a preview or stale prices."""
    if (value.get('version')!=1 or value.get('provenance')!='live-retained'
            or aware(datetime.fromisoformat(value['available_at']))>min(cutoff,observed_at or cutoff)
            or value['calendar_sha256']!=calendar.import_digest
            or value['publication_session']!=publication_session.isoformat()
            or value['closing_session']!=calendar.last_sessions(publication_session,2)[0].isoformat()):
        raise ValueError('retained rotation window mismatch')
    return value['numerical']


def unsupported_sections(numerical):
    """Reflect partial coverage instead of equating a manifest with readiness."""
    result=[]
    for kind,label in [('sectors','sector_rotation'),('konglo','konglo_rotation')]:
        groups=numerical['memberships'][kind]['groups']
        caps=numerical['caps_by_basket'].get(kind,{})
        for name,members in groups.items():
            raw=caps.get(name)
            if raw is None or any(member not in raw['values'] for member in members):
                result.append(label);break
            total=sum(raw['values'][member] for member in members)
            eligible=sum(raw['values'][member] for member in members if member in numerical['prices'])
            if total<=0 or eligible/total<0.9:
                result.append(label);break
        if not groups:result.append(label)
    return result
