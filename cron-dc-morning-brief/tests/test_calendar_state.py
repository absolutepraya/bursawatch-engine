import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
import pytest

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def calendar_file(tmp_path):
    path = tmp_path / 'calendar.json'
    path.write_text(json.dumps(dict(version='idx-2026-v2', amendment='amend-2', authority='IDX', source_url='https://www.idx.co.id/calendar', source_digest='a'*64, verified=True, amendment_checked_at='2026-10-04T00:00:00+00:00', valid_from='2026-09-01', valid_through='2026-10-31', sessions=['2026-09-21','2026-09-22','2026-09-23','2026-09-24','2026-09-25','2026-09-29','2026-09-30','2026-10-01','2026-10-02','2026-10-06','2026-10-07'])) )
    return path


def test_calendar_uses_verified_sessions_not_weekdays(core, tmp_path):
    m = core('calendar')
    cal = m.SessionCalendar.from_file(calendar_file(tmp_path), expected_version='idx-2026-v2', expected_amendment='amend-2', as_of=NOW)
    assert not cal.is_session(date(2026,10,5))
    assert cal.first_session_of_week(date(2026,10,7)) == date(2026,10,6)
    assert cal.first_session_of_week(date(2026,10,1)) == date(2026,9,29)
    assert cal.last_sessions(date(2026,10,2),3) == (date(2026,9,30),date(2026,10,1),date(2026,10,2))
    with pytest.raises(ValueError): cal.last_sessions(date(2026,10,2),18)
    with pytest.raises(ValueError): cal.is_session(date(2027,1,1))
    with pytest.raises(ValueError): m.SessionCalendar.from_file(calendar_file(tmp_path), expected_version='old', expected_amendment='amend-2', as_of=NOW)
    path = calendar_file(tmp_path); payload=json.loads(path.read_text()); payload['verified']=False; path.write_text(json.dumps(payload))
    with pytest.raises(ValueError): m.SessionCalendar.from_file(path, expected_version='idx-2026-v2', expected_amendment='amend-2', as_of=NOW)


def test_config_offline_explicit_paths_and_no_store_io(core,tmp_path):
    m=core('config')
    config=m.MorningConfig(tmp_path/'run.sqlite3',tmp_path/'provider.sqlite3')
    assert config.mode=='cache_only'
    assert not config.run_store_path.exists()
    with pytest.raises(ValueError): m.MorningConfig(tmp_path/'same',tmp_path/'same')
    with pytest.raises(ValueError): m.MorningConfig(tmp_path/'r',tmp_path/'p',mode='live')
    assert m.MorningConfig.from_mapping({'run_store_path':str(tmp_path/'r'),'sectors_store_path':str(tmp_path/'p')}).mode=='cache_only'
    with pytest.raises(ValueError): m.MorningConfig.from_mapping({'run_store_path':'r','sectors_store_path':'p','api_key':'ignored-is-dangerous'})


