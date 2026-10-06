from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from morning_brief.config import default_operator_config, load_operator_config_data, timing_for
from morning_brief.store import RunStore, digest
from test_runner import Source, HeartbeatDelivery, calendar
from test_publication import FakeProjection, DEST

ZONE = ZoneInfo('Asia/Jakarta')

def snapshot(**changes):
    config=default_operator_config()
    config.update(destination_channel_id=DEST, **changes)
    return dict(api_version=1,watcher_id='bursawatch-dc-morning-brief',revision=1,
        config_version=1,config=config,config_sha256=digest(config),updated_at='2026-10-05T05:00:00+07:00')

@pytest.mark.parametrize('changes',[
    {'cutoff_time':'7:00'}, {'delivery_time':'06:05'}, {'retry_minutes':True},
    {'timezone':'UTC'}, {'instruments':['SPY','SPY']}, {'instruments':['UNKNOWN']},
    {'delivery_time':'23:55'}, {'logos':{'SPY':':spy:'}}, {'extra':'ignored'},
    {'destination_channel_id':'no'}, {'fallback_minutes':0},
])
def test_invalid_operator_settings_fail_closed(changes):
    with pytest.raises(ValueError): load_operator_config_data({**default_operator_config(),**changes})

def test_defaults_and_optional_emoji_are_durable_data():
    config=default_operator_config();config['logos']={'SPY':None}
    times=timing_for(datetime(2026,10,5).date(),config)
    assert [times[k].strftime('%H:%M') for k in ['cutoff','fallback','target','deadline']]==['07:30','07:55','08:00','08:15']
    assert load_operator_config_data(config)['logos']['SPY'] is None

def test_database_snapshot_freezes_timing_and_delivery_waits_until_target(tmp_path,core):
    r=core('runner');now=[datetime(2026,10,5,6,0,30,tzinfo=ZONE)]
    store=RunStore(tmp_path/'runs.sqlite');source=Source();delivery=HeartbeatDelivery();projection=FakeProjection()
    runner=r.MorningRunner(store,source,delivery,projection,clock=lambda:now[0])
    args=dict(calendar=calendar(),numerical={},global_inputs=[{'name':'KOSPI','payload':'unselected-invalid'}],
        calendar_snapshots=[],model=None,model_version='fixture',prompt_version='fixture',preview=False)
    first=snapshot(cutoff_time='06:00',delivery_time='07:00',instruments=['SPY'],logos={'SPY':'<:spy:123456789012345678>'})
    assert runner.run_from_snapshot(first,**args)['phase']=='prepared'
    assert source.captures==1 and not projection.requests
    assert all(op.target['channel_id']!=DEST for op in delivery.sent)
    run=store.get_run_for_session('2026-10-05')
    assert store.get_frozen(run.run_id,'operator_config').payload['revision']==1
    assert store.get_frozen(run.run_id,'writer_bundle').payload['fallback_at'].startswith('2026-10-05T06:55:00')
    selected=store.get_frozen(run.run_id,'selection')
    assert '06:00 WIB' in selected.payload['texts'][0] and '07:00 WIB' in selected.payload['texts'][0]
    operation=store.get_frozen(run.run_id,'operation:ihsg_text')
    assert datetime.fromisoformat(operation.payload['attempt_deadline']).astimezone(ZONE).strftime('%H:%M')=='07:15'
    now[0]=now[0].replace(hour=7,minute=1)
    changed=snapshot(cutoff_time='06:15',delivery_time='07:30',instruments=['EIDO'])
    changed['revision']=2
    assert runner.run_from_snapshot(changed,**args)['phase']=='projected'
    assert len(projection.requests)==1 and source.captures==1
    assert projection.requests[0]['config_revision']==1
    assert store.get_frozen(run.run_id,'selection').digest==selected.digest
    assert store.get_frozen(run.run_id,'operator_config').payload==first

def test_snapshot_checksum_and_owner_are_required(tmp_path,core):
    runner=core('runner').MorningRunner(RunStore(tmp_path/'runs'),Source(),HeartbeatDelivery(),FakeProjection(),clock=lambda:datetime.now(ZONE))
    invalid=snapshot();invalid['config']['delivery_time']='07:30'
    from control_plane_client import ControlPlaneContractError
    with pytest.raises(ControlPlaneContractError): runner.run_from_snapshot(invalid)
    invalid=snapshot();invalid['watcher_id']='bursawatch-other'
    with pytest.raises(ValueError): runner.run_from_snapshot(invalid)

def test_control_plane_read_failure_never_uses_local_settings(tmp_path,core,monkeypatch):
    import control_plane_client
    def unavailable(*args,**kwargs): raise RuntimeError('private upstream error')
    monkeypatch.setattr(control_plane_client,'fetch_config',unavailable)
    delivery=HeartbeatDelivery();source=Source()
    runner=core('runner').MorningRunner(RunStore(tmp_path/'runs'),source,delivery,FakeProjection(),clock=lambda:datetime.now(ZONE))
    result=runner.run_from_control_plane(base_url='https://example.test',token='fake-test-token',preview=True)
    assert result['phase']=='fatal' and result['reason']=='RuntimeError'
    assert not delivery.sent and source.captures==0 and 'private' not in result['heartbeat']['text']


def test_cutoff_edit_uses_previous_sessions_actual_freeze(tmp_path,core):
    class RecordingSource(Source):
        def capture_window(self,previous,cutoff,limit=1000):
            self.previous=previous
            return super().capture_window(previous,cutoff,limit)
    store=RunStore(tmp_path/'runs')
    prior=datetime(2026,10,4,5,30,tzinfo=ZONE)
    store.create_run('2026-10-04',freeze_at=prior)
    source=RecordingSource()
    runner=core('runner').MorningRunner(store,source,HeartbeatDelivery(),FakeProjection(),clock=lambda:datetime(2026,10,5,7,30,30,tzinfo=ZONE))
    result=runner.run_from_snapshot(snapshot(),calendar=calendar(),numerical={},global_inputs=[],calendar_snapshots=[],model=None,model_version='fixture',prompt_version='fixture',preview=True)
    assert result['phase']=='preview'
    assert datetime.fromisoformat(source.previous)==prior
