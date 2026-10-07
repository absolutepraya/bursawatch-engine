"""Verified BI/BPS page snapshots, immutable local cache and future releases.

Table extraction is fixture-validated, not a claim that current dynamic pages
expose these rows. Empty/changed structures fail unavailable without guessing.
"""
from datetime import date, datetime, time, timedelta
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from .calendar import aware
from .store import canonical, digest, stamp

PRIMARY_URLS = {
    'BPS': ('https://www.bps.go.id/id/arc',),
    'BI': ('https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/sp_2730825.aspx',
           'https://www.bi.go.id/id/publikasi/kalender/default.aspx',),
}
_MONTHS = dict(zip(('januari','februari','maret','april','mei','juni','juli','agustus','september','oktober','november','desember'),range(1,13)))


def _instant(value): return aware(datetime.fromisoformat(value.replace('Z','+00:00')))


def _official(authority,url):
    if authority not in PRIMARY_URLS or url not in PRIMARY_URLS[authority]:
        raise ValueError('reviewed primary calendar URL required')


def _write_once(path,raw):
    if path.is_symlink(): raise ValueError('calendar cache artifact cannot be a symlink')
    try:
        fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        if path.read_bytes() != raw: raise ValueError('immutable calendar cache conflict')
        return
    with os.fdopen(fd,'wb') as output: output.write(raw)


class SnapshotCache:
    """Content-addressed source bytes reused across daily verification snapshots."""
    def __init__(self,path: Path):
        self.path=Path(path)
        if self.path.is_symlink(): raise ValueError('calendar cache cannot be a symlink')
        self.path.mkdir(parents=True,exist_ok=True,mode=0o700)

    def put(self,*,authority,source_url,html,retrieved_at,verified_at,amendment,verified,decision_day=None):
        _official(authority,source_url)
        if type(html) is not str or len(html.encode()) > 2*1024*1024 or not amendment:
            raise ValueError('bounded identified calendar snapshot required')
        if type(verified) is not bool or decision_day not in (None,'last'):
            raise ValueError('explicit verification and decision structure required')
        retrieved,checked=_instant(retrieved_at),_instant(verified_at)
        if checked < retrieved: raise ValueError('verification precedes retrieval')
        raw=html.encode()
        source_digest=hashlib.sha256(raw).hexdigest()
        metadata=dict(authority=authority,source_url=source_url,source_digest=source_digest,
                      retrieved_at=stamp(retrieved),verified_at=stamp(checked),amendment=amendment,
                      verified=verified,decision_day=decision_day)
        identity=digest(metadata)
        _write_once(self.path/(source_digest+'.html'),raw)
        _write_once(self.path/(identity+'.json'),canonical(metadata).encode())
        return dict(metadata,html=html,snapshot_digest=identity)

    def get(self,identity):
        if type(identity) is not str or re.fullmatch('[0-9a-f]{64}',identity) is None:
            raise ValueError('calendar snapshot identity invalid')
        metadata=json.loads((self.path/(identity+'.json')).read_bytes())
        if digest(metadata) != identity: raise ValueError('calendar metadata integrity mismatch')
        raw=(self.path/(metadata['source_digest']+'.html')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata['source_digest']:
            raise ValueError('calendar bytes integrity mismatch')
        return dict(metadata,html=raw.decode(),snapshot_digest=identity)


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows=[]; self.row=None; self.cell=None; self.table_depth=0
    def handle_starttag(self,tag,attrs):
        if tag=='table': self.table_depth+=1
        if self.table_depth and tag=='tr': self.row=[]
        if self.row is not None and tag in ('td','th'): self.cell=[]
    def handle_data(self,data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())); self.cell=None
        if tag=='tr' and self.row is not None:
            self.rows.append(self.row); self.row=None
            if len(self.rows)>1000: raise ValueError('calendar row bound exceeded')
        if tag=='table': self.table_depth=max(0,self.table_depth-1)