def test_store_restart_freezes_and_fenced_session_lease(core,tmp_path):
    m=core('store'); path=tmp_path/'run.sqlite3'
    store=m.RunStore(path)
    run=store.create_run('2026-10-06', freeze_at=NOW, run_id='run-1')
    lease=store.acquire_lease(run.run_id,'worker-1',now=NOW,seconds=60)
    with pytest.raises(m.LeaseBusy): store.acquire_lease(run.run_id,'worker-2',now=NOW,seconds=60)
    frozen=store.freeze(run.run_id,'inputs', {'calendar':'v2','manifest':'explicit-manifest'}, lease=lease, now=NOW)
    assert frozen.digest == '6756e4178b50388ec0ef7fea826301828c2f41a54b0c0fdf74520fc82327ec6b'
    assert store.freeze(run.run_id,'inputs', {'manifest':'explicit-manifest','calendar':'v2'},lease=lease,now=NOW).digest==frozen.digest
    with pytest.raises(m.FreezeConflict): store.freeze(run.run_id,'inputs',{'calendar':'corrected'},lease=lease,now=NOW)
    reopened=m.RunStore(path)
    assert reopened.get_frozen(run.run_id,'inputs').payload=={'calendar':'v2','manifest':'explicit-manifest'}
    assert reopened.create_run('2026-10-06',freeze_at=NOW,run_id='other').run_id=='run-1'
    with pytest.raises(m.FreezeConflict): reopened.create_run('2026-10-06',freeze_at=NOW+timedelta(seconds=1),run_id='other')
    later=NOW+timedelta(seconds=61)
    next_lease=reopened.acquire_lease(run.run_id,'worker-2',now=later,seconds=60)
    assert next_lease.generation>lease.generation
    with pytest.raises(m.LeaseLost): store.freeze(run.run_id,'text',{'body':'stale'},lease=lease,now=later)
    record=reopened.freeze(run.run_id,'text',{'digest':'b'*64,'operation_key':'op-1','dependencies':{'inputs':frozen.digest}},lease=next_lease,now=later,dependencies={'inputs':frozen.digest})
    with pytest.raises(m.FreezeConflict): reopened.freeze(run.run_id,'image',{},lease=next_lease,now=later,dependencies={'inputs':'c'*64})
    reopened.append_receipt(run.run_id,'text',operation_key='op-1',payload_digest='b'*64,receipt={'state':'accepted'},lease=next_lease,now=later)
    with pytest.raises(m.FreezeConflict): reopened.append_receipt(run.run_id,'text',operation_key='wrong',payload_digest='b'*64,receipt={'state':'accepted'},lease=next_lease,now=later)
    reopened.transition(run.run_id,'frozen',lease=next_lease,now=later,fallback_reason='history_incomplete')
    assert reopened.get_run(run.run_id).fallback_reason=='history_incomplete'
    reopened.set_checkpoint(run.run_id,'publication','projected',lease=next_lease,now=later)
    assert reopened.get_checkpoint(run.run_id,'publication')=='projected'
    with sqlite3.connect(path) as db:
        with pytest.raises(sqlite3.IntegrityError): db.execute("UPDATE freezes SET payload='{}'")
    assert record.dependencies=={'inputs':frozen.digest}


def test_lease_renewal_and_immutable_receipt_readback(core,tmp_path):
    m=core('store');store=m.RunStore(tmp_path/'state.sqlite3')
    run=store.create_run('2026-10-06',freeze_at=NOW)
    lease=store.acquire_lease(run.run_id,'worker',now=NOW,seconds=2)
    renewal=store.renew_lease(lease,now=NOW+timedelta(seconds=1),seconds=10)
    with pytest.raises(m.LeaseBusy):store.acquire_lease(run.run_id,'other',now=NOW+timedelta(seconds=3))
    store.freeze(run.run_id,'text',{'operation_key':'stable-op','digest':'a'*64},lease=renewal,now=NOW+timedelta(seconds=3))
    store.append_receipt(run.run_id,'text',operation_key='stable-op',payload_digest='a'*64,receipt={'state':'pending'},lease=renewal,now=NOW+timedelta(seconds=3))
    store.append_receipt(run.run_id,'text',operation_key='stable-op',payload_digest='a'*64,receipt={'state':'accepted'},lease=renewal,now=NOW+timedelta(seconds=4))
    assert m.RunStore(store.path).get_receipts(run.run_id,'text')==({'state':'pending'},{'state':'accepted'})
    with pytest.raises(m.LeaseLost):store.renew_lease(renewal,now=NOW+timedelta(seconds=11))


def test_import_is_side_effect_free(core,tmp_path):
    import subprocess,sys
    root=__import__('pathlib').Path(__file__).resolve().parents[2]
    code='import sys;sys.path.insert(0,'+repr(str(root/'cron-dc-morning-brief/bin'))+');import morning_brief.config,morning_brief.store,morning_brief.inputs,morning_brief.rotation,morning_brief.calendar'
    subprocess.run([sys.executable,'-B','-c',code],cwd=tmp_path,check=True)
    assert not list(tmp_path.iterdir())


def test_store_refuses_symlink_or_unknown_schema(core,tmp_path):
    m=core('store');target=tmp_path/'target.sqlite3';target.write_bytes(b'')
    link=tmp_path/'link.sqlite3';link.symlink_to(target)
    with pytest.raises(ValueError):m.RunStore(link)
    path=tmp_path/'new.sqlite3'
    with sqlite3.connect(path) as db:db.execute('PRAGMA user_version=999')
    with pytest.raises(ValueError):m.RunStore(path)
