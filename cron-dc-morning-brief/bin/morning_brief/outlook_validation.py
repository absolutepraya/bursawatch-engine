"""Pure source-grounding and scenario consistency rules, independent of layout."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re
from urllib.parse import urlsplit, urlunsplit, quote

from .calendar import aware


@dataclass(frozen=True)
class ScenarioSource:
    context: dict
    roles: tuple[str, ...]
    published_at: datetime
    url: str


@dataclass(frozen=True)
class ValidatedScenario:
    value: dict
    sources: tuple[ScenarioSource, ...]


@dataclass(frozen=True)
class ValidatedOutlook:
    claims: list[dict]
    scenario: ValidatedScenario


def source_url(value):
    """Validate a literal provenance URL and return its safe encoded form."""
    if not isinstance(value,str):raise ValueError('source URL required')
    parsed=urlsplit(value)
    if (parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password
            or re.search(r'[\s<>]',value)):
        raise ValueError('bounded literal source URL required')
    safe=":/?#@!$&'*,;=+-._~%"
    return urlunsplit((parsed.scheme,parsed.netloc,quote(parsed.path,safe=safe),
                       quote(parsed.query,safe=safe),quote(parsed.fragment,safe=safe)))


_PROBABILITY_WORD=re.compile(r'\b(?:probabilitas|probability)\b',re.I)
_LIKELIHOOD_WORD=re.compile(r'\b(?:peluang|berpeluang)\b',re.I)
_PERCENT=re.compile(r'\d+(?:[.,]\d+)?\s*(?:%|persen\b|percent\b)',re.I)


def states_probability(text):
    """True for a numeric probability claim, never for an index level beside "berpeluang".

    Judged per sentence, so a long qualifier cannot hide the number. A sentence states a
    probability when it has the word probabilitas/probability and any number, or the word
    peluang/berpeluang and a percentage. "berpeluang menguji 6.280" is a view about a level.
    """
    for sentence in re.split(r'(?<=[.!?])\s+',text):
        if _PROBABILITY_WORD.search(sentence) and re.search(r'\d',sentence):
            return True
        if _LIKELIHOOD_WORD.search(sentence) and _PERCENT.search(sentence):
            return True
    return False


def _claims(response,payload):
    if type(response) is not dict or set(response)!={'claims','scenario'} or type(response['claims']) is not list or not 0<=len(response['claims'])<=3:
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
        # Forbidden numerical probabilities remain forbidden across source wraps.
        if states_probability(row['text']):
            raise ValueError('calibrated probability is outside writer contract')
        if (identity,excerpt) in seen: raise ValueError('duplicate claim')
        seen.add((identity,excerpt))
        # No freeform inference is accepted. The source owns the quoted statement.
        source_url(row['source_url'])
        if not isinstance(row['publisher_id'],str):
            raise ValueError('claim publisher required')
        context=row['text'].strip()
        if len(context)>600: raise ValueError('complete context exceeds writer bound')
        claims.append(dict(evidence_id=identity,excerpt=excerpt,publisher_id=row['publisher_id'],
                           source_url=row['source_url'],context=context))
    return claims


def _scenario(response,payload):
    """Validate attribution and complete context, not a source's truth or stance."""
    value=response['scenario']
    if type(value) is not dict or set(value)!={'base_case','supporting','opposing','change_conditions','pulse'}:
        raise ValueError('complete structured scenario required')
    rows={row['evidence_id']:row for row in payload['evidence']['items']}
    seen=set()
    def ref(raw,conditional=False):
        if type(raw) is not dict or set(raw)!={'evidence_id','excerpt'}:
            raise ValueError('exact source reference required')
        identity,text=raw['evidence_id'],raw['excerpt']
        if type(identity) is not str or identity not in rows or type(text) is not str:
            raise ValueError('unknown source reference')
        row=rows[identity]
        if row.get('text_truncated') or not 1<=len(text)<=600 or text!=row['text'].strip():
            raise ValueError('full untruncated source context required')
        if states_probability(text):
            raise ValueError('numerical probability forbidden')
        if conditional and not re.search(r'\b(?:jika|bila|apabila|selama|asalkan|if|unless|provided)\b',text,re.I):
            raise ValueError('sourced conditional language required')
        source_url(row['source_url'])
        lower=aware(datetime.fromisoformat(payload['evidence']['previous_cutoff']))
        cutoff=aware(datetime.fromisoformat(payload['cutoff']))
        if not (lower<=aware(datetime.fromisoformat(row['published_at']))<=cutoff
                and aware(datetime.fromisoformat(row['accepted_at']))<=cutoff):
            raise ValueError('fresh cutoff-visible source required')
        seen.add(identity)
        return {key:row[key] for key in ('evidence_id','version_ref','evidence_hash','publisher_id','origin_status',
                    'source_url','published_at','accepted_at')} | {'excerpt':text,'role_provenance':'model_assessed'}
    def refs(raw,required=False,conditional=False):
        if type(raw) is not list or not (int(required)<=len(raw)<=3):
            raise ValueError('bounded source references required')
        result=[ref(item,conditional) for item in raw]
        if len({item['evidence_id'] for item in result})!=len(result): raise ValueError('duplicate role source')
        return result
    result={'assessment':'model_assigned_source_roles','base_case':ref(value['base_case'],True),
            'supporting':refs(value['supporting']),'opposing':refs(value['opposing']),
            'change_conditions':refs(value['change_conditions'],True,True)}
    pulse=value['pulse']
    if type(pulse) is not dict or set(pulse)!={'optimistic','cautious'}:
        raise ValueError('bounded narrative assessment required')
    optimistic,cautious=refs(pulse['optimistic']),refs(pulse['cautious'])
    publishers={item['publisher_id'] for item in optimistic+cautious}
    result['pulse']={'mode':'single_source' if len(publishers)==1 else 'collected_sources' if publishers else 'absent',
                     'optimistic':optimistic,'cautious':cautious}
    result['limitations']=['Asesmen peran sumber oleh model; bukan fakta pasar terverifikasi atau konsensus independen.']
    if not result['supporting']: result['limitations'].append('Bukti pendukung dari sumber belum tersedia.')
    if not result['opposing']: result['limitations'].append('Bukti penentang dari sumber belum tersedia.')
    else: result['limitations'].append('Bukti berlawanan tersedia; arah sesi tidak dipastikan.')
    if len(seen)>3: raise ValueError('at most three scenario sources')
    return result


