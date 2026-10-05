from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest
from morning_brief.global_markets import GREEN

PUBLICATION=date(2026,10,5)
CUTOFF=datetime(2026,10,5,7,30,tzinfo=ZoneInfo('Asia/Jakarta'))
TARGET=datetime(2026,10,5,8,tzinfo=ZoneInfo('Asia/Jakarta'))

def inputs():
    quotes=[dict(name='KOSPI',status='available',unit='points',change=23.4,percent=.5,price_at='2026-10-05T00:20:00+00:00',market_status='open',delay_status='delayed',delay_minutes=15,source_url='https://finance.yahoo.com/quote/%5EKS11/')]
    calendar={'events':[dict(event='Inflasi nasional',reference_period='September 2026',date='2026-10-06',time_wib=None,source='BPS',source_url='https://www.bps.go.id/id/calendar')],'unavailable':[]}
    outlook={'mode':'supported','claims':[{'excerpt':'Likuiditas membaik.','publisher_id':'Phintraco','source_url':'https://example.org/actual-source'}],'market_facts':[dict(label='IHSG',value=7200.5,unit='poin')]}
    return dict(publication_session=PUBLICATION,cutoff=CUTOFF,target=TARGET,outlook=outlook,globals=quotes,calendar=calendar,sectors=[],konglo=[])


def test_titles_hard_line_breaks_sources_and_frozen_times(core):
    f=core('formatting'); result=f.format_brief(**inputs(),logos={'KOSPI':'<:kospi:123456789012345678>'})
    assert len(result)==3 and all(len(x)<=2000 for x in result)
    assert result[0].startswith('### 🌇 BURSAWATCH PAGI: Mon, 5 Oct 2026')
    assert result[1].startswith('### 🏭 ROTASI SEKTOR: Mon, 5 Oct 2026')
    assert result[2].startswith('### 🐉 ROTASI KONGLO: Mon, 5 Oct 2026')
    assert all('07:30 WIB' in x and '08:00 WIB' in x for x in result)
    assert '**Pasar global**\n<:kospi:123456789012345678> KOSPI:' in result[0]
    assert GREEN in result[0] and '**Agenda Indonesia**' in result[0]
    for url in ['https://example.org/actual-source','https://finance.yahoo.com/quote/%5EKS11/','https://www.bps.go.id/id/calendar']:
        assert url in result[0]
    markdown=f.six_block_markdown(result,[{'title':'IDX Composite Index','path':'ihsg.png'},None,{'title':'Rotasi Konglo','path':'konglo.png'}])
    assert len(markdown.split('\n\n---\n\n'))==6
    assert 'gambar tidak tersedia' in markdown and '![' in markdown
    assert '<:kospi:123456789012345678>' in markdown and '  \n' in markdown


def test_optional_claims_and_citations_removed_together(core):
    values=inputs();values['outlook']['claims']=[{'excerpt':'long prose '*250,'publisher_id':'Phintraco','source_url':f'https://example.org/source/{i}'} for i in range(3)]
    values['notices']={'ihsg':['Notice '+('n'*2200)]}
    text=core('formatting').format_brief(**values)[0]
    assert len(text)<=2000
    assert all(f'https://example.org/source/{i}' not in text for i in range(3))
    assert 'bukti belum cukup' in text
    assert 'long prose' not in text
    assert text==core('formatting').format_brief(**values)[0]


def test_missing_logos_and_unavailable_inputs(core):
    values=inputs(); values.update(globals=[],calendar={'events':[],'unavailable':[{'source_url':'https://www.bi.go.id/id/publikasi/ruang-media/agenda-kegiatan/'}]},outlook={'mode':'facts_only','claims':[],'market_facts':[]})
    text=core('formatting').format_brief(**values)[0]
    assert 'belum tersedia' in text and '<:kospi' not in text
    assert 'https://www.bi.go.id/id/publikasi/ruang-media/agenda-kegiatan/' in text


