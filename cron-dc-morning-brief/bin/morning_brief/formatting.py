"""Frozen publication text and six-block offline review Markdown, no delivery IO."""
from datetime import date, datetime
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, quote
from zoneinfo import ZoneInfo
from .calendar import aware
from .economic_calendar import format_calendar_events
from .global_markets import format_global_rows
from .rendering import publication_label

# Use the existing stock-card tracker, without its Yahoo fetching surface.
_news_bin = Path(__file__).resolve().parents[3] / 'lib-news-format' / 'bin'
if str(_news_bin) not in sys.path:
    sys.path.insert(0, str(_news_bin))
from news_format import market_block

REVISION='bursawatch-text-v4'
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


def _rotation_text(title,publication_session):
    """Heading only. Coverage, basis and cap details stay in the frozen manifest."""
    return title+publication_label(publication_session)


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


def _outlook_paragraph(outlook):
    """Retain exact conditional source context, with attribution but no links."""
    if outlook.get('mode') != 'supported':
        return '-', None, []
    scenario = outlook.get('scenario')
    if scenario is not None:
        # Preserve the existing consistency/role validation used by the writer.
        _scenario_block(scenario)
        rows = [scenario['base_case'], *scenario['supporting'], *scenario['opposing'],
                *scenario['change_conditions']]
    else:
        rows = outlook.get('claims', [])
    seen = set(); rendered = []; shown = []
    for row in rows:
        identity = row.get('evidence_id') or (row.get('publisher_id'), row.get('excerpt'))
        if identity in seen:
            continue
        seen.add(identity)
        excerpt = row.get('context', row.get('excerpt'))
        if not isinstance(excerpt, str) or not excerpt.strip() or not row.get('publisher_id'):
            raise ValueError('complete attributed paragraph required')
        _url(row['source_url'])  # Provenance stays validated and retained privately.
        excerpt = ' '.join(excerpt.split()).replace('·', ',')
        rendered.append('Menurut '+_escape(row['publisher_id'])+': '+excerpt)
        shown.append(row)
    if not rendered:
        return '-', None, []
    displayed_scenario = ({**scenario, 'pulse':{'mode':'absent','optimistic':[],'cautious':[]},
                           'limitations':[]} if scenario is not None else None)
    return ' '.join(rendered), displayed_scenario, shown if scenario is None else []


def _agenda_block(calendar):
    rows = []; sources = []
    for event in calendar.get('events', [])[:3]:
        try:
            label = _escape(event['event']).replace('·', ',')
            when = date.fromisoformat(event['date']).strftime('%a, %d %b %Y')
            citations = event.get('sources') or [event]
            links = []
            for source in citations:
                link = '['+_escape(source['source'])+']('+_url(source['source_url'])+')'
                if link not in links: links.append(link)
            if not links:
                raise ValueError('agenda source required')
            row = '* '+label+' - '+when
            # Keep names and source links atomic. One malformed/oversized event
            # cannot hide the other agenda entries or overflow the main message.
            if _length(row+' '.join(links)) > 350:
                continue
            rows.append(row)
            for link in links:
                if link not in sources: sources.append(link)
        except (ValueError, KeyError, TypeError):
            continue
    citations = ' '.join('\\['+link+'\\]' for link in sources)
    title = 'Agenda Ekonomi Indonesia'+(' '+citations if citations else '')+':'
    return title+'\n'+('\n'.join(rows) or '-')


def format_brief(*,publication_session: date,cutoff: datetime,target: datetime,
                 outlook: dict,globals: list[dict],calendar: dict,sectors,konglo,
                 logos=None,notices=None,ihsg_tracker=None,with_selection=False):
    """Compact public layout; audit sources and session metadata stay frozen."""
    _validate_timing(publication_session,cutoff,target)
    logos=logos or {};notices=notices or {}
    known={name:markup for name,markup in logos.items() if isinstance(markup,str)
           and re.fullmatch(r'<:[A-Za-z0-9_]+:[0-9]{15,22}>',markup)}
    tracker=dict(ihsg_tracker or {})
    if not ihsg_tracker:
        for fact in outlook.get('market_facts', []):
            if (isinstance(fact,dict) and str(fact.get('label','')).startswith('IHSG')
                    and type(fact.get('value')) in (int,float)
                    and math.isfinite(fact['value']) and fact['value']>0):
                tracker['latest_price']=fact['value'];break
    close_block=market_block(tracker, 'IDR', price_label='Penutupan IHSG terakhir', missing_marker=False)
    quotes=[]
    for row in globals:
        try:
            quotes.append(format_global_rows([row],logos=known))
        except (ValueError, KeyError, TypeError):
            if row.get('name') in ('KOSPI','Nikkei','SPY','QQQ','EIDO','USDIDR'):
                quotes.append(format_global_rows([dict(name=row['name'],status='unavailable')],logos=known))
    global_block='Pasar global:\n'+('\n'.join(quotes) or '-')
    agenda=_agenda_block(calendar)
    try:
        paragraph,scenario,claims=_outlook_paragraph(outlook)
    except (ValueError, KeyError, TypeError):
        paragraph,scenario,claims='-',None,[]
    header='### 🌇 BURSAWATCH PAGI: '+publication_label(publication_session)
    def assemble(prose):
        return '\n\n'.join((header,close_block,'Outlook IHSG:\n'+prose,global_block,agenda))
    first=assemble(paragraph)
    if _length(first)>LIMIT:
        paragraph,scenario,claims='-',None,[]
        first=assemble(paragraph)
    if _length(first)>LIMIT:
        raise MessageTooLong('bounded tracker, markets and agenda exceed message limit')
    texts=(first,
           _rotation_text('### 🏭 ROTASI SEKTOR: ',publication_session),
           _rotation_text('### 🐉 ROTASI KONGLO: ',publication_session))
    if not with_selection:
        return texts
    supported=paragraph!='-'
    presentation={**outlook,'mode':'supported' if supported else 'facts_only',
                  'reason':outlook.get('reason') if supported or outlook.get('mode')!='supported' else 'formatting_unavailable',
                  'scenario':scenario,'claims':claims,'text':first}
    return texts,presentation


def attachment_caption(kind: str,publication_session: date, *, cutoff=None, target=None) -> str:
    if cutoff is not None or target is not None:
        _validate_timing(publication_session,cutoff,target)
    # Offline alt text only. Discord image messages carry no content.
    return {'ihsg':'IDX Composite Index','sectors':'Rotasi Sektor','konglo':'Rotasi Konglo'}[kind]


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