def _date(value):
    try: return date.fromisoformat(value)
    except ValueError:
        match=re.fullmatch(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})',value)
        if match is None or match[2].casefold() not in _MONTHS:
            raise ValueError('unverified calendar date format')
        return date(int(match[3]),_MONTHS[match[2].casefold()],int(match[1]))


def _parse(snapshot,cutoff):
    _official(snapshot['authority'],snapshot['source_url'])
    metadata={k:v for k,v in snapshot.items() if k not in {'html','snapshot_digest'}}
    if digest(metadata)!=snapshot['snapshot_digest'] or hashlib.sha256(snapshot['html'].encode()).hexdigest()!=snapshot['source_digest']:
        raise ValueError('snapshot_integrity')
    checked,retrieved=_instant(snapshot['verified_at']),_instant(snapshot['retrieved_at'])
    if snapshot['verified'] is not True or not retrieved<=checked<=cutoff or cutoff-checked>timedelta(days=7):
        raise ValueError('snapshot_unverified_future_or_stale')
    parser=_Tables(); parser.feed(snapshot['html'])
    header=None; events=[]
    aliases={'tanggal':'date','jadwal':'date','kegiatan':'event','rilis':'event','agenda':'event',
             'indikator':'event','periode':'period','periode referensi':'period','waktu':'time',
             'id rilis':'id','revisi':'revision','cakupan':'scope','tanggal keputusan':'decision'}
    for cells in parser.rows:
        mapped=[aliases.get(c.casefold()) for c in cells]
        if 'date' in mapped and 'event' in mapped:
            header=mapped; continue
        if header is None or len(cells)!=len(header): continue
        fields={k:v for k,v in zip(header,cells) if k}
        label=fields.get('event','')
        if fields.get('scope','nasional').casefold()!='nasional': continue
        if not any(word in label.casefold() for word in ('inflasi','neraca perdagangan','ekspor','impor','pdb','pertumbuhan ekonomi','tenaga kerja','pengangguran','rdg','bi-rate','cadangan devisa')): continue
        value=fields['date']; decision=False
        parts=re.split(r'\s+s\.d\.\s+|\s+to\s+',value)
        if len(parts)==2:
            if snapshot['authority']!='BI' or snapshot['decision_day']!='last':
                raise ValueError('meeting_decision_day_unverified')
            start,end=map(_date,parts)
            if start>=end: raise ValueError('meeting_date_order')
            release=_date(fields['decision']) if fields.get('decision') else end
            if release!=end: raise ValueError('meeting_decision_date_conflict')
            decision=True
        else:
            if snapshot['authority']=='BI' and 'rdg' in label.casefold() and not fields.get('decision'):
                raise ValueError('meeting_start_is_not_verified_decision_day')
            release=_date(fields.get('decision') or value)
            decision=bool(fields.get('decision'))
        value=fields.get('time','')
        if value:
            match=re.fullmatch(r'(\d{2})[:.](\d{2})(?:\s+WIB)?',value)
            if not match: raise ValueError('calendar_time_unverified')
            event_time=time(int(match[1]),int(match[2]))
            scheduled=datetime.combine(release,event_time,tzinfo=ZoneInfo('Asia/Jakarta'))
        else:
            event_time=None; scheduled=None
        period=fields.get('period','') or 'periode belum diumumkan'
        identity=fields.get('id') or digest({'event':label.casefold(),'period':period.casefold()})
        revision=int(fields.get('revision','1') or '1')
        if revision<1: raise ValueError('invalid_calendar_revision')
        events.append(dict(event_id=snapshot['authority']+':'+identity,release_id=fields.get('id') or None,event=label,reference_period=period,
                           date=release.isoformat(),time_wib=event_time.strftime('%H:%M') if event_time else None,
                           scheduled_at=stamp(scheduled) if scheduled else None,decision_day=decision,revision=revision,
                           source=snapshot['authority'],source_url=snapshot['source_url'],
                           source_digest=snapshot['source_digest'],snapshot_digest=snapshot['snapshot_digest'],
                           retrieved_at=snapshot['retrieved_at'],verified_at=snapshot['verified_at'],amendment=snapshot['amendment']))
    if header is None: raise ValueError('calendar_dynamic_empty_or_unknown_structure')
    return events


