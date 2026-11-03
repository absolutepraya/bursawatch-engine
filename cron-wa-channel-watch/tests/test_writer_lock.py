import fcntl

import pytest

import scan


@pytest.mark.parametrize('entry', ['run', 'submit_analysis'])
def test_stateful_scan_holds_owner_lock_until_exit(tmp_path, monkeypatch, entry):
    class ReachedConfig(Exception):
        pass

    state_path = tmp_path / 'state.json'
    lock_path = tmp_path / 'pipeline-owner.lock'

    def inspect_lock(*args, **kwargs):
        with lock_path.open('a+') as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise ReachedConfig

    monkeypatch.setattr(scan.config, 'load_for_run', inspect_lock)
    arguments = dict(config_path=tmp_path / 'config.json', state_path=state_path,
                     archive_dir=tmp_path / 'archive', no_post=True)
    arguments.update(queue_dir=tmp_path / 'queue') if entry == 'run' else arguments.update(payload={})
    with pytest.raises(ReachedConfig):
        getattr(scan, entry)(**arguments)
    with lock_path.open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
