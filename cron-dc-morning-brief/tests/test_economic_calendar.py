"""Synthetic official-page shapes; dates do not claim live upcoming events."""
from datetime import datetime
import pytest

FREEZE = datetime.fromisoformat('2026-10-05T07:30:00+07:00')
BPS = 'https://www.bps.go.id/id/arc'
BI = 'https://www.bi.go.id/id/publikasi/ruang-media/news-release/Pages/sp_2730825.aspx'


def page(rows):
    cells = ['Tanggal','Kegiatan','Periode','Waktu','ID Rilis','Revisi','Cakupan']
    return '<html><table><tr>'+''.join('<th>'+c+'</th>' for c in cells)+'</tr>'+''.join('<tr>'+''.join('<td>'+str(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</table></html>'


def saved(module, cache, html, authority='BPS', **changes):
    fields = dict(authority=authority,source_url=BPS if authority=='BPS' else BI,html=html,
                  retrieved_at='2026-10-04T12:00:00+07:00',verified_at='2026-10-04T12:15:00+07:00',
                  amendment='synthetic-a1',verified=True,decision_day=None)
    fields.update(changes)
    return cache.put(**fields)


def test_verified_future_events_amend_deduplicate_and_select_next_three_across_dates(core,tmp_path):
    module = core('economic_calendar')
    cache = module.SnapshotCache(tmp_path/'calendars')
    bps = saved(module,cache,page([
        ['2026-10-06','Inflasi','September 2026','09:00','joint-1',1,'nasional'],
        ['2026-10-07','Inflasi','September 2026','10:00','joint-1',2,'nasional'],
        ['2026-10-07','Neraca perdagangan','September 2026','10:00','joint-1',2,'nasional'],
        ['2026-10-09','PDB','Q3 2026','','gdp-1',1,'nasional'],
        ['2026-10-10','Tenaga kerja','Agustus 2026','09:00','labor-1',1,'nasional'],
        ['2026-10-06','Inflasi provinsi','September 2026','09:00','local-1',1,'provinsi'],
        ['2026-10-04','Inflasi','Agustus 2026','09:00','past-1',1,'nasional'],
    ]))
    bi = saved(module,cache,page([['2026-10-05 s.d. 2026-10-06','RDG BI-Rate','Oktober 2026','','rdg-1',1,'nasional']]),authority='BI',decision_day='last')
    result = module.select_calendar_events([bps,bi],freeze_at=FREEZE)
    assert [e['date'] for e in result['events']] == ['2026-10-06','2026-10-07','2026-10-09']
    assert result['events'][0]['decision_day'] is True
    assert result['events'][0]['time_wib'] is None and result['events'][2]['time_wib'] is None
    assert 'Neraca perdagangan' in result['events'][1]['event'] and 'Inflasi' in result['events'][1]['event']
    assert result['events'][1]['revision'] == 2
    assert all(e['source_url'].startswith('https://www.') for e in result['events'])
    rendered = module.format_calendar_events(result)
    assert 'jam belum diumumkan' in rendered and 'konsensus' not in rendered.casefold()


@pytest.mark.parametrize('mutation', ['dynamic_empty','unverified','future_verification','future_retrieval','stale','unknown_meeting_day'])
def test_unknown_calendar_or_timing_is_unavailable_not_invented(core,tmp_path,mutation):
    module = core('economic_calendar')
    cache = module.SnapshotCache(tmp_path/'cache')
    html = page([['2026-10-06','Inflasi','September 2026','','release-1',1,'nasional']])
    fields = {}
    if mutation=='dynamic_empty': html='<html><div id="app"></div></html>'
    elif mutation=='unverified': fields['verified']=False
    elif mutation=='future_verification': fields['verified_at']='2026-10-05T07:30:01+07:00'
    elif mutation=='future_retrieval': fields['retrieved_at']='2026-10-05T07:30:01+07:00'; fields['verified_at']='2026-10-05T07:30:02+07:00'
    elif mutation=='stale': fields.update(retrieved_at='2026-09-01T00:00:00+07:00',verified_at='2026-09-01T00:00:00+07:00')
    elif mutation=='unknown_meeting_day': html=page([['2026-10-06 s.d. 2026-10-07','RDG BI-Rate','Oktober 2026','','rdg-1',1,'nasional']]); fields['authority']='BI'
    snapshot=saved(module,cache,html,**fields)
    result=module.select_calendar_events([snapshot],freeze_at=FREEZE)
    assert result['events']==[] and result['unavailable']


def test_unknown_same_day_time_is_excluded_until_future_date_is_verified(core,tmp_path):
    module=core('economic_calendar')
    cache=module.SnapshotCache(tmp_path/'cache')
    snapshot=saved(module,cache,page([
        ['2026-10-05','Inflasi','September 2026','','same-day',1,'nasional'],
        ['2026-10-05','PDB','Q3 2026','08:00','future-time',1,'nasional'],
        ['2026-10-05','Tenaga kerja','Agustus 2026','07:00','past-time',1,'nasional'],
    ]))
    result=module.select_calendar_events([snapshot],freeze_at=FREEZE)
    assert [e['event_id'] for e in result['events']]==['BPS:future-time']


def test_snapshot_bytes_immutable_cached_across_runs_and_wrong_source_rejected(core,tmp_path):
    module=core('economic_calendar')
    cache=module.SnapshotCache(tmp_path/'cache')
    html=page([['6 Oktober 2026','Inflasi','September 2026','','release-1',1,'nasional']])
    first=saved(module,cache,html)
    second=saved(module,cache,html,retrieved_at='2026-10-05T07:00:00+07:00',verified_at='2026-10-05T07:05:00+07:00')
    assert first['source_digest']==second['source_digest'] and first['snapshot_digest']!=second['snapshot_digest']
    assert len(list((tmp_path/'cache').glob('*.html')))==1
    assert cache.get(first['snapshot_digest'])==first
    assert first['retrieved_at']=='2026-10-04T05:00:00+00:00'
    with pytest.raises(ValueError): saved(module,cache,html,source_url='https://example.com/bps')
    result=module.select_calendar_events([first],freeze_at=FREEZE)
    assert result['events'][0]['date']=='2026-10-06'


def test_amendment_to_past_removes_old_future_date_before_filtering(core,tmp_path):
    module=core('economic_calendar')
    snapshot=saved(module,module.SnapshotCache(tmp_path/'cache'),page([
        ['2026-10-06','Inflasi','September 2026','09:00','amended',1,'nasional'],
        ['2026-10-04','Inflasi','September 2026','09:00','amended',2,'nasional'],
    ]))
    assert module.select_calendar_events([snapshot],freeze_at=FREEZE)['events']==[]


def test_frozen_calendar_recovery_reuses_original_snapshot_not_new_amendment(core,tmp_path):
    from test_evidence import owner
    module=core('economic_calendar'); store,run,lease=owner(core,tmp_path)
    cache=module.SnapshotCache(tmp_path/'cache')
    first=saved(module,cache,page([['2026-10-06','Inflasi','September 2026','','release',1,'nasional']]))
    record=module.freeze_calendar_events(store,run.run_id,[first],lease=lease,now=FREEZE)
    amended=saved(module,cache,page([['2026-10-07','Inflasi','September 2026','','release',2,'nasional']]),amendment='synthetic-a2')
    recovered=module.freeze_calendar_events(store,run.run_id,[amended],lease=lease,now=FREEZE)
    assert recovered.digest==record.digest and recovered.payload['events'][0]['date']=='2026-10-06'


def test_joint_briefing_keeps_each_reference_period(core,tmp_path):
    module=core('economic_calendar'); cache=module.SnapshotCache(tmp_path/'cache')
    bps=saved(module,cache,page([
        ['2026-10-06','Inflasi','September 2026','09:00','joint',1,'nasional'],
        ['2026-10-06','PDB','Q3 2026','09:00','joint',1,'nasional'],
    ]))
    result=module.select_calendar_events([bps],freeze_at=FREEZE)
    assert result['events'][0]['reference_period']=='Q3 2026 / September 2026'


def test_rdg_start_alone_is_not_a_verified_decision_day(core,tmp_path):
    module=core('economic_calendar'); cache=module.SnapshotCache(tmp_path/'cache')
    bi=saved(module,cache,page([['2026-10-06','RDG BI-Rate','Oktober 2026','','rdg',1,'nasional']]),authority='BI')
    result=module.select_calendar_events([bi],freeze_at=FREEZE)
    assert result['events']==[] and result['unavailable']
