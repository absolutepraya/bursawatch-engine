"""Restart contracts through the real scheduler, host, runner and temporary store.

Only external producers, source evidence, model resolution and delivery are fake.
No production factory, credential, scheduler or provider is opened by these tests.
"""
from datetime import timedelta
from pathlib import Path

import pytest

from morning_brief.host import HostRuntime
from morning_brief.outlook import freeze_bundle
from morning_brief.runner import MorningRunner
from morning_brief.scheduled import ProducerConfig, ScheduledRuntime
from morning_brief.store import RunStore
from test_host import setup_host
from test_operator_config import snapshot
from test_publication import DEST, FakeProjection, NOW
from test_runner import FREEZE, HeartbeatDelivery, Source, calendar


class NoCapture(Source):
    def capture_window(self, *args, **kwargs):
        pytest.fail('restart recaptured source evidence')


def forbidden(*args, **kwargs):
    pytest.fail('frozen recovery reopened an external adapter')


def compose(config, inputs, *, now, source, delivery, projection,
            fetch_snapshot=snapshot, writer_factory=lambda: (None, 'fixture-model'),
            collect_rotation=forbidden, collect_public=forbidden):
    store = RunStore(config.run_store)
    runner = MorningRunner(store, source, delivery, projection, clock=lambda: now[0])
    host = HostRuntime(config, store, runner, fetch_snapshot=fetch_snapshot,
                       writer_factory=writer_factory, clock=lambda: now[0])
    producer = ProducerConfig(1, inputs['calendar']['path'],
                              str(Path(config.input_manifest).with_name('memberships.json')),
                              str(Path(config.input_manifest).with_name('source-cache')))
    runtime = ScheduledRuntime(host, producer, collect_rotation=collect_rotation,
                               collect_public=collect_public, load_memberships=forbidden,
                               clock=lambda: now[0])
    return runtime


def brief_operations(delivery):
    return [op for op in delivery.sent if op.target['channel_id'] == DEST]


def test_composed_restart_retains_configuration_artifacts_and_delivery_target(tmp_path):
    config, inputs = setup_host(tmp_path)
    now = [FREEZE + timedelta(seconds=30)]
    source, delivery, projection = Source(), HeartbeatDelivery(), FakeProjection()
    reads = []
    operator = snapshot(delivery_time='08:30')

    def fetch():
        reads.append(1)
        return operator

    first = compose(config, inputs, now=now, source=source, delivery=delivery,
                    projection=projection, fetch_snapshot=fetch)
    assert first.tick()['phase'] == 'prepared'
    assert reads == [1]  # Scheduler passes this same snapshot to the host.
    assert source.captures == 1 and brief_operations(delivery) == []
    store = first.host.store
    run = store.get_run_for_session('2026-10-05')
    originals = {slot: store.get_frozen(run.run_id, slot).digest for slot in
                 ('operator_config', 'upstream', 'selection', 'publication')}
    Path(config.input_manifest).unlink()
    Path(inputs['calendar']['path']).unlink()
    now[0] = NOW  # Before the retained 08:30 target, even after restart.
    restarted = compose(config, inputs, now=now, source=NoCapture(), delivery=delivery,
                        projection=projection, fetch_snapshot=forbidden, writer_factory=forbidden)
    assert restarted.tick()['phase'] == 'prepared'
    assert brief_operations(delivery) == []
    now[0] += timedelta(minutes=30)
    assert restarted.tick()['phase'] == 'projected'
    assert len(projection.requests) == 1
    sent = [(op.key, op.digest) for op in brief_operations(delivery)]
    assert sent
    assert restarted.tick()['phase'] == 'projected'
    assert [(op.key, op.digest) for op in brief_operations(delivery)] == sent
    assert len(projection.requests) == 1
    assert {slot: restarted.host.store.get_frozen(run.run_id, slot).digest
            for slot in originals} == originals


