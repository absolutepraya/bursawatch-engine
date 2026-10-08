"""Injected writers consume only frozen bundles; unsupported text is facts-only."""
from datetime import datetime
from threading import Event
import time
import subprocess
import sys
from pathlib import Path
import pytest
from test_evidence import owner, source, manifest, CapturedClient, LOWER, FREEZE
from test_global_markets import chart, schedule, US_ROWS
from test_economic_calendar import saved, page


def frozen_bundle(core,tmp_path,source_text='Laba emiten sintetis naik 10 persen. Kas emiten tetap positif. IHSG bergerak terbatas.'):
    store,run,lease=owner(core,tmp_path)
    rows=[source(1,text=source_text),source(2,text='Jika likuiditas pulih, IHSG berpotensi bergerak terbatas. Jika tekanan global bertambah, pandangan ini perlu ditinjau ulang.')]
    capture=manifest(rows,captured_at='2026-10-05T00:30:04.200000+00:00',capture_gap_seconds=4.2)
    core('evidence').freeze_source_evidence(store,run.run_id,CapturedClient(store,run.run_id,rows,capture),previous_cutoff=LOWER,lease=lease,now=FREEZE)
    globals_module=core('global_markets')
    quote=globals_module.parse_yahoo_chart('QQQ',chart('QQQ','America/New_York',[s for s,e in US_ROWS[:2]],[100,102]),freeze_at=FREEZE,retrieved_at=FREEZE,sessions=schedule('America/New_York',US_ROWS))
    globals_module.freeze_globals(store,run.run_id,[quote],lease=lease,now=FREEZE)
    calendars=core('economic_calendar')
    snapshot=saved(calendars,calendars.SnapshotCache(tmp_path/'calendars'),page([['2026-10-06','Inflasi','September 2026','','release-1',1,'nasional']]))
    calendars.freeze_calendar_events(store,run.run_id,[snapshot],lease=lease,now=FREEZE)
    store.freeze(run.run_id,'inputs',{'publication_session':'2026-10-05','closing_session':'2026-10-02','previous_session':'2026-10-02','benchmark_version':'verified-fixture','facts':[{'label':'IHSG close 2026-10-02','value':7000,'unit':'poin'}]},lease=lease,now=FREEZE)
    bundle=core('outlook').freeze_bundle(store,run.run_id,model_version='injected-fixture-1',prompt_version='extractive-1',lease=lease,now=FREEZE)
    return store,run,lease,bundle


