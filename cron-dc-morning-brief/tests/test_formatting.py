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


def test_optional_prose_removed_whole_sources_survive(core):
    values=inputs();values['outlook']['claims']=[{'excerpt':'long prose '*250,'publisher_id':'Phintraco','source_url':f'https://example.org/source/{i}'} for i in range(3)]
    values['notices']={'ihsg':['Notice '+('n'*2200)]}
    text=core('formatting').format_brief(**values)[0]
    assert len(text)<=2000
    assert all(f'https://example.org/source/{i}' in text for i in range(3))
    assert 'long prose' not in text
    assert text==core('formatting').format_brief(**values)[0]


def test_missing_logos_and_unavailable_inputs(core):
    values=inputs(); values.update(globals=[],calendar={'events':[],'unavailable':[{'source_url':'https://www.bi.go.id/id/publikasi/ruang-media/agenda-kegiatan/'}]},outlook={'mode':'facts_only','claims':[],'market_facts':[]})
    text=core('formatting').format_brief(**values)[0]
    assert 'belum tersedia' in text and '<:kospi' not in text
    assert 'https://www.bi.go.id/id/publikasi/ruang-media/agenda-kegiatan/' in text


def test_overlong_required_facts_fail_without_cutting_links(core):
    values=inputs();values['globals'][0]['source_url']='https://example.org/'+('x'*2100)
    with pytest.raises(core('formatting').MessageTooLong):core('formatting').format_brief(**values)


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
    with pytest.raises(f.MessageTooLong):f.format_brief(**values)