def test_composed_interrupted_preparation_recovers_upstream_and_original_writer(tmp_path, monkeypatch):
    config, inputs = setup_host(tmp_path)
    now = [FREEZE + timedelta(seconds=30)]
    source, delivery, projection = Source(), HeartbeatDelivery(), FakeProjection()
    first = compose(config, inputs, now=now, source=source, delivery=delivery,
                    projection=projection, writer_factory=lambda: (None, 'original-model'))

    def interrupted(run, inputs, lease, **kwargs):
        freeze_bundle(first.host.store, run.run_id, model_version=kwargs['model_version'],
                      prompt_version=kwargs['prompt_version'], lease=lease, now=now[0])
        raise RuntimeError('synthetic interruption after freezing writer identity')

    monkeypatch.setattr(first.host.runner, '_select', interrupted)
    assert first.tick()['phase'] == 'fatal'
    store = first.host.store
    run = store.get_run_for_session('2026-10-05')
    originals = {slot: store.get_frozen(run.run_id, slot).digest for slot in
                 ('operator_config', 'upstream', 'evidence', 'writer_bundle')}
    assert store.get_frozen(run.run_id, 'selection') is None
    Path(config.input_manifest).unlink()
    Path(inputs['calendar']['path']).unlink()
    restarted = compose(config, inputs, now=now, source=NoCapture(), delivery=delivery,
                        projection=projection, fetch_snapshot=forbidden,
                        writer_factory=lambda: (forbidden, 'changed-model'))
    assert restarted.tick()['phase'] == 'prepared'
    assert {slot: restarted.host.store.get_frozen(run.run_id, slot).digest
            for slot in originals} == originals
    assert restarted.host.store.get_frozen(run.run_id, 'writer_bundle').payload['versions']['model'] == 'original-model'
    now[0] = NOW
    assert restarted.tick()['phase'] == 'projected'
    assert source.captures == 1 and len(projection.requests) == 1


def test_composed_projection_retry_after_deadline_never_reposts(tmp_path):
    config, inputs = setup_host(tmp_path)
    now = [NOW]
    source, delivery, projection = Source(), HeartbeatDelivery(), FakeProjection()
    projection.down = True
    first = compose(config, inputs, now=now, source=source, delivery=delivery, projection=projection)
    assert first.tick()['phase'] == 'projection_pending'
    original = [(op.key, op.digest) for op in brief_operations(delivery)]
    Path(config.input_manifest).unlink()
    now[0] += timedelta(hours=1)
    projection.down = False
    restarted = compose(config, inputs, now=now, source=NoCapture(), delivery=delivery,
                        projection=projection, fetch_snapshot=forbidden, writer_factory=forbidden)
    assert restarted.tick()['phase'] == 'projected'
    assert [(op.key, op.digest) for op in brief_operations(delivery)] == original
    assert len(projection.requests) == 2 and projection.requests[0] == projection.requests[1]


def test_composed_live_dispatch_cannot_reuse_preview_state(tmp_path):
    config, inputs = setup_host(tmp_path)
    now = [FREEZE + timedelta(seconds=30)]
    source, delivery, projection = Source(), HeartbeatDelivery(), FakeProjection()
    store = RunStore(config.run_store)
    preview = MorningRunner(store, source, delivery, projection, clock=lambda: now[0])
    assert preview.run_from_snapshot(snapshot(), calendar=calendar(), numerical={}, global_inputs=[],
                                     calendar_snapshots=[], model=None, model_version='fixture',
                                     prompt_version='fixture', preview=True)['phase'] == 'preview'
    now[0] = NOW
    restarted = compose(config, inputs, now=now, source=NoCapture(), delivery=delivery,
                        projection=projection, fetch_snapshot=forbidden, writer_factory=forbidden)
    result = restarted.tick()
    assert result['phase'] == 'fatal' and result['reason'] == 'FreezeConflict'
    assert source.captures == 1 and brief_operations(delivery) == []
    assert projection.requests == []


@pytest.mark.parametrize('when, phase', [(NOW + timedelta(days=5), 'no_op'),
                                        (NOW + timedelta(hours=1), 'missed_session')])
def test_composed_idle_tick_does_not_create_or_capture_a_session(tmp_path, when, phase):
    config, inputs = setup_host(tmp_path)
    now = [when]
    delivery, projection = HeartbeatDelivery(), FakeProjection()
    runtime = compose(config, inputs, now=now, source=NoCapture(), delivery=delivery,
                      projection=projection, writer_factory=forbidden)
    assert runtime.tick()['phase'] == phase
    assert runtime.host.store.get_run_for_session(when.date().isoformat()) is None
    assert brief_operations(delivery) == [] and projection.requests == []