def select_calendar_events(snapshots: list[dict],*,freeze_at: datetime) -> dict:
    cutoff=aware(freeze_at); latest={}; failures=[]
    if len(snapshots)>32: raise ValueError('calendar snapshot bound exceeded')
    for snapshot in snapshots:
        url=snapshot.get('source_url','unknown')
        if url not in latest or snapshot.get('verified_at','')>latest[url].get('verified_at',''):
            latest[url]=snapshot
    releases={}
    for url,snapshot in sorted(latest.items()):
        try:
            events=_parse(snapshot,cutoff)
            local={}
            for event in events:
                key=event['event_id']; old=local.get(key)
                if old is None or event['revision']>old['revision']: local[key]=event
                elif event['revision']==old['revision']:
                    if (event['date'],event['time_wib'])!=(old['date'],old['time_wib']):
                        raise ValueError('conflicting_calendar_dates')
                    labels=sorted(set(old['event'].split(' / ')+[event['event']]))
                    old['event']=' / '.join(labels)
                    periods=sorted(set(old['reference_period'].split(' / ')+[event['reference_period']]))
                    old['reference_period']=' / '.join(periods)
            for key,event in local.items():
                old=releases.get(key)
                if old is None or event['verified_at']>old['verified_at']: releases[key]=event
        except (ValueError,KeyError,TypeError):
            failures.append({'source_url':url,'reason':'verified_calendar_unavailable'})
    # Resolve amendments first, so a release moved into the past removes its old future date.
    # An unknown same-day time cannot be established as after the freeze.
    future=[e for e in releases.values() if (_instant(e['scheduled_at'])>cutoff if e['scheduled_at'] else date.fromisoformat(e['date'])>cutoff.astimezone(ZoneInfo('Asia/Jakarta')).date())]
    # Only an explicit shared release ID and matching schedule establish a joint
    # briefing. Similar labels or coincident times alone are not identity proof.
    joint={}
    for event in sorted(future,key=lambda e:e['event_id']):
        key=(event.get('release_id') or event['event_id'],event['date'],event['time_wib'])
        proof={k:event[k] for k in ('source','source_url','source_digest','snapshot_digest',
                                    'retrieved_at','verified_at','amendment','revision')}
        if key not in joint:
            joint[key]=dict(event,sources=[proof])
        else:
            old=joint[key]
            old['sources'].append(proof)
            for field in ('event','reference_period'):
                old[field]=' / '.join(sorted(set(old[field].split(' / ')+event[field].split(' / '))))
            old['source']=' / '.join(sorted({p['source'] for p in old['sources']}))
    events=sorted(joint.values(),key=lambda e:(e['date'],e['time_wib'] or '00:00',e['event_id']))[:3]
    return {'events':events,'unavailable':failures,'cutoff':stamp(cutoff),'snapshot_ids':[s.get('snapshot_digest') for _,s in sorted(latest.items())]}


def format_calendar_events(calendar: dict) -> str:
    def citations(event):
        sources=event.get('sources') or [event]
        return ' '.join(f"[{p['source']}]({p['source_url']})" for p in sources)
    return '\n'.join(f"{e['event']} ({e['reference_period']}) · {e['date']} · {e['time_wib']+' WIB' if e['time_wib'] else 'jam belum diumumkan'} · {citations(e)}" for e in calendar['events'])


def freeze_calendar_events(store,run_id,snapshots,*,lease,now):
    run=store.get_run(run_id)
    captured=store.get_frozen(run_id,'calendar_snapshots')
    if captured is None: captured=store.freeze(run_id,'calendar_snapshots',{'snapshots':snapshots,'cutoff':run.freeze_at},lease=lease,now=now)
    calendar=select_calendar_events(captured.payload['snapshots'],freeze_at=_instant(run.freeze_at))
    return store.freeze(run_id,'calendar_events',calendar,lease=lease,now=now,dependencies={'calendar_snapshots':captured.digest})
