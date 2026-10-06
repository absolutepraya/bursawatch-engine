from dataclasses import asdict
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from morning_brief.host import HostConfig, HostRuntime, load_inputs, readiness
from morning_brief.runner import MorningRunner, jsonable
from morning_brief.store import RunStore
from test_operator_config import snapshot
from test_publication import DEST, FakeProjection, NOW
from test_runner import Source, HeartbeatDelivery, calendar, numerical, FREEZE


def private_json(path, value):
    path.write_text(json.dumps(jsonable(value)))
    path.chmod(0o600)
    return path


def setup_host(tmp_path):
    root = tmp_path / 'hermes'
    (root / 'hermes_cli').mkdir(parents=True)
    (root / 'hermes_cli/config.py').touch()
    fields = dict(version=1, run_store=str(tmp_path/'runs.sqlite'),
        input_manifest=str(tmp_path/'inputs.json'), hermes_root=str(root))
    for name in ('config_token_file', 'source_token_file', 'publication_token_file', 'delivery_token_file'):
        path=tmp_path/name;path.write_text('x'*48);path.chmod(0o600)
        fields[name]=str(path)
    config=HostConfig(**fields)
    cal=jsonable(calendar())
    cal['verified']=True;cal.pop('import_digest')
    path=private_json(tmp_path/'calendar.json',cal)
    inputs=dict(version=1,provenance='live-retained',available_at=(FREEZE-timedelta(minutes=1)).isoformat(),
        calendar=dict(path=str(path),version=cal['version'],amendment=cal['amendment'],
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
        numerical=numerical(),global_inputs=[],calendar_snapshots=[])
    private_json(Path(config.input_manifest),inputs)
    return config,inputs


def test_dispatcher_freezes_once_then_recovers_without_files_config_api_or_writer(tmp_path):
    config,_=setup_host(tmp_path);clock=[FREEZE+timedelta(seconds=30)]
    store=RunStore(config.run_store);source=Source();delivery=HeartbeatDelivery();projection=FakeProjection()
    runner=MorningRunner(store,source,delivery,projection,clock=lambda:clock[0])
    reads=[];models=[]
    def fetch(): reads.append(1);return snapshot()
    def writer(): models.append(1);return None,'hermes-current-model'
    host=HostRuntime(config,store,runner,fetch_snapshot=fetch,writer_factory=writer,clock=lambda:clock[0])
    assert host.tick()['phase']=='prepared'
    assert source.captures==1 and len(reads)==1 and len(models)==1
    assert not [op for op in delivery.sent if op.target['channel_id']==DEST]
    Path(config.input_manifest).unlink()
    clock[0]=NOW
    assert host.tick()['phase']=='projected'
    assert source.captures==1 and len(reads)==1 and len(models)==1
    assert len(projection.requests)==1
    clock[0]+=timedelta(hours=1)
    assert host.tick()['phase']=='projected'
    assert len(projection.requests)==1 and source.captures==1


def test_before_cutoff_and_missed_session_never_read_inputs_or_capture(tmp_path):
    config,_=setup_host(tmp_path);Path(config.input_manifest).unlink()
    clock=[FREEZE-timedelta(seconds=1)];store=RunStore(config.run_store);source=Source()
    delivery=HeartbeatDelivery();runner=MorningRunner(store,source,delivery,FakeProjection(),clock=lambda:clock[0])
    host=HostRuntime(config,store,runner,fetch_snapshot=snapshot,
        writer_factory=lambda:pytest.fail('idle tick resolved writer'),clock=lambda:clock[0])
    assert host.tick()['phase']=='before_freeze'
    clock[0]=NOW+timedelta(hours=1)
    assert host.tick()['phase']=='missed_session'
    assert source.captures==0 and store.get_run_for_session('2026-10-05') is None
    assert all(op.target['channel_id']!=DEST for op in delivery.sent)


def test_missing_live_calendar_fails_before_any_macro_message(tmp_path):
    config,_=setup_host(tmp_path);Path(config.input_manifest).unlink()
    store=RunStore(config.run_store);source=Source();delivery=HeartbeatDelivery()
    runner=MorningRunner(store,source,delivery,FakeProjection(),clock=lambda:NOW)
    result=HostRuntime(config,store,runner,fetch_snapshot=snapshot,
        writer_factory=lambda:pytest.fail('missing input resolved writer'),clock=lambda:NOW).tick()
    assert result['phase']=='fatal' and result['reason']=='FileNotFoundError'
    assert source.captures==0 and all(op.target['channel_id']!=DEST for op in delivery.sent)


def test_interrupted_preparation_restores_chart_context_without_reopening_manifest(tmp_path,monkeypatch):
    config,inputs=setup_host(tmp_path)
    inputs['chart']={'request':{'identity':'test-original'},'verification':{'evidence_ref':'test-proof'}}
    private_json(Path(config.input_manifest),inputs)
    store=RunStore(config.run_store);source=Source();delivery=HeartbeatDelivery()
    runner=MorningRunner(store,source,delivery,FakeProjection(),clock=lambda:FREEZE+timedelta(seconds=30))
    import morning_brief.host as module
    observed=[]
    def chart(config,value,cutoff):observed.append(value['chart']);return None,None
    monkeypatch.setattr(module,'chart_inputs',chart)
    original=runner._select
    monkeypatch.setattr(runner,'_select',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('interrupted')))
    host=HostRuntime(config,store,runner,fetch_snapshot=snapshot,
        writer_factory=lambda:(None,'current-model'),clock=lambda:FREEZE+timedelta(seconds=30))
    assert host.tick()['phase']=='fatal'
    Path(config.input_manifest).unlink()
    monkeypatch.setattr(runner,'_select',original)
    assert host.tick()['phase']=='prepared'
    assert observed==[inputs['chart'],inputs['chart']] and source.captures==1