def validate_scenario(scenario) -> ValidatedScenario:
    """Check full source identity and provenance across every role, including pulse.

    This checks attributed context, not the truth of a source or its model-assigned
    stance. No publication text is assembled. Keep the original selection intact.
    """
    if not isinstance(scenario,dict) or not scenario.get('base_case') or not scenario.get('change_conditions'):
        raise ValueError('complete selected scenario required')
    value=deepcopy(scenario)
    if value['pulse']['mode'] not in ('absent','single_source','collected_sources'):
        raise ValueError('narrative assessment mode required')
    if not isinstance(value['limitations'],list) or any(not isinstance(item,str) for item in value['limitations']):
        raise ValueError('text scenario limitations required')
    roles={};rows={}
    def add(role,items):
        for row in items:
            identity=row['evidence_id']
            if identity in rows and rows[identity]!=row: raise ValueError('inconsistent source context')
            rows[identity]=row;roles.setdefault(identity,[])
            if role not in roles[identity]: roles[identity].append(role)
    add('base_case',[value['base_case']])
    add('supporting',value['supporting'])
    add('opposing',value['opposing'])
    add('change_conditions',value['change_conditions'])
    add('optimistic',value['pulse']['optimistic'])
    add('cautious',value['pulse']['cautious'])
    sources=[]
    for identity,row in rows.items():
        # The former candidate renderer enforced these prerequisites incidentally.
        # Provenance remains checked even when the public paragraph omits a role.
        if not isinstance(row['excerpt'],str) or not row['publisher_id']:
            raise ValueError('complete attributed paragraph required')
        sources.append(ScenarioSource(row,tuple(roles[identity]),
            aware(datetime.fromisoformat(row['published_at'])),source_url(row['source_url'])))
    return ValidatedScenario(value,tuple(sources))


def validate_outlook(response,payload) -> ValidatedOutlook:
    """Ground the writer response in its frozen bundle and check shared contexts."""
    claims=_claims(response,payload)
    return ValidatedOutlook(claims,validate_scenario(_scenario(response,payload)))
