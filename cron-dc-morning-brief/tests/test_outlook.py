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


def frozen_bundle(core,tmp_path,source_text='Laba emiten sintetis naik 10 persen. Kas emiten tetap positif.'):
    store,run,lease=owner(core,tmp_path)
    core('evidence').freeze_source_evidence(store,run.run_id,CapturedClient(store,run.run_id,[source(1,text=source_text)]),previous_cutoff=LOWER,lease=lease,now=FREEZE)
    globals_module=core('global_markets')
    quote=globals_module.parse_yahoo_chart('QQQ',chart('QQQ','America/New_York',[s for s,e in US_ROWS[:2]],[100,102]),freeze_at=FREEZE,retrieved_at=FREEZE,sessions=schedule('America/New_York',US_ROWS))
    globals_module.freeze_globals(store,run.run_id,[quote],lease=lease,now=FREEZE)
    calendars=core('economic_calendar')
    snapshot=saved(calendars,calendars.SnapshotCache(tmp_path/'calendars'),page([['2026-10-06','Inflasi','September 2026','','release-1',1,'nasional']]))
    calendars.freeze_calendar_events(store,run.run_id,[snapshot],lease=lease,now=FREEZE)
    store.freeze(run.run_id,'inputs',{'publication_session':'2026-10-05','closing_session':'2026-10-02','facts':[{'label':'IHSG','value':7000,'unit':'poin'}]},lease=lease,now=FREEZE)
    bundle=core('outlook').freeze_bundle(store,run.run_id,model_version='injected-fixture-1',prompt_version='extractive-1',lease=lease,now=FREEZE)
    return store,run,lease,bundle


def test_structured_exact_claims_get_inline_attribution_and_native_facts_survive(core,tmp_path):
    module=core('outlook')
    store,run,lease,bundle=frozen_bundle(core,tmp_path)
    def model(payload):
        assert payload['versions']=={'model':'injected-fixture-1','prompt':'extractive-1'}
        assert payload['cutoff']==run.freeze_at
        row=payload['evidence']['items'][0]
        return {'claims':[{'evidence_id':row['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}]}
    result=module.write_outlook(bundle,model,now=FREEZE,timeout_seconds=1)
    assert result['mode']=='supported' and '[collector](https://example.com/story/1)' in result['text']
    assert 'QQQ: +2.00 USD (+2.00%)' in result['text'] and 'Inflasi' in result['text'] and 'IHSG: 7000 poin' in result['text']
    assert result['global_facts'][0]['price']==102 and result['calendar_facts'][0]['date']=='2026-10-06'
    assert result['bundle_digest']==bundle.digest


@pytest.mark.parametrize('mutation', ['unknown_id','invented_level','probability','partial_context','freeform','extra_fields'])
def test_source_id_alone_or_partial_excerpt_does_not_support_arbitrary_claim(core,tmp_path,mutation):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path)
    claim={'evidence_id':bundle.payload['evidence']['items'][0]['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}
    response={'claims':[claim]}
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
        return {'claims':[{'evidence_id':payload['evidence']['items'][0]['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}]}
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
bundle={'cutoff':'2026-10-05T00:30:00+00:00','evidence':{'facts_only':False,'items':[]},'globals':{'quotes':[]},'calendar_events':{'events':[]},'inputs':{},'versions':{'model':'test','prompt':'test'}}
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
        result=module.write_outlook(bundle,lambda _: {'claims':[{'evidence_id':row['evidence_id'],'excerpt':'Laba emiten sintetis naik 10 persen.'}]},now=datetime.fromisoformat('2026-10-05T07:54:59.980+07:00'),timeout_seconds=1)
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
    result=module.write_outlook(bundle,lambda _: {'claims':[{'evidence_id':row['evidence_id'],'excerpt':fragment}]},now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'
    assert result['claims']==[] and 'Menurut ' not in result['text']
    assert result['global_facts'][0]['price']==102 and result['calendar_facts'][0]['date']=='2026-10-06'


@pytest.mark.parametrize('source_text,excerpt', [
    ('IHSG tidak\nnaik.', 'IHSG tidak\nnaik.'),
    ('Jika likuiditas pulih,\nIHSG naik.', 'Jika likuiditas pulih,\nIHSG naik.'),
    ('Laba emiten naik.\nKas emiten tetap positif.', 'Kas emiten tetap positif.'),
    ('IHSG tidak\nnaik. Kas emiten tetap positif.', 'IHSG tidak\nnaik.'),
])
def test_complete_wrapped_context_and_punctuation_delimited_sentences_remain_supported(core,tmp_path,source_text,excerpt):
    module=core('outlook'); _,_,_,bundle=frozen_bundle(core,tmp_path,source_text)
    row=bundle.payload['evidence']['items'][0]
    result=module.write_outlook(bundle,lambda _: {'claims':[{'evidence_id':row['evidence_id'],'excerpt':excerpt}]},now=FREEZE,timeout_seconds=1)
    assert result['mode']=='supported' and result['reason'] is None
    assert result['claims'][0]['excerpt']==excerpt
    assert result['claims'][0]['text']=='Menurut [collector](https://example.com/story/1): '+excerpt


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
    result=module.write_outlook(bundle,lambda _: {'claims':[{'evidence_id':row['evidence_id'],'excerpt':source_text}]},now=FREEZE,timeout_seconds=1)
    assert result['mode']=='facts_only' and result['reason']=='unsupported_claim'
    assert result['claims']==[] and 'Menurut ' not in result['text']
    assert result['global_facts'][0]['price']==102 and result['calendar_facts'][0]['date']=='2026-10-06'
