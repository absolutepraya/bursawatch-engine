"""Frozen publication text and six-block offline review Markdown, no delivery IO."""
from datetime import date, datetime
import math
import re
from urllib.parse import urlsplit, urlunsplit, quote
from zoneinfo import ZoneInfo
from .calendar import aware
from .economic_calendar import format_calendar_events
from .global_markets import format_global_rows
from .rendering import publication_label
from .rotation import select_groups

REVISION='bursawatch-text-v3'
LIMIT=2000


class MessageTooLong(ValueError):
    """Required identity, facts and sources cannot fit; never clip a source URL."""


def _length(value):
    # Conservative for Discord's UTF-16 clients, including astral emoji glyphs.
    return len(value.encode('utf-16-le'))//2


def _escape(value):
    return re.sub(r'([\\\[\]()*_`])',r'\\\1',str(value))


def _url(value):
    if not isinstance(value,str):raise ValueError('source URL required')
    parsed=urlsplit(value)
    if (parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password
            or re.search(r'[\s<>]',value)):
        raise ValueError('bounded literal source URL required')
    safe=":/?#@!$&'*,;=+-._~%"
    return urlunsplit((parsed.scheme,parsed.netloc,quote(parsed.path,safe=safe),
                       quote(parsed.query,safe=safe),quote(parsed.fragment,safe=safe)))


def _sources(values):
    seen=[]
    for value in values:
        if value:
            rendered=_url(value)
            if rendered not in seen:seen.append(rendered)
    return '(Sources: '+', '.join(f'<{value}>' for value in seen)+')' if seen else ''


def _fit(required,optional):
    required=[text for text in required if text]
    optional=list(optional)
    while True:
        text='\n\n'.join(required+optional)
        if _length(text)<=LIMIT:return text
        if not optional:raise MessageTooLong('required message facts and source links exceed 2000 characters')
        optional.pop()  # Whole paragraphs/highlights only, deterministic priority.


def _validate_timing(publication_session,cutoff,target):
    zone=ZoneInfo('Asia/Jakarta');cutoff=aware(cutoff).astimezone(zone);target=aware(target).astimezone(zone)
    if (cutoff.date()!=publication_session or target.date()!=publication_session or cutoff>=target
            or cutoff.second or cutoff.microsecond or target.second or target.microsecond):
        raise ValueError('same-session minute-aligned cutoff before publication target required')