@pytest.mark.parametrize('change',['preview','future','calendar_digest','public_permissions'])
def test_live_loader_rejects_unverified_or_cutoff_invisible_inputs(tmp_path,change):
    config,inputs=setup_host(tmp_path)
    if change=='preview':inputs['provenance']='synthetic-preview'
    if change=='future':inputs['available_at']=(FREEZE+timedelta(seconds=1)).isoformat()
    if change=='calendar_digest':inputs['calendar']['sha256']='0'*64
    path=private_json(Path(config.input_manifest),inputs)
    if change=='public_permissions':path.chmod(0o644)
    with pytest.raises(ValueError):load_inputs(path,cutoff=FREEZE)


def test_readiness_is_read_only_and_does_not_accept_a_bare_positive_benchmark(tmp_path):
    config,inputs=setup_host(tmp_path)
    assert readiness(config,snapshot=snapshot(),now=NOW)['ready']
    assert not Path(config.run_store).exists()
    inputs['numerical']['benchmark_attestation']={}
    private_json(Path(config.input_manifest),inputs)
    assert readiness(config,snapshot=snapshot(),now=NOW)['gaps']==['benchmark_unavailable']
    assert not Path(config.run_store).exists()


def test_native_current_model_router_is_used_without_pinning_or_sdk_retries(tmp_path,monkeypatch):
    config,_=setup_host(tmp_path)
    import morning_brief.hermes_writer as module
    seen=[]
    client=SimpleNamespace(max_retries=2,chat=SimpleNamespace(completions=SimpleNamespace()))
    def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"claims":[],"scenario":null}'))])
    client.chat.completions.create=create
    def resolve(provider,**kwargs):
        assert provider=='azure-foundry' and kwargs=={'model':'current-hermes-model'}
        return client,'current-hermes-model'
    monkeypatch.setitem(sys.modules,'hermes_cli.config',SimpleNamespace(load_config_readonly=lambda:{'model':{'provider':'azure-foundry','default':'current-hermes-model'}}))
    monkeypatch.setitem(sys.modules,'agent.auxiliary_client',SimpleNamespace(resolve_provider_client=resolve))
    monkeypatch.setitem(sys.modules,'utils',SimpleNamespace(model_forces_max_completion_tokens=lambda _:False))
    writer,version=module.current_writer(config.hermes_root)
    assert version=='current-hermes-model' and client.max_retries==0 and seen==[]
    assert writer({'claim_contract':{},'evidence':[]})=={'claims':[],'scenario':None}
    assert len(seen)==1 and seen[0]['timeout']==30 and seen[0]['max_tokens']==3000
    assert 'tools' not in seen[0] and seen[0]['model']==version


def test_changed_model_cannot_relabel_frozen_writer_bundle(tmp_path):
    config,_=setup_host(tmp_path);store=RunStore(config.run_store)
    source=Source();delivery=HeartbeatDelivery();projection=FakeProjection()
    runner=MorningRunner(store,source,delivery,projection,clock=lambda:NOW)
    run=store.create_run('2026-10-05',freeze_at=FREEZE)
    lease=store.acquire_lease(run.run_id,'interrupted',now=NOW)
    store.freeze(run.run_id,'operator_config',snapshot(),lease=lease,now=NOW)
    from morning_brief.outlook import freeze_bundle
    freeze_bundle(store,run.run_id,model_version='previous-model',prompt_version='source-scenario-v2',lease=lease,now=NOW)
    store.release_lease(lease,now=NOW)
    host=HostRuntime(config,store,runner,fetch_snapshot=lambda:pytest.fail('config read on recovery'),
        writer_factory=lambda:(lambda _:pytest.fail('changed writer called'),'current-model'),clock=lambda:NOW)
    assert host.tick()['phase']=='projected'
    assert store.get_frozen(run.run_id,'writer_bundle').payload['versions']['model']=='previous-model'
