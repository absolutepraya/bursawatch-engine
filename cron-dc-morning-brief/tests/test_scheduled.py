from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from morning_brief.scheduled import ProducerConfig, ScheduledRuntime
from test_host import setup_host
from test_operator_config import snapshot
from test_runner import FREEZE


def setup(tmp_path,now,*,operator=None,frozen=False):
    tmp_path=tmp_path/('host-'+str(len(list(tmp_path.iterdir()))));tmp_path.mkdir()
    config,inputs=setup_host(tmp_path);calls=[]
    def tick(**kwargs):calls.append(('dispatcher',kwargs));return dict(phase='prepared')
    def beat(value):calls.append(('beat',value));return value
    host=SimpleNamespace(config=config,store=SimpleNamespace(
        get_run_for_session=lambda _:SimpleNamespace(run_id='existing') if frozen else None,
        get_frozen=lambda *_:object() if frozen else None),tick=tick,beat=beat,
        fetch_snapshot=lambda:operator or snapshot())
    producer=ProducerConfig(1,inputs['calendar']['path'],str(tmp_path/'references.json'),str(tmp_path/'sources'))
    def rotation(**kwargs):calls.append(('rotation',kwargs));return dict(manifest_written=True,gaps=[])
    def public(*args,**kwargs):calls.append(('public',kwargs));return dict(manifest_written=True,gaps=[],incomplete_sections=[])
    runtime=ScheduledRuntime(host,producer,collect_rotation=rotation,collect_public=public,
        load_memberships=lambda _:dict(explicit=True),clock=lambda:now)
    return runtime,calls


def test_early_tick_prepares_bounded_rotation_without_quotes_capture_or_dispatch(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE-timedelta(hours=2))
    assert runtime.tick()['phase']=='input_preparation'
    assert [name for name,_ in calls]==['rotation','beat']
    assert calls[0][1]['cutoff']==FREEZE


def test_quote_collection_is_near_database_configured_cutoff(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE-timedelta(minutes=5))
    assert runtime.tick()['phase']=='input_preparation'
    assert [name for name,_ in calls]==['rotation','public','beat']
    assert calls[1][1]['rotation_snapshot'] is None
    runtime,calls=setup(tmp_path,FREEZE-timedelta(minutes=5),operator=snapshot(cutoff_time='09:30',delivery_time='10:00'))
    assert runtime.tick()['phase']=='input_preparation'
    assert [name for name,_ in calls]==['rotation','beat']
    assert calls[0][1]['cutoff'].hour==9


def test_cutoff_and_frozen_recovery_never_fetch_sources(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE)
    assert runtime.tick()['phase']=='prepared'
    assert [name for name,_ in calls]==['dispatcher']
    assert calls[0][1]['operator_snapshot']['config']['cutoff_time']=='07:30'
    runtime,calls=setup(tmp_path,FREEZE-timedelta(minutes=5),frozen=True)
    runtime.host.fetch_snapshot=lambda:pytest.fail('frozen recovery must not reread operator config')
    assert runtime.tick()['phase']=='prepared'
    assert calls==[('dispatcher',{})]


def test_non_session_never_collects_or_dispatches(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE+timedelta(days=1,minutes=-5),operator=snapshot(delivery_days='idx_sessions'))
    result=runtime.tick()
    assert result==dict(phase='no_op',reason='non_session')
    assert [name for name,_ in calls]==['beat']


def test_missing_calendar_stays_fatal_without_guessing_weekdays(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE-timedelta(minutes=5),operator=snapshot(delivery_days='idx_sessions'))
    Path(runtime.producer.calendar_snapshot).unlink()
    assert runtime.tick()['phase']=='fatal'
    assert [name for name,_ in calls]==['beat']


def test_producer_crossing_cutoff_cannot_start_quote_fetch(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE-timedelta(seconds=10))
    clock=iter([FREEZE-timedelta(seconds=10),FREEZE+timedelta(seconds=1)])
    runtime.clock=lambda:next(clock)
    assert runtime.tick()['phase']=='input_preparation'
    assert [name for name,_ in calls]==['rotation','beat']


def test_optional_rotation_failure_does_not_block_core_quote_collection(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE-timedelta(minutes=5))
    def broken(**kwargs):raise ValueError('synthetic missing membership reference')
    runtime.rotation=broken
    result=runtime.tick()
    assert result['phase']=='input_preparation' and result['gaps']==1
    assert [name for name,_ in calls]==['public','beat']
    assert result['producer']['rotation']['gaps']==['rotation:ValueError']


def test_weekday_missing_calendar_still_collects_globals_without_rotation(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE-timedelta(minutes=5))
    Path(runtime.producer.calendar_snapshot).unlink()
    result=runtime.tick()
    assert result['phase']=='input_preparation' and result['gaps']==1
    assert [name for name,_ in calls]==['public','beat']


def test_weekend_never_collects_or_dispatches_even_with_missing_calendar(tmp_path):
    runtime,calls=setup(tmp_path,FREEZE+timedelta(days=5))
    Path(runtime.producer.calendar_snapshot).unlink()
    assert runtime.tick()==dict(phase='no_op',reason='weekend')
    assert [name for name,_ in calls]==['beat']