def test_structured_exact_claims_get_inline_attribution_and_native_facts_survive(core,tmp_path):
    module=core('outlook')
    store,run,lease,bundle=frozen_bundle(core,tmp_path)
    def model(payload):
        assert payload['versions']=={'model':'injected-fixture-1','prompt':'extractive-1'}
        assert payload['cutoff']==run.freeze_at
        row=payload['evidence']['items'][0]
        return with_scenario(payload,[{'evidence_id':row['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}])
    result=module.write_outlook(bundle,model,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='supported' and 'Menurut collector' in result['text'] and '(Sources: <https://example.com/story/1>)' in result['text']
    assert 'QQQ: +2.00 USD (+2.00%)' in result['text'] and 'Inflasi' in result['text'] and 'IHSG close 2026-10-02: 7000 poin' in result['text']
    assert result['global_facts'][0]['price']==102 and result['calendar_facts'][0]['date']=='2026-10-06'
    assert result['bundle_digest']==bundle.digest


@pytest.mark.parametrize('mutation', ['unknown_id','invented_level','probability','partial_context','freeform','extra_fields'])
def test_source_id_alone_or_partial_excerpt_does_not_support_arbitrary_claim(core,tmp_path,mutation):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path)
    claim={'evidence_id':bundle.payload['evidence']['items'][0]['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}
    response=with_scenario(bundle.payload,[claim])
    if mutation=='unknown_id': claim['evidence_id']='f'*64
    elif mutation=='invented_level': claim['excerpt']='IHSG menuju 8000 karena laba naik.'
    elif mutation=='probability': claim['excerpt']='Peluang IHSG naik 90%.'
    elif mutation=='partial_context': claim['excerpt']='naik 10 persen.'
    elif mutation=='freeform': response='IHSG pasti naik.'
    elif mutation=='extra_fields': claim['direction']='bullish'
    result=module.write_outlook(bundle,lambda _bundle:response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'
    assert result['claims']==[] and 'QQQ: +2.00 USD (+2.00%)' in result['text'] and 'Inflasi' in result['text']
    assert '8000' not in result['text'] and '90%' not in result['text']


def test_degraded_evidence_skips_model_and_preserves_independent_facts(core,tmp_path):
    module=core('outlook'); store,run,lease=owner(core,tmp_path)
    rows=[source(1)]
    core('evidence').freeze_source_evidence(store,run.run_id,CapturedClient(store,run.run_id,rows,manifest(rows,overflow=True,complete=False)),previous_cutoff=LOWER,lease=lease,now=FREEZE)
    bundle=module.freeze_bundle(store,run.run_id,model_version='fixture',prompt_version='extractive-1',lease=lease,now=FREEZE)
    def forbidden(_): pytest.fail('incomplete corpus called writer')
    result=module.write_outlook(bundle,forbidden,now=FREEZE)
    assert result['mode']=='facts_only' and result['reason']=='incomplete_evidence'


def test_timeout_releases_by_0755_bounds_retries_and_late_mutation_cannot_change_fallback(core,tmp_path):
    module=core('outlook'); store,run,lease,bundle=frozen_bundle(core,tmp_path)
    started,release,finished=Event(),Event(),Event()
    def stuck(payload):
        started.set(); release.wait(5)
        payload['globals']['quotes'][0]['price']=999999
        finished.set()
        return with_scenario(payload,[{'evidence_id':payload['evidence']['items'][0]['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}])
    try:
        now=datetime.fromisoformat('2026-10-05T07:54:59.980+07:00')
        start=time.monotonic()
        result=module.write_outlook(bundle,stuck,now=now,timeout_seconds=5)
        elapsed=time.monotonic()-start
        assert started.is_set() and not finished.is_set() and elapsed<0.25
        assert result['mode']=='facts_only' and result['reason']=='model_timeout'
        retry=module.write_outlook(bundle,lambda _:pytest.fail('spawned another worker while first hung'),now=now,timeout_seconds=5)
        assert retry['reason']=='model_busy'
        store.freeze(run.run_id,'outlook',result,lease=lease,now=FREEZE)
        release.set(); assert finished.wait(1)
        assert result['global_facts'][0]['price']==102
        assert store.get_frozen(run.run_id,'outlook').payload['mode']=='facts_only'
        assert store.get_frozen(run.run_id,'globals').payload['quotes'][0]['price']==102
    finally: release.set()


def test_timeout_worker_does_not_hold_interpreter_exit(core):
    core('outlook')
    root=Path(__file__).resolve().parents[1]/'bin'
    script="""
import sys,time
sys.path.insert(0,sys.argv[1])
from morning_brief.outlook import write_outlook
from datetime import datetime
bundle={'cutoff':'2026-10-05T00:30:00+00:00','evidence':{'facts_only':False,'items':[]},'globals':{'quotes':[]},'calendar_events':{'events':[{'event':'Inflasi','reference_period':'September','date':'2026-10-06','time_wib':None,'source':'BPS','source_url':'https://example.test/event'}]},'inputs':{'previous_session':'2026-10-02','benchmark_version':'fixture','facts':[{'label':'IHSG close 2026-10-02','value':7000,'unit':'poin'}]},'versions':{'model':'test','prompt':'test'}}
r=write_outlook(bundle,lambda _:time.sleep(60),now=datetime.fromisoformat('2026-10-05T07:54:59.999+07:00'),timeout_seconds=10)
assert r['reason']=='model_timeout'
print('fallback returned')
"""
    result=subprocess.run([sys.executable,'-c',script,str(root)],capture_output=True,text=True,timeout=2)
    assert result.returncode==0 and result.stdout.strip()=='fallback returned'


def test_at_deadline_never_starts_model(core,tmp_path):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path)
    result=module.write_outlook(bundle,lambda _:pytest.fail('model started at fallback deadline'),now=datetime.fromisoformat('2026-10-05T07:55:00+07:00'))
    assert result['reason']=='fallback_deadline'


def test_writer_deadline_also_bounds_support_validation(core,tmp_path,monkeypatch):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path)
    original=module._claims
    finished=Event()
    def delayed_support(*args):
        time.sleep(0.15)
        result=original(*args)
        finished.set()
        return result
    monkeypatch.setattr(module,'_claims',delayed_support)
    row=bundle.payload['evidence']['items'][0]
    start=time.monotonic()
    try:
        result=module.write_outlook(bundle,lambda payload:with_scenario(payload,[{'evidence_id':row['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}]),now=datetime.fromisoformat('2026-10-05T07:54:59.980+07:00'),timeout_seconds=1)
        assert result['reason']=='model_timeout' and result['mode']=='facts_only'
        assert time.monotonic()-start<0.1
    finally:
        assert finished.wait(1)


@pytest.mark.parametrize('source_text,fragment', [
    ('IHSG tidak\nnaik.', 'naik.'),
    ('IHSG tidak\r\nnaik.', 'naik.'),
    ('Jika likuiditas pulih,\nIHSG naik.', 'IHSG naik.'),
    ('Jika inflasi stabil:\n\nIHSG naik.', 'IHSG naik.'),
])
def test_source_wrap_cannot_remove_preceding_negation_or_condition(core,tmp_path,source_text,fragment):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path,source_text)
    row=bundle.payload['evidence']['items'][0]
    result=module.write_outlook(bundle,lambda payload:with_scenario(payload,[{'evidence_id':row['evidence_id'],'excerpt':fragment}]),now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'
    assert result['claims']==[] and 'Menurut ' not in result['text']
    assert result['global_facts'][0]['price']==102 and result['calendar_facts'][0]['date']=='2026-10-06'


@pytest.mark.parametrize('source_text,excerpt', [
    ('IHSG tidak\nnaik.', 'IHSG tidak\nnaik.'),
    ('Jika likuiditas pulih,\nIHSG naik.', 'Jika likuiditas pulih,\nIHSG naik.'),
    ('IHSG: laba emiten naik.\nKas emiten tetap positif.', 'Kas emiten tetap positif.'),
    ('IHSG tidak\nnaik. Kas emiten tetap positif.', 'IHSG tidak\nnaik.'),
])
def test_complete_wrapped_context_and_punctuation_delimited_sentences_remain_supported(core,tmp_path,source_text,excerpt):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path,source_text)
    row=bundle.payload['evidence']['items'][0]
    result=module.write_outlook(bundle,lambda payload:with_scenario(payload,[{'evidence_id':row['evidence_id'],'excerpt':excerpt}]),now=FREEZE,timeout_seconds=1)
    assert result['mode']=='supported' and result['reason'] is None
    assert result['claims'][0]['excerpt']==excerpt
    assert result['claims'][0]['text']=='Menurut [collector](https://example.com/story/1): '+source_text


@pytest.mark.parametrize('source_text', [
    'Probabilitas IHSG naik 80 persen.',
    'Probabilitas\nIHSG naik 80 persen.',
    'Probabilitas\r\nIHSG naik 80 persen.',
    'Peluang\n\nIHSG naik 80 persen.',
    'Probability\nIHSG naik 80 persen.',
    '80 persen\nprobabilitas IHSG naik.',
])
def test_complete_wrapped_numerical_probability_falls_back(core,tmp_path,source_text):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path,source_text)
    row=bundle.payload['evidence']['items'][0]
    result=module.write_outlook(bundle,lambda payload:with_scenario(payload,[{'evidence_id':row['evidence_id'],'excerpt':source_text}]),now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'
    assert result['claims']==[] and 'Menurut ' not in result['text']
    assert result['global_facts'][0]['price']==102 and result['calendar_facts'][0]['date']=='2026-10-06'


@pytest.mark.parametrize('missing', ['close','version','wrong_session','dated_driver'])
def test_evidence_floor_requires_verified_latest_close_and_dated_factual_driver(core,tmp_path,missing):
    import copy
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    payload=copy.deepcopy(bundle.payload)
    if missing=='close': payload['inputs']['facts']=[]
    elif missing=='version': payload['inputs'].pop('benchmark_version')
    elif missing=='wrong_session': payload['inputs']['facts'][0]['label']='IHSG close 2026-10-01'
    else:
        payload['globals']['quotes']=[]
        payload['calendar_events']['events']=[]
    result=core('outlook').write_outlook(payload,lambda _:pytest.fail('below-floor outlook invoked model'),now=FREEZE)
    assert result['mode']=='facts_only' and result['reason']=='evidence_floor'


def structured_response(payload):
    rows=payload['evidence']['items']
    def ref(row): return {'evidence_id':row['evidence_id'],'excerpt':row['text']}
    return {'claims':[], 'scenario':{'base_case':ref(rows[-1]),'supporting':[ref(rows[0])],
        'opposing':[],'change_conditions':[ref(rows[-1])],
        'pulse':{'optimistic':[ref(rows[0])],'cautious':[]}}}


def test_conditional_source_grounded_core_reaches_generated_after_nonzero_capture_gap(core,tmp_path):
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    result=core('outlook').write_outlook(bundle,structured_response,now=FREEZE,timeout_seconds=1)
    assert bundle.payload['evidence']['capture_gap_seconds']==4.2
    assert result['mode']=='supported'
    scenario=result['scenario']
    assert scenario['assessment']=='model_assigned_source_roles'
    assert scenario['base_case']['excerpt']==bundle.payload['evidence']['items'][-1]['text']
    assert scenario['change_conditions'][0]['source_url']=='https://example.com/story/2'
    assert scenario['supporting'][0]['published_at']=='2026-10-04T09:00:00+00:00'
    assert scenario['pulse']['mode']=='single_source' and scenario['opposing']==[]
    assert scenario['limitations'] and result['bundle_digest']==bundle.digest


@pytest.mark.parametrize('mutation',['missing_base','missing_condition','unknown_id','partial_context','freeform','probability','unconditional','unsafe_url'])
def test_structured_scenario_rejects_unsupported_or_context_losing_output(core,tmp_path,mutation):
    import copy
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    payload=copy.deepcopy(bundle.payload);response=structured_response(payload)
    if mutation=='missing_base': response['scenario']['base_case']=None
    elif mutation=='missing_condition': response['scenario']['change_conditions']=[]
    elif mutation=='unknown_id': response['scenario']['base_case']['evidence_id']='f'*64
    elif mutation=='partial_context': response['scenario']['base_case']['excerpt']='IHSG berpotensi bergerak terbatas.'
    elif mutation=='freeform': response['scenario']['summary']='IHSG pasti naik.'
    elif mutation=='probability':
        row=payload['evidence']['items'][-1];row['text']='Jika likuiditas pulih, probabilitas IHSG naik 90 persen.'
        response=structured_response(payload)
    elif mutation=='unconditional':
        payload['evidence']['items'][-1]['text']='IHSG pasti naik.'; response=structured_response(payload)
    else: payload['evidence']['items'][-1]['source_url']='https://example.com/invalid path'
    result=core('outlook').write_outlook(payload,lambda _:response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'
    assert result.get('scenario') is None and 'IHSG close 2026-10-02' in result['text']


def test_bare_extracts_do_not_replace_required_conditional_core(core,tmp_path):
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    row=bundle.payload['evidence']['items'][0]
    result=core('outlook').write_outlook(bundle,lambda _:{'claims':[{'evidence_id':row['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}]},now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only'


def with_scenario(payload,claims):
    result=structured_response(payload); result['claims']=claims
    return result


def test_no_qualifying_pulse_is_omitted_and_opposing_absence_explicit(core,tmp_path):
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    response=structured_response(bundle.payload);response['scenario']['pulse']={'optimistic':[],'cautious':[]}
    result=core('outlook').write_outlook(bundle,lambda _:response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='supported' and result['scenario']['pulse']['mode']=='absent'
    assert 'Bukti penentang dari sumber belum tersedia.' in result['scenario']['limitations']


def test_whole_context_retains_sentence_level_negation_and_conditions(core,tmp_path):
    text='IHSG tidak diperkirakan naik. Jika tekanan reda, IHSG dapat bergerak terbatas.'
    _,_,_,bundle=frozen_bundle(core,tmp_path,text)
    result=core('outlook').write_outlook(bundle,lambda payload:with_scenario(payload,[
        {'evidence_id':payload['evidence']['items'][0]['evidence_id'],'excerpt':'Jika tekanan reda, IHSG dapat bergerak terbatas.'}]),now=FREEZE)
    assert result['mode']=='supported' and text in result['claims'][0]['text']
    assert result['scenario']['supporting'][0]['excerpt']==text


def test_probability_with_long_qualifier_cannot_evade_whole_context_guard(core,tmp_path):
    import copy
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    payload=copy.deepcopy(bundle.payload)
    payload['evidence']['items'][-1]['text']='Jika likuiditas pulih, probabilitas '+('berdasarkan kondisi pasar '*3)+'IHSG naik 80 persen.'
    result=core('outlook').write_outlook(payload,structured_response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'


def test_two_collecting_publishers_remain_model_assessed_views_not_consensus(core,tmp_path):
    import copy
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    payload=copy.deepcopy(bundle.payload)
    payload['evidence']['items'][0]['publisher_id']='Tuntun'
    response=structured_response(payload)
    response['scenario']['opposing']=[response['scenario']['supporting'][0]]
    response['scenario']['pulse']['cautious']=[response['scenario']['base_case']]
    result=core('outlook').write_outlook(payload,lambda _:response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='supported' and result['scenario']['pulse']['mode']=='collected_sources'
    assert 'Bukti berlawanan tersedia; arah sesi tidak dipastikan.' in result['scenario']['limitations']
    assert 'bukan konsensus' in result['text']


def test_complete_context_probability_is_rejected_even_when_selected_sentence_omits_it(core,tmp_path):
    _,_,_,bundle=frozen_bundle(core,tmp_path,'Probabilitas IHSG naik 80 persen. Likuiditas membaik.')
    response=with_scenario(bundle.payload,[{'evidence_id':bundle.payload['evidence']['items'][0]['evidence_id'],
        'excerpt':'Likuiditas membaik.'}])
    response['scenario']['supporting']=[]
    response['scenario']['pulse']={'optimistic':[],'cautious':[]}
    result=core('outlook').write_outlook(bundle,lambda _:response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'


@pytest.mark.parametrize('path', ['scenario','claim'])
@pytest.mark.parametrize('source_text', [
    'Jika likuiditas pulih, IHSG memiliki 80 persen peluang naik.',
    'Jika likuiditas pulih, IHSG memiliki 80 persen\npeluang naik.',
    'Jika likuiditas pulih, IHSG memiliki 80 persen\r\npeluang naik.',
    'Jika likuiditas pulih, IHSG memiliki 80 persen\n\npeluang naik.',
])
def test_number_before_peluang_cannot_enter_claim_or_scenario_even_across_wraps(core,tmp_path,path,source_text):
    import copy
    from test_formatting import inputs
    _,_,_,bundle=frozen_bundle(core,tmp_path,source_text)
    payload=copy.deepcopy(bundle.payload)
    response=structured_response(payload)
    if path=='scenario':
        payload['evidence']['items'][-1]['text']=source_text
        response=structured_response(payload)
    else:
        row=payload['evidence']['items'][0]
        response['claims']=[{'evidence_id':row['evidence_id'],'excerpt':source_text}]
        # Keep scenario references on safe source 2, so only the claim guard can
        # reject source 1. A scenario-side rejection cannot mask a claim defect.
        response['scenario']['supporting']=[]
        response['scenario']['pulse']={'optimistic':[],'cautious':[]}
    result=core('outlook').write_outlook(payload,lambda _:response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'
    assert result['claims']==[] and result['scenario'] is None and '80 persen' not in result['text']
    values=inputs();values['outlook']=result
    texts,presentation=core('formatting').format_brief(**values,with_selection=True)
    assert presentation['mode']=='facts_only' and presentation['scenario'] is None
    assert '80 persen' not in texts[0]


@pytest.mark.parametrize('text,expected',[
    ('IHSG berpeluang menguji level 6.370. Jika turun di bawah 6.120, risiko koreksi meningkat.',False),
    ('Peluang IHSG untuk melanjutkan penguatan menuju 6.297-6.339 terbuka, terutama jika volume beli tetap dominan.',False),
    ('Berpeluang menguat. Support 6.100 dan resistance 6.300.',False),
    ('Ada peluang 70% IHSG naik.',True),
    ('IHSG berpeluang naik 70 persen hari ini.',True),
    ('Probabilitas sebesar 70 persen.',True),
    ('The probability of 0.7 is high.',True),
    ('70% probability of a rally.',True),
    ('Jika likuiditas pulih, probabilitas '+('berdasarkan kondisi pasar '*3)+'IHSG naik 80 persen.',True),
])
def test_only_numeric_probability_claims_are_rejected_not_levels_beside_berpeluang(core,text,expected):
    assert core('outlook').states_probability(text) is expected


def test_a_real_analyst_sentence_with_berpeluang_and_index_levels_reaches_a_supported_outlook(core,tmp_path):
    import copy
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    payload=copy.deepcopy(bundle.payload)
    payload['evidence']['items'][-1]['text']='Jika momentum beli semakin kuat, IHSG berpeluang menguji level 6.370. Jika turun di bawah 6.120, risiko koreksi meningkat.'
    result=core('outlook').write_outlook(payload,structured_response,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='supported'


def _two_attempt_model(payload,*,first,second=None):
    calls=[]
    def model(request):
        calls.append(request)
        return first if len(calls)==1 else (second if second is not None else first)
    return model,calls


def test_one_correction_pass_recovers_an_invalid_first_answer_and_carries_only_our_message(core,tmp_path):
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    good=structured_response(bundle.payload)
    model,calls=_two_attempt_model(bundle.payload,first={'claims':[],'scenario':None},second=good)
    result=core('outlook').write_outlook(bundle,model,now=FREEZE,timeout_seconds=5)
    assert result['mode']=='supported' and len(calls)==2
    assert 'retry_feedback' not in calls[0] and calls[1]['retry_feedback']=='complete structured scenario required'


def test_two_invalid_answers_fall_back_after_exactly_two_calls(core,tmp_path):
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    model,calls=_two_attempt_model(bundle.payload,first={'claims':[],'scenario':None})
    result=core('outlook').write_outlook(bundle,model,now=FREEZE,timeout_seconds=5)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim' and len(calls)==2


def test_a_model_failure_is_not_retried(core,tmp_path):
    _,_,_,bundle=frozen_bundle(core,tmp_path)
    calls=[]
    def broken(request):
        calls.append(request); raise OSError('provider down')
    result=core('outlook').write_outlook(bundle,broken,now=FREEZE,timeout_seconds=5)
    assert result['reason']=='model_unavailable' and len(calls)==1