def test_overlong_section_omitted_without_cutting_links(core):
    values=inputs();values['globals'][0]['source_url']='https://example.org/'+('x'*2100)
    text=core('formatting').format_brief(**values)[0]
    assert len(text.encode('utf-16-le'))//2<=2000 and 'IHSG' in text
    assert values['globals'][0]['source_url'] not in text
    assert 'belum tersedia' in text


def test_timing_mismatch_rejected(core):
    values=inputs();values['target']=CUTOFF
    with pytest.raises(ValueError):core('formatting').format_brief(**values)


def test_at_most_three_rotation_highlights_and_duplicate_names(core):
    from test_rendering import baskets
    values=inputs();values['sectors']=baskets(11)
    text=core('formatting').format_brief(**values)[1]
    assert text.count('Kekuatan')<=3 and text.count('Momentum')<=3
    values['sectors']=baskets(1)*2
    with pytest.raises(ValueError):core('formatting').format_brief(**values)


def test_cap_collection_wib_and_effective_date_distinguished(core):
    from test_rendering import baskets
    values=inputs();groups=baskets(1)
    groups[0].provenance.update(cap_collected_at='2026-10-05T00:00:00+00:00',cap_effective_date=None)
    values['sectors']=groups
    text=core('formatting').format_brief(**values)[1]
    assert 'dikumpulkan' in text and '07:00 WIB' in text
    assert 'tanggal efektif belum terverifikasi' in text
    assert 'bobot cap snapshot tetap' in text


def test_exact_discord_limit_with_real_emoji_and_full_url(core):
    f=core('formatting');values=inputs()
    values['outlook']={'mode':'facts_only','claims':[],'market_facts':[]}
    values['logos']={'KOSPI':'<:kospi:123456789012345678>'}
    baseline=f.format_brief(**values)[0]
    remaining=2000-len(baseline.encode('utf-16-le'))//2
    values['globals'][0]['source_url']+='x'*remaining
    boundary=f.format_brief(**values)[0]
    assert len(boundary.encode('utf-16-le'))//2==2000
    assert values['globals'][0]['source_url'] in boundary
    assert '<:kospi:123456789012345678>' in boundary
    values['globals'][0]['source_url']+='x'
    degraded=f.format_brief(**values)[0]
    assert len(degraded.encode('utf-16-le'))//2<=2000
    if values['globals'][0]['source_url'] in degraded:
        assert '<'+values['globals'][0]['source_url']+'>' in degraded


def test_parenthesized_source_url_is_rendered_safely(core):
    values=inputs();values['outlook']['claims'][0]['source_url']='https://example.org/a_(b)'
    text=core('formatting').format_brief(**values)[0]
    assert 'Menurut Phintraco: Likuiditas membaik.' in text
    assert '(Sources: <https://example.org/a_%28b%29>)' in text


def test_three_long_claim_urls_degrade_without_orphaned_links(core):
    values=inputs(); values['outlook']['claims']=[
        {'excerpt':'IHSG masih bersyarat.','publisher_id':'Source '+str(i),
         'source_url':'https://example.org/'+str(i)+('x'*1900)} for i in range(3)]
    text=core('formatting').format_brief(**values)[0]
    assert len(text.encode('utf-16-le'))//2<=2000 and 'IHSG' in text
    assert 'bukti belum cukup' in text and 'Menurut Source' not in text
    assert all(claim['source_url'] not in text for claim in values['outlook']['claims'])
    assert text==core('formatting').format_brief(**values)[0]


def scenario_inputs():
    values=inputs()
    base=dict(evidence_id='a'*64,excerpt='Jika likuiditas pulih, IHSG bergerak terbatas. Jika tekanan global bertambah, pandangan berubah.',
        publisher_id='Phintraco',source_url='https://example.org/scenario',published_at='2026-10-04T09:00:00+00:00')
    supporting={**base,'evidence_id':'b'*64,'excerpt':'IHSG tidak bebas tekanan global.','publisher_id':'Tuntun','source_url':'https://example.org/caution'}
    values['outlook']['claims']=[]
    values['outlook']['scenario']={'assessment':'model_assigned_source_roles','base_case':base,'supporting':[],
        'opposing':[supporting],'change_conditions':[base],
        'pulse':{'mode':'collected_sources','optimistic':[base],'cautious':[supporting]},'limitations':['Bukti berlawanan tersedia; arah sesi tidak dipastikan.']}
    return values


