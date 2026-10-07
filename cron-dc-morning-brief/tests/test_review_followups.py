"""Regression coverage for the five external PR review findings, no live IO."""
from datetime import timedelta
import pytest
from test_evidence import source, owner, LOWER, FREEZE, FlakyCapture
from test_economic_calendar import saved, page
from test_runner import calendar, numerical, Source, HeartbeatDelivery
from test_publication import NOW, FakeProjection


@pytest.mark.parametrize('text,relevant', [
    ('ihsg melemah.', True), ('JKSE menguat.', True), ('JCI stabil.', True),
    ('Jakarta Composite Index bergerak terbatas.', True), ('IDX Composite turun.', True),
    ('IHSGX naik.', False), ('Bahan composite baru.', False),
    ('Nasdaq Composite melemah.', False), ('Berita olahraga hari ini.', False),
])
def test_only_whole_ihsg_aliases_enter_the_bundle(core, text, relevant):
    result=core('evidence').select_evidence([source(1,text=text)])
    assert bool(result['items']) is relevant
    assert result['degraded_reasons']==[]
    if not relevant: assert result['omissions']=={'irrelevant':1}


def test_recent_stories_win_both_total_and_publisher_caps(core):
    rows=[source(i+1,publisher=str(i),text=f'IHSG berita {i}',
                 published_at=(FREEZE-timedelta(minutes=40-i)).isoformat()) for i in range(40)]
    selected=core('evidence').select_evidence(rows)
    assert [x['event_key'] for x in selected['items']]==[x['event_key'] for x in reversed(rows[10:])]
    assert core('evidence').select_evidence(list(reversed(rows)))==selected
    for row in rows: row['publisher_id']='same'
    assert [x['event_key'] for x in core('evidence').select_evidence(rows)['items']]==[x['event_key'] for x in reversed(rows[-3:])]


def test_ambiguous_capture_failure_freezes_unavailable_without_new_snapshot(core,tmp_path):
    store,run,lease=owner(core,tmp_path)
    client=FlakyCapture(store,run.run_id,[source(1,text='IHSG pandangan baru')],failures=1)
    module=core('evidence')
    result=module.freeze_source_evidence(store,run.run_id,client,previous_cutoff=LOWER,lease=lease,now=FREEZE)
    assert client.calls==1 and result.payload['facts_only'] and result.payload['items']==[]
    assert store.get_frozen(run.run_id,'source_manifest').payload['status']=='unavailable'
    assert module.freeze_source_evidence(store,run.run_id,client,previous_cutoff=LOWER,lease=lease,now=FREEZE).digest==result.digest
    assert client.calls==1


def test_explicit_joint_release_is_one_event_with_both_authority_links(core,tmp_path):
    module=core('economic_calendar'); cache=module.SnapshotCache(tmp_path/'cache')
    rows=[['2026-10-06','Inflasi','September 2026','09:00','joint-1',1,'nasional']]
    bps=saved(module,cache,page(rows)); bi=saved(module,cache,page(rows),authority='BI')
    result=module.select_calendar_events([bps,bi],freeze_at=FREEZE)
    assert len(result['events'])==1
    rendered=module.format_calendar_events(result)
    assert bps['source_url'] in rendered and bi['source_url'] in rendered
    assert module.select_calendar_events([bi,bps],freeze_at=FREEZE)==result
    other=saved(module,cache,page([['2026-10-06','PDB','Q3 2026','09:00','different-id',1,'nasional']]),authority='BI')
    assert len(module.select_calendar_events([bps,other],freeze_at=FREEZE)['events'])==2


def test_runner_freezes_provisioned_logos_and_reuses_them_after_restart(core,tmp_path):
    from test_global_markets import chart, schedule, US_ROWS
    module=core('runner'); store=core('store').RunStore(tmp_path/'runs.sqlite')
    globals=[dict(name='QQQ',payload=chart('QQQ','America/New_York',[s for s,e in US_ROWS[:2]],[100,102]),
                  retrieved_at=FREEZE.isoformat(),sessions=schedule('America/New_York',US_ROWS))]
    runner=module.MorningRunner(store,Source(),HeartbeatDelivery(),FakeProjection(),clock=lambda:NOW)
    markup='<:qqq:123456789012345678>'
    args=dict(calendar=calendar(),numerical=numerical(),global_inputs=globals,calendar_snapshots=[],
              model=None,model_version='fixture',prompt_version='v1',logos={'QQQ':markup})
    assert runner.run(**args)['phase']=='preview'
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    first=store.get_frozen(run.run_id,'selection')
    assert markup in first.payload['texts'][0]
    args['logos']={'QQQ':'<:new:123456789012345679>'}
    assert runner.run(**args)['phase']=='preview'
    assert store.get_frozen(run.run_id,'selection').digest==first.digest
    assert store.get_frozen(run.run_id,'upstream').payload['logos']=={'QQQ':markup}


def test_missing_publication_time_uses_observation_instant(core):
    old=source(1,text='IHSG lama',published_at='2026-10-04T00:00:00+00:00')
    new=source(2,text='IHSG baru',published_at=None,observed_at='2026-10-05T07:29:00+07:00')
    assert [r['event_key'] for r in core('evidence').select_evidence([old,new])['items']]==[new['event_key'],old['event_key']]


def test_unrelated_items_do_not_consume_publisher_capacity_or_degrade(core):
    unrelated=[source(i,text=f'Nasdaq Composite berita {i}',text_truncated=True) for i in range(4)]
    result=core('evidence').select_evidence(unrelated+[source(10,text='IHSG relevan')])
    assert len(result['items'])==1 and result['omissions']=={'irrelevant':4}
    assert result['degraded_reasons']==[]


def test_joint_dedup_precedes_three_event_limit_and_keeps_periods(core,tmp_path):
    module=core('economic_calendar'); cache=module.SnapshotCache(tmp_path/'cache')
    bps=saved(module,cache,page([
        ['2026-10-06','Inflasi','September 2026','09:00','joint',1,'nasional'],
        ['2026-10-07','Neraca perdagangan','September 2026','09:00','trade',1,'nasional'],
        ['2026-10-08','PDB','Q3 2026','09:00','gdp',1,'nasional'],
    ]))
    bi=saved(module,cache,page([['2026-10-06','Cadangan devisa','Oktober 2026','09:00','joint',1,'nasional']]),authority='BI')
    result=module.select_calendar_events([bps,bi],freeze_at=FREEZE)
    assert [e['date'] for e in result['events']]==['2026-10-06','2026-10-07','2026-10-08']
    assert result['events'][0]['reference_period']=='Oktober 2026 / September 2026'
    assert len(result['events'][0]['sources'])==2