def _provenance_urls(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key.endswith('url') and isinstance(item,str):yield item
            elif isinstance(item,(dict,list,tuple)):yield from _provenance_urls(item)
    elif isinstance(value,(list,tuple)):
        for item in value:yield from _provenance_urls(item)


def _rotation_text(groups,title,publication_session,notices):
    groups=tuple(groups)
    selected=select_groups(groups,limit=3)
    required=[title+publication_label(publication_session)]
    if not groups:required.append('Data rotasi belum tersedia.')
    else:
        coverage=min(row.coverage for row in groups)
        excluded=sum(len(row.excluded) for row in groups)
        if coverage<1 or excluded:
            unknown=sum(len(row.provenance.get('missing_cap_members',())) for row in groups)
            required.append(f'**Basket parsial:** cakupan minimum {coverage:.1%} cap diketahui; {excluded} pengecualian anggota, termasuk {unknown} cap tidak tersedia.')
        if any(row.provenance.get('cap_collection_status')=='stale' for row in groups):
            required.append('**Snapshot cap lama (stale):** pembaruan belum berhasil; tanggal pengumpulan asli dipertahankan.')
        required.append('**Basis:** ilustrasi historis, bobot cap snapshot tetap.')
        caps=sorted({aware(datetime.fromisoformat(row.provenance['cap_collected_at'])).astimezone(ZoneInfo('Asia/Jakarta')).strftime('%d/%m/%Y %H:%M WIB')
                     for row in groups if row.provenance.get('cap_collected_at')})
        if caps:
            effective=sorted({str(row.provenance['cap_effective_date']) for row in groups if row.provenance.get('cap_effective_date')})
            metadata='tanggal efektif '+', '.join(effective) if effective else 'tanggal efektif belum terverifikasi'
            required.append('**Cap dikumpulkan:** '+', '.join(caps)+' ('+metadata+').')
    try: required.append(_sources(url for row in groups for url in _provenance_urls(row.provenance)))
    except ValueError:
        return _fit(required[:1]+['Data rotasi belum tersedia: sumber tidak dapat ditampilkan dengan aman.'],[])
    highlights=[f"**{_escape(row.name)}:** {row.quadrant}. Kekuatan {row.x:+.2f} pp; Momentum {row.y:+.2f} pp." for row in selected]
    try: return _fit(required,highlights+list(notices))
    except MessageTooLong:
        return _fit(required[:1]+['Data rotasi belum tersedia: rincian sumber melebihi batas pesan.'],[])


def _scenario_block(scenario):
    """One atomic source-attributed core, including roles and optional pulse."""
    if not isinstance(scenario,dict) or not scenario.get('base_case') or not scenario.get('change_conditions'):
        raise ValueError('complete selected scenario required')
    roles={};rows={}
    def add(role,items):
        for row in items:
            identity=row['evidence_id']
            if identity in rows and rows[identity]!=row: raise ValueError('inconsistent source context')
            rows[identity]=row;roles.setdefault(identity,[])
            if role not in roles[identity]: roles[identity].append(role)
    add('Kasus dasar',[scenario['base_case']])
    add('Pendukung',scenario['supporting'])
    add('Penentang',scenario['opposing'])
    add('Kondisi perubahan',scenario['change_conditions'])
    pulse=scenario['pulse']
    add('narasi optimistis',pulse['optimistic'])
    add('narasi hati-hati',pulse['cautious'])
    blocks=['**Skenario IHSG** (asesmen model atas pandangan sumber)']
    for identity,row in rows.items():
        published=aware(datetime.fromisoformat(row['published_at'])).astimezone(ZoneInfo('Asia/Jakarta'))
        blocks.append('**'+'; '.join(roles[identity])+':** Menurut '+_escape(row['publisher_id'])+
            f' · {published:%d/%m %H:%M} WIB: '+row['excerpt']+' '+_sources([row['source_url']]))
    if not scenario['supporting']: blocks.append('Pendukung belum tersedia.')
    if not scenario['opposing']: blocks.append('Penentang belum tersedia.')
    blocks.extend(scenario['limitations'])
    if pulse['mode']!='absent':
        heading='Pandangan satu sumber' if pulse['mode']=='single_source' else 'Narasi sumber terkumpul'
        blocks.append('**'+heading+'** (peran narasi dinilai model, bukan konsensus).')
        if not pulse['optimistic']: blocks.append('Narasi optimistis belum tersedia.')
        if not pulse['cautious']: blocks.append('Narasi hati-hati belum tersedia.')
    return '\n\n'.join(blocks)


def format_brief(*,publication_session: date,cutoff: datetime,target: datetime,
                 outlook: dict,globals: list[dict],calendar: dict,sectors,konglo,
                 logos=None,notices=None,with_selection=False):
    """Use structured frozen writer/quote/event fields exactly once.

    Frozen identity/time markers survive optional whole-block removal.
    Each source claim or scenario is trimmed atomically with its citations.
    Callers freeze the returned strings verbatim;
    late retries must never refresh their date, times, evidence or prose.
    """
    label=publication_label(publication_session);_validate_timing(publication_session,cutoff,target)
    notices=notices or {};logos=logos or {}
    # Missing/unrecognised provisioned markup falls back to the readable name.
    known={name:markup for name,markup in logos.items() if isinstance(markup,str) and re.fullmatch(r'<:[A-Za-z0-9_]+:[0-9]{15,22}>',markup)}
    required=['### 🌇 BURSAWATCH PAGI: '+label]
    facts=[]
    for fact in outlook.get('market_facts',[]):
        if (type(fact) is not dict or set(fact)!={'label','value','unit'}
                or not isinstance(fact.get('label'),str) or not isinstance(fact.get('unit'),str)
                or type(fact['value']) not in (int,float) or not math.isfinite(fact['value'])):
            continue
        facts.append(f"**{_escape(fact['label'])}:** {fact['value']:g} {_escape(fact['unit'])}")
    # Each optional section keeps its supporting citations in the same block.
    # Unrenderable optional inputs never poison an already frozen session.
    available=[]
    global_rows=[];global_driver=False
    for row in globals:
        try:
            global_rows.append(format_global_rows([row],logos=known)+' '+_sources([row.get('source_url')]))
            if row.get('status')=='available' and row.get('source_url'): global_driver=True
        except (ValueError,KeyError,TypeError): pass
    global_block='**Pasar global**\n'+('\n'.join(global_rows) or 'Data belum tersedia.')
    calendar_rows=[]
    for event in calendar.get('events',[]):
        try:
            normalized={**event,'source_url':_url(event['source_url'])}
            if event.get('sources'):
                normalized['sources']=[{**p,'source_url':_url(p['source_url'])} for p in event['sources']]
            calendar_rows.append(format_calendar_events({'events':[normalized]}))
        except (ValueError,KeyError,TypeError): pass
    unavailable=[]
    for event in calendar.get('unavailable',[]):
        try: unavailable.append(_sources([event.get('source_url')]))
        except ValueError: pass
    calendar_block='**Agenda Ekonomi Indonesia**\n'+('\n'.join(calendar_rows) or 'Agenda terverifikasi belum tersedia.')
    if unavailable: calendar_block+=' '+ ' '.join(unavailable)
    scenario=outlook.get('scenario')
    scenario_block=None
    if outlook.get('mode')=='supported' and scenario is not None:
        try: scenario_block=_scenario_block(scenario)
        except (ValueError,KeyError,TypeError): pass
    claims=outlook.get('claims',[]) if scenario is None else []
    prose=[];prose_claims=[]
    if isinstance(claims,list) and len(claims)<=3:
        for claim in claims:
            try:
                if any(not isinstance(claim.get(key),str) or not claim[key] for key in
                       ('excerpt','publisher_id','source_url')): continue
                prose_claims.append(claim)
                prose.append('Menurut '+_escape(claim['publisher_id'])+': '+claim.get('context',claim['excerpt'])+' '+_sources([claim['source_url']]))
            except (ValueError,TypeError): pass
    limitation='**Outlook IHSG:** bukti belum cukup untuk rangkuman pandangan sumber.'
    # Reserve a truthful limitation before adding whole optional paragraphs.
    required.append(limitation)
    for block in facts+[global_block,calendar_block]+([scenario_block] if scenario_block else [])+prose+list(notices.get('ihsg',[])):
        if block==scenario_block and not (
                (global_block in available and global_driver)
                or (calendar_block in available and calendar_rows)):
            continue
        if _length('\n\n'.join(required+available+[block]))<=LIMIT:
            available.append(block)
    displayed_claim=any(block in available for block in prose)
    supported=outlook.get('mode')=='supported' and (displayed_claim or (scenario_block is not None and scenario_block in available))
    if supported:
        required.remove(limitation)
        if scenario_block is not None:
            available.remove(scenario_block)
            available.insert(sum(block in available for block in facts),scenario_block)
    if global_block not in available:
        available.append('**Pasar global**\nData belum tersedia.')
    if calendar_block not in available:
        available.append('**Agenda Ekonomi Indonesia**\nAgenda terverifikasi belum tersedia.')
    first=_fit(required,available)

    sector=_rotation_text(sectors,'### 🏭 ROTASI SEKTOR: ',publication_session,notices.get('sectors',[]))
    conglomerate=_rotation_text(konglo,'### 🐉 ROTASI KONGLO: ',publication_session,notices.get('konglo',[]))
    texts=(first,sector,conglomerate)
    if not with_selection: return texts
    selected={**outlook,'mode':'supported' if supported else 'facts_only',
              'reason':outlook.get('reason') if supported or outlook.get('mode')!='supported' else 'formatting_unavailable',
              'scenario':scenario if supported else None,
              'claims':[claim for claim,block in zip(prose_claims,prose) if block in available] if supported else [],'text':first}
    return texts,selected


def attachment_caption(kind: str,publication_session: date, *, cutoff=None, target=None) -> str:
    titles={'ihsg':'IDX Composite Index','sectors':'Rotasi Sektor','konglo':'Rotasi Konglo'}
    if cutoff is None and target is None:
        timing='Cutoff 07:30 WIB · Target 08:00 WIB'  # Historical local artifacts.
    else:
        _validate_timing(publication_session,cutoff,target)
        zone=ZoneInfo('Asia/Jakarta')
        timing=f'Cutoff {cutoff.astimezone(zone):%H:%M} WIB · Target {target.astimezone(zone):%H:%M} WIB'
    return titles[kind]+' | '+publication_label(publication_session)+' | '+timing


def six_block_markdown(texts,images) -> str:
    """Three text blocks alternating with explicit attachments or omissions.

    images is exactly three None or {title,path} dictionaries, not a request to
    fetch image paths. Publisher attachment bytes/manifests remain caller-owned.
    """
    if len(texts)!=3 or len(images)!=3 or any(_length(t)>LIMIT for t in texts):
        raise ValueError('three bounded text and image slots required')
    blocks=[]
    for text,image in zip(texts,images):
        if '\n\n---\n\n' in text:raise ValueError('reserved review separator in publication text')
        blocks.append(text.replace('\n','  \n'))
        if image is None:blocks.append('Gambar: gambar tidak tersedia.')
        else:
            if set(image)!={'title','path'} or not image['title'] or re.search(r'[\r\n()\[\]]',image['path']):
                raise ValueError('explicit local attachment title/path required')
            blocks.append(f"![{_escape(image['title'])}]({image['path']})")
    return '\n\n---\n\n'.join(blocks)+'\n'
