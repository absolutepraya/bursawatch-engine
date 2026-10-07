from datetime import date, datetime
from zoneinfo import ZoneInfo
import pytest
from morning_brief.global_markets import GREEN, RED

PUBLICATION=date(2026,10,5)
CUTOFF=datetime(2026,10,5,7,30,tzinfo=ZoneInfo('Asia/Jakarta'))
TARGET=datetime(2026,10,5,8,tzinfo=ZoneInfo('Asia/Jakarta'))


def inputs():
    quotes=[dict(name='KOSPI',status='available',unit='points',change=23.4,percent=.5,price_at='2026-10-05T00:20:00+00:00',market_status='open',delay_status='delayed',delay_minutes=15,source_url='https://finance.yahoo.com/quote/%5EKS11/')]
    calendar={'events':[dict(event='Inflasi nasional',reference_period='September 2026',date='2026-10-06',time_wib=None,source='BPS',source_url='https://www.bps.go.id/id/calendar')],'unavailable':[]}
    outlook={'mode':'supported','claims':[{'excerpt':'Likuiditas membaik.','publisher_id':'Phintraco','source_url':'https://example.org/actual-source'}],'market_facts':[dict(label='IHSG',value=7200.5,unit='poin')]}
    return dict(publication_session=PUBLICATION,cutoff=CUTOFF,target=TARGET,outlook=outlook,globals=quotes,calendar=calendar,sectors=[],konglo=[])


def scenario_inputs():
    values=inputs()
    base=dict(evidence_id='a'*64,excerpt='Jika likuiditas pulih, IHSG bergerak terbatas. Jika tekanan global bertambah, pandangan berubah.',publisher_id='Phintraco',source_url='https://example.org/scenario',published_at='2026-10-04T09:00:00+00:00')
    opposing={**base,'evidence_id':'b'*64,'excerpt':'IHSG tidak bebas tekanan global.','publisher_id':'Tuntun','source_url':'https://example.org/caution'}
    values['outlook']['claims']=[]
    values['outlook']['scenario']={'assessment':'model_assigned_source_roles','base_case':base,'supporting':[],
        'opposing':[opposing],'change_conditions':[base],
        'pulse':{'mode':'collected_sources','optimistic':[base],'cautious':[opposing]},'limitations':['Bukti berlawanan tersedia; arah sesi tidak dipastikan.']}
    return values


def test_exact_requested_main_layout_and_tracker(core):
    fields=inputs()
    fields['ihsg_tracker']=dict(latest_price=9175,one_day_change=-125,one_day_percent=-1.34,
        one_week_change=-575,one_week_percent=-5.90,one_month_change=-475,one_month_percent=-4.92,
        three_month_change=2175,three_month_percent=31.07)
    text=core('formatting').format_brief(**fields,logos={'KOSPI':'<:kospi:123456789012345678>'})[0]
    expected=('### 🌇 BURSAWATCH PAGI: Mon, 5 Oct 2026\n\n'
        'Penutupan IHSG terakhir (IDR): **9.175**\n'
        f'{RED} 1D: **-125 (-1.34%)**, {RED} 1W: **-575 (-5.90%)**,\n'
        f'{RED} 1M: **-475 (-4.92%)**, {GREEN} 3M: **+2.175 (+31.07%)**\n\n'
        'Outlook IHSG:\nMenurut Phintraco: Likuiditas membaik.\n\n'
        f'Pasar global:\n<:kospi:123456789012345678> KOSPI: +23.40 poin (+0.50%) {GREEN}\n\n'
        'Agenda Ekonomi Indonesia \\[[BPS](https://www.bps.go.id/id/calendar)\\]:\n'
        '* Inflasi nasional - Tue, 06 Oct 2026')
    assert text==expected
    assert '·' not in text and 'Sources:' not in text and fields['outlook']['claims'][0]['source_url'] not in text


def test_missing_fields_are_only_hyphens(core):
    fields=inputs();fields.update(globals=[dict(name='KOSPI',status='stale')],calendar={'events':[]},outlook={'mode':'facts_only','market_facts':[]})
    text=core('formatting').format_brief(**fields)[0]
    assert 'Penutupan IHSG terakhir (IDR): **-**\n1D: **-**, 1W: **-**,\n1M: **-**, 3M: **-**' in text
    assert 'Outlook IHSG:\n-' in text and 'KOSPI: -' in text and 'Agenda Ekonomi Indonesia:\n-' in text
    assert 'belum tersedia' not in text and 'kedaluwarsa' not in text


def test_at_most_three_agenda_bullets_one_header_source_and_no_period_or_time(core):
    fields=inputs();event=fields['calendar']['events'][0]
    fields['calendar']['events']=[{**event,'event':f'Agenda {i}','date':f'2026-10-{6+i:02}','time_wib':'10:00'} for i in range(5)]
    text=core('formatting').format_brief(**fields)[0]
    assert text.count('* Agenda ')==3 and text.count('[BPS]')==1
    assert 'September 2026' not in text and '10:00' not in text and '* Agenda 3' not in text


