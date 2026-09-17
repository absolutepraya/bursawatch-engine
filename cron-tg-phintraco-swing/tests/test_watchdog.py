import datetime as dt
import json
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / "bin" / "watchdog.py"
SPEC = importlib.util.spec_from_file_location("idx_swing_watchdog", MODULE_PATH)
watchdog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watchdog)


def test_is_stale_when_poll_missing():
    now = dt.datetime(2026, 7, 10, 8, 0, tzinfo=watchdog.WIB)
    assert watchdog.is_stale({}, now, 10) is True


def test_is_stale_after_ten_minutes():
    now = dt.datetime(2026, 7, 10, 8, 11, tzinfo=watchdog.WIB)
    state = {"last_poll_success": "2026-07-10T08:00:00+07:00"}
    assert watchdog.is_stale(state, now, 10) is True


def test_recent_poll_is_healthy():
    now = dt.datetime(2026, 7, 10, 8, 9, tzinfo=watchdog.WIB)
    state = {"last_poll_success": "2026-07-10T08:00:00+07:00"}
    assert watchdog.is_stale(state, now, 10) is False


def test_watchdog_notice_cannot_overwrite_live_scanner_state(
    tmp_state, monkeypatch
):
    stale = watchdog.scan.empty_state()
    stale["observed_message_id"] = 41
    stale["last_poll_success"] = "2026-07-10T07:00:00+07:00"
    watchdog.scan.save_state(stale)
    replacements = []
    real_replace = watchdog.os.replace

    def record_replace(source, destination):
        replacements.append((Path(source), Path(destination)))
        return real_replace(source, destination)

    def simulate_concurrent_scanner_advance(content, channel_id, dry_run, event_key):
        live = json.loads(tmp_state.read_text())
        live["observed_message_id"] = 99
        live["outbox"] = {"live-scanner-state": {"must": "survive"}}
        tmp_state.write_text(json.dumps(live))
        return "fatal-id"

    monkeypatch.setattr(watchdog.os, "replace", record_replace)
    monkeypatch.setattr(
        watchdog.scan, "post_discord_text", simulate_concurrent_scanner_advance
    )

    assert watchdog.main() == 1
    persisted = json.loads(tmp_state.read_text())
    assert persisted["observed_message_id"] == 99
    assert persisted["outbox"] == {"live-scanner-state": {"must": "survive"}}
    metadata_path = tmp_state.parent / "watchdog-notices.json"
    assert metadata_path.exists()
    assert replacements == [(metadata_path.with_suffix(".tmp"), metadata_path)]


def test_watchdog_leaves_corrupt_scanner_state_untouched(
    tmp_state, monkeypatch
):
    corrupt = "{not valid json"
    tmp_state.write_text(corrupt)
    monkeypatch.setattr(
        watchdog.scan,
        "post_discord_text",
        lambda *args, **kwargs: "fatal-id",
    )

    assert watchdog.main() == 1
    assert tmp_state.read_text() == corrupt
    assert list(tmp_state.parent.glob("state.corrupt-*.json")) == []
    assert (tmp_state.parent / "watchdog-notices.json").exists()
