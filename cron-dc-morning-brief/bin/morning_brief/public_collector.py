"""Explicit no-post public-input collection into private retained artifacts.

This producer never spends Sectors/Chart-IMG credits, reads Discord credentials,
captures source evidence, invokes a writer, initializes run state or posts.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .calendar import SessionCalendar, aware
from .config import load_operator_config_data, timing_for
from .global_markets import WATCHLIST, parse_yahoo_chart
from .host import private_file
from .public_sources import yahoo_sessions, ihsg_benchmark
from .store import canonical, stamp
from .store import digest


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def write_once(path, raw):
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        if private_file(path) != raw:
            raise ValueError('retained source artifact conflict')
        return
    with os.fdopen(fd,'wb') as output:
        output.write(raw)


class YahooTransport:
    def __init__(self, source_cache):
        self.cache=Path(source_cache)
        self.fetches=0

    def get(self, name, granularity):
        symbol=WATCHLIST[name][0] if name in WATCHLIST else '^JKSE'
        if name not in WATCHLIST and name != 'IHSG' or granularity not in ('1d','60m'):
            raise ValueError('bounded public quote request required')
        history_range='1y' if name=='IHSG' and granularity=='1d' else '1mo'
        url=('https://query1.finance.yahoo.com/v8/finance/chart/'+quote(symbol,safe='')
            +'?interval='+granularity+'&range='+history_range+'&includePrePost=false&includeTradingPeriods=true')
        request=Request(url,headers={'User-Agent':'Bursawatch-Morning/1.0'})
        # One explicit shared source directory coordinates the producer's
        # concurrent requests and persists 429 cooldown across process restarts.
        if not self.cache.is_absolute() or self.cache.is_symlink() or self.cache.stat().st_mode & 0o077:
            raise ValueError('private shared Yahoo source cache required')
        fd=os.open(self.cache/'yahoo-http.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'r+b') as lock:
            details=os.fstat(lock.fileno())
            if not stat.S_ISREG(details.st_mode) or details.st_mode & 0o077:
                raise ValueError('private Yahoo lock required')
            fcntl.flock(lock,fcntl.LOCK_EX)
            policy=self.cache/'yahoo-rate-limit.json'
            now=datetime.now(timezone.utc)
            if policy.exists():
                not_before=aware(datetime.fromisoformat(json.loads(private_file(policy,max_bytes=2048))['not_before']))
                if now<not_before:
                    raise ValueError('Yahoo source cooldown active')
            self.fetches+=1
            try:
                with build_opener(NoRedirect()).open(request,timeout=5) as response:
                    raw=response.read(2_000_001)
            except HTTPError as error:
                try:
                    if error.code==429:
                        observed=datetime.now(timezone.utc)
                        not_before=observed+timedelta(hours=24)
                        header=error.headers.get('Retry-After','')[:256]
                        try:
                            if header.isdecimal():
                                not_before=observed+timedelta(seconds=max(60,int(header)))
                            elif header:
                                not_before=max(observed+timedelta(seconds=60),aware(parsedate_to_datetime(header)))
                        except (ValueError,TypeError,OverflowError):
                            pass
                        raw_policy=canonical({'observed_at':stamp(observed),'not_before':stamp(not_before)}).encode()
                        with tempfile.NamedTemporaryFile(dir=self.cache,delete=False) as temporary:
                            temporary.write(raw_policy)
                            temporary_path=Path(temporary.name)
                        os.replace(temporary_path,policy)
                finally:
                    error.close()
                raise
        if len(raw)>2_000_000:
            raise ValueError('public quote response exceeds bound')
        return {'source_url':url,'retrieved_at':stamp(datetime.now(timezone.utc)),
                'source_sha256':hashlib.sha256(raw).hexdigest(),'payload':json.loads(raw)}


def collect_public(config, *, snapshot, calendar_path, source_cache, now, transport=None, clock=None,
                   economic_snapshots=()):
    """Collect actual snapshots for the next configured, verified IDX freeze.

    Collected data after today's freeze is for a future session, never a current
    backfill. A later natural preparation can refresh the current manifest;
    content-addressed old sources and frozen publications remain unchanged.
    """
    from control_plane_client import ConfigSnapshot
    checked=ConfigSnapshot.from_payload(snapshot)
    if checked.watcher_id != 'bursawatch-dc-morning-brief':
        raise ValueError('morning configuration identity mismatch')
    settings=load_operator_config_data(checked.config); now=aware(now)
    if type(economic_snapshots) not in (list,tuple) or len(economic_snapshots)>32:
        raise ValueError('bounded explicit economic snapshots required')
    raw_calendar=private_file(calendar_path,max_bytes=512_000); p=json.loads(raw_calendar)
    calendar=SessionCalendar.from_file(calendar_path,expected_version=p['version'],
        expected_amendment=p['amendment'],as_of=now)
    if calendar.import_digest != hashlib.sha256(raw_calendar).hexdigest():
        raise ValueError('calendar changed during collection')
    candidates=[day for day in calendar.sessions if timing_for(day,settings)['cutoff']>now]
    if not candidates:
        raise ValueError('verified upcoming publication session unavailable')
    session=candidates[0]; cutoff=timing_for(session,settings)['cutoff']
    # A future freeze must still be inside the calendar's amendment check policy.
    SessionCalendar.from_file(calendar_path,expected_version=p['version'],
        expected_amendment=p['amendment'],as_of=cutoff)
    cache=Path(source_cache)
    if not cache.is_absolute() or cache.is_symlink():
        raise ValueError('explicit private source cache required')
    cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    if cache.stat().st_mode & 0o077:
        raise ValueError('private source cache required')
    transport=transport or YahooTransport(cache); clock=clock or (lambda:datetime.now(timezone.utc))
    fetches_before=getattr(transport,'fetches',0)
    records={}; failures=[]
    # Reuse only history that already passed the full chart/completed-close
    # gate for this same final session. Never cache a still-open daily bar as a
    # final close. Retain original retrieval and provenance on every reuse.
    try:
        from .yahoo_chart import prepare_chart
        retained=json.loads(private_file(config.input_manifest))
        candidate={**retained['chart'],'cutoff':stamp(cutoff)}
        if aware(datetime.fromisoformat(candidate['daily']['retrieved_at']))>now:
            raise ValueError('future retained history')
        prepare_chart(candidate,calendar,publication_session=session,cutoff=cutoff)
        records[('IHSG','1d')]=candidate['daily']
    except (OSError,ValueError,KeyError,TypeError,OverflowError):
        pass
    requests=[(name,interval) for name in ['IHSG',*settings['instruments']] for interval in ('1d','60m')]
    requests=[key for key in requests if key not in records]
    # Fourteen bounded requests maximum, no retries or alternate source routes.
    with ThreadPoolExecutor(max_workers=3) as pool:
        work={pool.submit(transport.get,name,interval):(name,interval) for name,interval in requests}
        for future in as_completed(work):
            key=work[future]
            try:
                record=future.result(); observed=aware(datetime.fromisoformat(record['retrieved_at']))
                if observed>cutoff:
                    raise ValueError('source response arrived after freeze')
                record={**record,'retrieved_at':stamp(observed)}
                encoded=canonical(record).encode(); identity=hashlib.sha256(encoded).hexdigest()
                write_once(cache/(identity+'.json'),encoded)
                records[key]=dict(record,artifact_path=str(cache/(identity+'.json')))
            except Exception as error:
                failures.append(key[0]+':'+key[1]+':'+type(error).__name__)
    globals=[]; numerical={}; chart=None
    for name in ['IHSG',*settings['instruments']]:
        try:
            daily,hourly=records[(name,'1d')],records[(name,'60m')]
            proof=yahoo_sessions(name,hourly['payload'],
                retrieved_at=datetime.fromisoformat(hourly['retrieved_at']),cutoff=cutoff)
            proof['evidence_ref']=hourly['artifact_path']
            if name=='IHSG':
                numerical=ihsg_benchmark(daily['payload'],proof,calendar,publication_session=session,
                    retrieved_at=datetime.fromisoformat(daily['retrieved_at']),cutoff=cutoff)
                try:
                    from .yahoo_chart import prepare_chart, PROFILE
                    candidate=dict(provider='yahoo',profile_revision=PROFILE,cutoff=stamp(cutoff),
                        daily={**daily,'payload_sha256':digest(daily['payload'])},sessions=proof)
                    prepare_chart(candidate,calendar,publication_session=session,cutoff=cutoff)
                    chart=candidate
                except (KeyError,ValueError,TypeError,OverflowError) as error:
                    failures.append('IHSG:chart:'+type(error).__name__)
            else:
                globals.append(dict(name=name,payload=daily['payload'],retrieved_at=daily['retrieved_at'],sessions=proof))
                checked_quote=parse_yahoo_chart(name,daily['payload'],freeze_at=cutoff,
                    retrieved_at=datetime.fromisoformat(daily['retrieved_at']),sessions=proof)
                if checked_quote['status']!='available':
                    failures.append(name+':quote:'+(checked_quote.get('reason') or checked_quote['status']))
        except (KeyError,ValueError,TypeError,OverflowError) as error:
            failures.append(name+':verification:'+type(error).__name__)
            if name!='IHSG':
                # Preserve a visible unavailable row for every configured market.
                globals.append(dict(name=name,payload={},retrieved_at=stamp(now),sessions={'verified':False}))
    result={'session':session.isoformat(),'cutoff':stamp(cutoff),'provider_fetches':getattr(transport,'fetches',fetches_before+len(requests))-fetches_before,
            'history_cache_hits':int(('IHSG','1d') not in requests),
            'posts':False,'paid_requests':0,'gaps':sorted(failures),'manifest_written':False}
    if not numerical:
        return result
    completed=aware(clock())
    if not now <= completed <= cutoff or any(datetime.fromisoformat(r['retrieved_at'])>completed for r in records.values()):
        return dict(result,gaps=sorted([*failures,'preparation_not_visible_at_cutoff']))
    value=dict(version=1,provenance='live-retained',
        available_at=stamp(completed),
        calendar={'path':str(Path(calendar_path).resolve()),'version':calendar.version,
                  'amendment':calendar.amendment,'sha256':calendar.import_digest},
        numerical=numerical,global_inputs=globals,calendar_snapshots=list(economic_snapshots))
    if chart is not None:
        value['chart']=chart
    # Each version is immutable; only this private pointer can advance before a
    # freeze. The dispatcher restores its frozen upstream after preparation.
    encoded=canonical(value).encode(); identity=hashlib.sha256(encoded).hexdigest()
    write_once(cache/('manifest-'+identity+'.json'),encoded)
    target=Path(config.input_manifest)
    if target.is_symlink():
        raise ValueError('live input manifest cannot be a symlink')
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=target.with_name(target.name+'.'+identity+'.tmp')
    write_once(temporary,encoded)
    os.replace(temporary,target)
    return dict(result,manifest_written=True,manifest_sha256=identity,
                incomplete_sections=['economic_calendar','sector_rotation','konglo_rotation']+([] if chart else ['ihsg_chart']))