def test_grounded_conditional_core_pulse_and_inline_context_are_visible(core):
    values=scenario_inputs();text=core('formatting').format_brief(**values)[0]
    assert '**Skenario IHSG**' in text and 'asesmen model' in text
    assert 'Kasus dasar' in text and 'Kondisi perubahan' in text
    assert 'Pendukung belum tersedia' in text and 'Penentang' in text
    assert '**Narasi sumber terkumpul**' in text and 'optimistis' in text and 'hati-hati' in text
    assert 'IHSG tidak bebas tekanan global.' in text and '04/10 16:00 WIB' in text
    assert '(Sources: <https://example.org/scenario>)' in text
    assert '(Sources: <https://example.org/caution>)' in text
    assert text.count('Jika likuiditas pulih')==1
    assert 'bukti belum cukup' not in text


def test_single_source_and_absent_pulse_not_misrepresented(core):
    values=scenario_inputs();scenario=values['outlook']['scenario']
    scenario['pulse']={'mode':'single_source','optimistic':[scenario['base_case']],'cautious':[]}
    text=core('formatting').format_brief(**values)[0]
    assert '**Pandangan satu sumber**' in text and '**Narasi sumber terkumpul**' not in text
    scenario['pulse']={'mode':'absent','optimistic':[],'cautious':[]}
    text=core('formatting').format_brief(**values)[0]
    assert 'Pandangan satu sumber' not in text and 'Narasi sumber' not in text


def test_unrenderable_scenario_falls_back_atomically_with_no_direction_or_orphaned_citations(core):
    values=scenario_inputs()
    values['outlook']['scenario']['base_case']['source_url']='https://example.org/'+('x'*1950)
    text=core('formatting').format_brief(**values)[0]
    assert len(text.encode('utf-16-le'))//2<=2000 and 'bukti belum cukup' in text
    assert 'Jika likuiditas pulih' not in text and 'https://example.org/caution' not in text


def test_invalid_optional_fact_does_not_make_frozen_selection_permanently_fatal(core):
    values=inputs();values['outlook']['market_facts'].append({'label':'IHSG invalid','value':float('inf'),'unit':'poin'})
    text=core('formatting').format_brief(**values)[0]
    assert '7200.5' in text and 'inf' not in text and len(text.encode('utf-16-le'))//2<=2000


def test_invalid_rotation_provenance_degrades_with_explicit_gap(core):
    from test_rendering import baskets
    values=inputs();groups=baskets(1)
    groups[0].provenance['source_url']='https://example.org/invalid path'
    values['sectors']=groups
    text=core('formatting').format_brief(**values)[1]
    assert 'belum tersedia' in text and 'Kekuatan' not in text


def test_supported_scenario_requires_its_verified_driver_to_be_presentable(core):
    values=scenario_inputs()
    values['globals'][0]['source_url']='https://example.org/'+('g'*2200)
    values['calendar']['events'][0]['source_url']='https://example.org/'+('c'*2200)
    texts,presentation=core('formatting').format_brief(**values,with_selection=True)
    assert presentation['mode']=='facts_only' and presentation['scenario'] is None
    assert 'bukti belum cukup' in texts[0] and 'Jika likuiditas' not in texts[0]


def test_safe_url_encoding_preserves_host_and_url_identity(core):
    values=inputs()
    values['outlook']['claims'][0]['source_url']='https://[2001:db8::1]/a_(b)?v=[q]'
    text=core('formatting').format_brief(**values)[0]
    assert '(Sources: <https://[2001:db8::1]/a_%28b%29?v=%5Bq%5D>)' in text