def test_overlong_outlook_falls_back_atomically_preserving_required_sections(core):
    fields=inputs();fields['outlook']['claims']=[{'excerpt':'long prose '*250,'publisher_id':'Phintraco','source_url':'https://example.org/source'}]
    fields['notices']={'ihsg':['Unexpected extra '+('n'*2200)]}
    text,presentation=core('formatting').format_brief(**fields,with_selection=True)
    assert len(text[0].encode('utf-16-le'))//2<=2000
    assert 'Outlook IHSG:\n-' in text[0] and 'long prose' not in text[0] and 'Unexpected extra' not in text[0]
    assert presentation['mode']=='facts_only' and not presentation['claims']
    assert 'Pasar global:' in text[0] and 'Agenda Ekonomi Indonesia' in text[0]


def test_hidden_source_urls_cannot_overflow_or_leak_into_main_message(core):
    fields=inputs();fields['globals'][0]['source_url']='https://example.org/'+('g'*3000)
    fields['outlook']['claims'][0]['source_url']='https://example.org/'+('c'*3000)
    text=core('formatting').format_brief(**fields)[0]
    assert 'Menurut Phintraco:' in text and 'KOSPI: +23.40' in text and len(text)<2000
    assert 'example.org' not in text


def test_source_conditions_negations_and_attribution_survive_in_one_paragraph(core):
    fields=scenario_inputs();texts,presentation=core('formatting').format_brief(**fields,with_selection=True)
    text=texts[0];paragraph=text.split('Outlook IHSG:\n')[1].split('\n\n')[0]
    assert '\n' not in paragraph and 'Menurut Phintraco:' in paragraph and 'Menurut Tuntun:' in paragraph
    assert 'Jika tekanan global bertambah, pandangan berubah.' in paragraph
    assert 'IHSG tidak bebas tekanan global.' in paragraph and paragraph.count('Jika likuiditas pulih')==1
    assert 'Skenario IHSG' not in text and 'Narasi sumber' not in text and '04/10 16:00' not in text
    assert presentation['mode']=='supported' and presentation['scenario']['pulse']['mode']=='absent'


def test_invalid_source_or_conflicting_context_falls_back_without_partial_direction(core):
    fields=scenario_inputs();fields['outlook']['scenario']['opposing'][0]['source_url']='https://invalid.org/has space'
    texts,presentation=core('formatting').format_brief(**fields,with_selection=True)
    assert 'Outlook IHSG:\n-' in texts[0] and 'Jika likuiditas pulih' not in texts[0]
    assert presentation['mode']=='facts_only' and presentation['scenario'] is None


def test_invalid_optional_fact_and_partial_tracker_stay_missing(core):
    fields=inputs();fields['outlook']['market_facts'].append(dict(label='IHSG invalid',value=float('inf'),unit='poin'))
    text=core('formatting').format_brief(**fields)[0]
    assert '**7.200**' in text and 'inf' not in text and '1W: **-**' in text


def test_safe_url_encoding_still_protects_agenda_header(core):
    fields=inputs();fields['calendar']['events'][0]['source_url']='https://www.bps.go.id/a_(b)?v=[q]'
    text=core('formatting').format_brief(**fields)[0]
    assert '[BPS](https://www.bps.go.id/a_%28b%29?v=%5Bq%5D)' in text


def test_oversized_agenda_entry_drops_whole_entry_not_other_sections(core):
    fields=inputs();fields['calendar']['events'][0]['event']='x'*2200
    text=core('formatting').format_brief(**fields)[0]
    assert 'Agenda Ekonomi Indonesia:\n-' in text and 'KOSPI: +23.40' in text and len(text)<2000


def test_timing_mismatch_rejected(core):
    fields=inputs();fields['target']=CUTOFF
    with pytest.raises(ValueError):core('formatting').format_brief(**fields)


def test_offline_six_block_preview_has_image_alt_text_but_no_extra_caption(core):
    f=core('formatting');texts=f.format_brief(**inputs())
    markdown=f.six_block_markdown(texts,[{'title':f.attachment_caption('ihsg',PUBLICATION),'path':'ihsg.png'},None,{'title':'Rotasi Konglo','path':'konglo.png'}])
    assert len(markdown.split('\n\n---\n\n'))==6 and '![IDX Composite Index](ihsg.png)' in markdown
    assert 'Cutoff' not in markdown and 'Target' not in markdown


def test_rotation_messages_are_only_dated_headings_whatever_the_basket_provenance(core):
    from test_rendering import baskets
    fields=inputs();groups=baskets(1)
    groups[0].provenance.update(cap_collection_status='stale',missing_cap_members=('YYYY',),
        cap_collected_at='2026-10-05T00:00:00+00:00',source_url='https://example.org/invalid path')
    fields['sectors']=groups;fields['konglo']=baskets(11);fields['notices']={'sectors':['Gambar belum tersedia.']}
    texts=core('formatting').format_brief(**fields)
    assert texts[1]=='### 🏭 ROTASI SEKTOR: '+core('rendering').publication_label(PUBLICATION)
    assert texts[2]=='### 🐉 ROTASI KONGLO: '+core('rendering').publication_label(PUBLICATION)
    assert all(word not in texts[1]+texts[2] for word in ('parsial','Basis','Cap ','Kekuatan','Momentum','stale','tersedia'))
