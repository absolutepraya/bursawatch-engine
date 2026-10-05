"""Frozen publication text and six-block offline review Markdown, no delivery IO."""
from datetime import date, datetime
import math
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from .calendar import aware
from .economic_calendar import format_calendar_events
from .global_markets import format_global_rows
from .rendering import publication_label
from .rotation import select_groups

REVISION='bursawatch-text-v1'
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
    if (parsed.scheme not in ('https','http') or not parsed.netloc or parsed.username or parsed.password
            or re.search(r'[\s<>\[\]()]',value)):
        raise ValueError('bounded literal source URL required')
    return value


def _sources(values):
    seen=[]
    for value in values:
        if value and _url(value) not in seen:seen.append(value)
    return '(Sources: '+', '.join(f'<{value}>' for value in seen)+')' if seen else ''


def _fit(required,optional):
    required=[text for text in required if text]
    optional=list(optional)
    while True:
        text='\n\n'.join(required+optional)
        if _length(text)<=LIMIT:return text
        if not optional:raise MessageTooLong('required message facts and source links exceed 2000 characters')
        optional.pop()  # Whole paragraphs/highlights only, deterministic priority.


def _timing(publication_session,cutoff,target):
    zone=ZoneInfo('Asia/Jakarta');cutoff=aware(cutoff).astimezone(zone);target=aware(target).astimezone(zone)
    if (cutoff.date()!=publication_session or target.date()!=publication_session
            or (cutoff.hour,cutoff.minute,cutoff.second,cutoff.microsecond)!=(7,30,0,0)
            or (target.hour,target.minute,target.second,target.microsecond)!=(8,0,0,0)):
        raise ValueError('frozen publication 07:30 cutoff and 08:00 target required')
    return '**Cutoff data:** 07:30 WIB · **Target terbit:** 08:00 WIB'


def _provenance_urls(value):
    if isinstance(value,dict):
        for key,item in value.items():
            if key.endswith('url') and isinstance(item,str):yield item
            elif isinstance(item,(dict,list,tuple)):yield from _provenance_urls(item)
    elif isinstance(value,(list,tuple)):
        for item in value:yield from _provenance_urls(item)


def _rotation_text(groups,title,publication_session,timing,notices):
    groups=tuple(groups)
    selected=select_groups(groups,limit=3)
    required=[title+publication_label(publication_session),timing]
    if not groups:required.append('Data rotasi belum tersedia.')
    else:
        coverage=min(row.coverage for row in groups)
        excluded=sum(len(row.excluded) for row in groups)
        if coverage<1 or excluded:
            required.append(f'**Cakupan:** minimum {coverage:.1%} kapitalisasi awal; {excluded} pengecualian anggota basket.')
        required.append('**Basis:** ilustrasi historis, bobot cap snapshot tetap.')
        caps=sorted({aware(datetime.fromisoformat(row.provenance['cap_collected_at'])).astimezone(ZoneInfo('Asia/Jakarta')).strftime('%d/%m/%Y %H:%M WIB')
                     for row in groups if row.provenance.get('cap_collected_at')})
        if caps:
            effective=sorted({str(row.provenance['cap_effective_date']) for row in groups if row.provenance.get('cap_effective_date')})
            metadata='tanggal efektif '+', '.join(effective) if effective else 'tanggal efektif belum terverifikasi'
            required.append('**Cap dikumpulkan:** '+', '.join(caps)+' ('+metadata+').')
    required.append(_sources(url for row in groups for url in _provenance_urls(row.provenance)))
    highlights=[f"**{_escape(row.name)}:** {row.quadrant}. Kekuatan {row.x:+.2f} pp; Momentum {row.y:+.2f} pp." for row in selected]
    return _fit(required,highlights+list(notices))


def format_brief(*,publication_session: date,cutoff: datetime,target: datetime,
                 outlook: dict,globals: list[dict],calendar: dict,sectors,konglo,
                 logos=None,notices=None) -> tuple[str,str,str]:
    """Use structured frozen writer/quote/event fields exactly once.

    Required facts, all supporting source URLs and frozen time markers survive
    optional paragraph removal. Callers freeze the returned strings verbatim;
    late retries must never refresh their date, times, evidence or prose.
    """
    label=publication_label(publication_session);timing=_timing(publication_session,cutoff,target)
    notices=notices or {};logos=logos or {}
    # Missing/unrecognised provisioned markup falls back to the readable name.
    known={name:markup for name,markup in logos.items() if isinstance(markup,str) and re.fullmatch(r'<:[A-Za-z0-9_]+:[0-9]{15,22}>',markup)}
    required=['### 🌇 BURSAWATCH PAGI: '+label,timing]
    facts=[]
    for fact in outlook.get('market_facts',[]):
        if (type(fact) is not dict or set(fact)!={'label','value','unit'}
                or type(fact['value']) not in (int,float) or not math.isfinite(fact['value'])):
            raise ValueError('finite frozen market fact required')
        facts.append(f"**{_escape(fact['label'])}:** {fact['value']:g} {_escape(fact['unit'])}")
    required.extend(facts)
    required.append('**Pasar global**\n'+(format_global_rows(globals,logos=known) or 'Data belum tersedia.'))
    required.append('**Agenda Indonesia**\n'+(format_calendar_events(calendar) or 'Agenda terverifikasi belum tersedia.'))
    claims=outlook.get('claims',[])
    if len(claims)>3 or any(not all(isinstance(claim.get(key),str) and claim[key] for key in
                                  ('excerpt','publisher_id','source_url')) for claim in claims):
        raise ValueError('at most three structured attributed writer claims required')
    urls=[q.get('source_url') for q in globals]
    urls.extend(e['source_url'] for e in calendar.get('events',[]))
    urls.extend(e.get('source_url') for e in calendar.get('unavailable',[]))
    urls.extend(claim['source_url'] for claim in claims)
    required.append(_sources(urls))
    if outlook.get('mode')!='supported' or not claims:
        required.append('**Outlook IHSG:** bukti belum cukup untuk rangkuman pandangan sumber.')
    # Reconstruct attribution from the selected writer's structured fields,
    # preserving whole exact excerpts instead of trimming inside source claims.
    prose=['Menurut '+_escape(claim['publisher_id'])+': '+claim['excerpt'] for claim in claims]
    first=_fit(required,prose+list(notices.get('ihsg',[])))
    sector=_rotation_text(sectors,'### 🏭 ROTASI SEKTOR: ',publication_session,timing,notices.get('sectors',[]))
    conglomerate=_rotation_text(konglo,'### 🐉 ROTASI KONGLO: ',publication_session,timing,notices.get('konglo',[]))
    return first,sector,conglomerate


def attachment_caption(kind: str,publication_session: date) -> str:
    titles={'ihsg':'IDX Composite Index','sectors':'Rotasi Sektor','konglo':'Rotasi Konglo'}
    return titles[kind]+' | '+publication_label(publication_session)+' | Cutoff 07:30 WIB · Target 08:00 WIB'


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
