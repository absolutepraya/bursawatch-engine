import importlib.util
import json
import os
import fcntl
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("archive_news_outbox", Path(__file__).parents[1] / "scripts/archive_news_outbox.py")
tool = importlib.util.module_from_spec(SPEC)


def load_tool():
    SPEC.loader.exec_module(tool)
    return tool


def owner_state(kind="x", entries=None):
    value = {"version": 3 if kind == "x" else 1, "profiles": {}, "outbox": entries or []}
    if kind == "x":
        value.update(deliveries=["receipt"], source_events={"event": "keep"}, cleanup=[])
    else:
        value["publication_ledger"] = {"receipt": "keep"}
    return value


@pytest.mark.parametrize("kind,entries,remaining", [
    ("x", [{"agent_phase": "ready"}, {"agent_phase": "pending"}], []),
    ("wa", [{"agent_phase": "ready"}, {"agent_phase": "delivered"}, {"agent_phase": "filtered"}, {"agent_phase": "pending"}], [{"agent_phase": "delivered"}, {"agent_phase": "filtered"}]),
])
def test_archive_preserves_history_and_original_bytes(tmp_path, kind, entries, remaining):
    t = load_tool()
    value = owner_state(kind, entries)
    value["publication_projection"] = {"ack": "keep"}
    path = tmp_path / "state.json"
    raw = json.dumps(value).encode()
    path.write_bytes(raw)
    plan = t.preview(kind, path)
    assert path.read_bytes() == raw
    t.apply(plan, tmp_path / "archive", writers_paused=True, open_operations=lambda: 0)
    assert (tmp_path / "archive/state-before.json").read_bytes() == raw
    value["outbox"] = remaining
    assert json.loads(path.read_text()) == value


def test_apply_rejects_stale_state_and_incomplete_fence(tmp_path):
    t = load_tool()
    path = tmp_path / "state.json"
    path.write_text(json.dumps(owner_state()))
    plan = t.preview("x", path)
    with pytest.raises(ValueError, match="paused"):
        t.apply(plan, tmp_path / "a", writers_paused=False, open_operations=lambda: 0)
    with pytest.raises(ValueError, match="nonterminal"):
        t.apply(plan, tmp_path / "a", writers_paused=True, open_operations=lambda: 1)
    path.write_text(json.dumps(owner_state(entries=[{"post_id": "new"}])))
    with pytest.raises(ValueError, match="changed"):
        t.apply(plan, tmp_path / "a", writers_paused=True, open_operations=lambda: 0)
    assert not (tmp_path / "a").exists()


def test_unknown_whatsapp_phase_and_symlink_fail_closed(tmp_path):
    t = load_tool()
    path = tmp_path / "state.json"
    path.write_text(json.dumps(owner_state("wa", [{"agent_phase": "unknown"}])))
    with pytest.raises(ValueError, match="phase"):
        t.preview("wa", path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular"):
        t.preview("x", link)


def test_apply_refuses_an_active_agent_lease(tmp_path):
    t = load_tool()
    path = tmp_path / "state.json"
    path.write_text(json.dumps(owner_state(entries=[{"agent_lease_until": "2099-01-01T00:00:00+00:00"}])))
    plan = t.preview("x", path)
    with pytest.raises(ValueError, match="lease"):
        t.apply(plan, tmp_path / "archive", writers_paused=True, open_operations=lambda: 0)
    assert not (tmp_path / "archive").exists()


def test_archive_ancestors_are_durable_before_live_switch(tmp_path, monkeypatch):
    t = load_tool()
    path = tmp_path / "state.json"
    path.write_text(json.dumps(owner_state(entries=[{"agent_phase": "ready"}])))
    archive = tmp_path / "fresh" / "day" / "archive"
    synced = []
    real_sync, real_write = os.fsync, t._write

    def sync(fd):
        synced.append(os.fstat(fd).st_ino)
        real_sync(fd)

    def write(target, raw):
        if target == path:
            for parent in [tmp_path, archive.parent.parent, archive.parent]:
                assert parent.stat().st_ino in synced
        real_write(target, raw)

    monkeypatch.setattr(t.os, "fsync", sync)
    monkeypatch.setattr(t, "_write", write)
    t.apply(t.preview("x", path), archive, writers_paused=True, open_operations=lambda: 0)


def test_failure_after_live_switch_leaves_original_backup(tmp_path, monkeypatch):
    t = load_tool()
    path = tmp_path / "state.json"
    raw = json.dumps(owner_state(entries=[{"agent_phase": "ready"}])).encode()
    path.write_bytes(raw)
    archive = tmp_path / "archive"
    plan = t.preview("x", path)
    real_write = t._write

    def fail_receipt(target, data):
        if target.name == "receipt.json":
            raise OSError("injected receipt failure")
        real_write(target, data)

    monkeypatch.setattr(t, "_write", fail_receipt)
    with pytest.raises(OSError, match="injected"):
        t.apply(plan, archive, writers_paused=True, open_operations=lambda: 0)
    assert (archive / "state-before.json").read_bytes() == raw
    assert t.preview("x", path)["before_sha256"] == plan["after_sha256"]
    assert not (archive / "receipt.json").exists()


@pytest.mark.parametrize("actual,requested", [("wa", "x"), ("x", "wa")])
def test_preview_rejects_wrong_owner_kind(tmp_path, actual, requested):
    t = load_tool()
    path = tmp_path / "state.json"
    raw = json.dumps(owner_state(actual, [{"agent_phase": "delivered"}])).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="owner"):
        t.preview(requested, path)
    assert path.read_bytes() == raw


def test_archive_refuses_while_whatsapp_writer_lock_is_held(tmp_path):
    t = load_tool()
    path = tmp_path / "state.json"
    raw = json.dumps(owner_state("wa", [{"agent_phase": "ready"}])).encode()
    path.write_bytes(raw)
    plan = t.preview("wa", path)
    with (tmp_path / "pipeline-owner.lock").open("a+") as writer:
        fcntl.flock(writer, fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            t.apply(plan, tmp_path / "archive", writers_paused=True, open_operations=lambda: 0)
    assert path.read_bytes() == raw
    assert not (tmp_path / "archive").exists()
