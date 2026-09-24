from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-wa-source-ingest" / "bin"))
from adapter import endpoints, run_once

sys.path.insert(0, str(ROOT / "cron-wa-channel-watch" / "bin"))
from config import load
from event_queue import enqueue, event_filename
from models import ChannelEvent, ChannelMedia

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


class Inbox:
    def __init__(self):
        self.events = []

    def accept(self, event):
        self.events.append(event)
        identity = [event[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        return {"event_key": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(), "version": 1, "duplicate": False, "work_keys": []}


def context():
    profiles = load(ROOT / "cron-wa-channel-watch" / "config" / "watches.json").profiles
    bri = profiles[0]
    row = {"platform": "whatsapp", "endpoint_id": "whatsapp:0029VbAjdnb60eBhwVdJxj1c", "publisher_id": "bri-danareksa", "address": bri.channel_url, "provider_id": bri.channel_jid, "capability_id": "swing_chart_context", "verification_status": "verified", "enabled": True}
    return profiles, bri, {"revision": 4, "subscriptions": [row]}, row["endpoint_id"]


def queue_event(queue_dir: Path, event: ChannelEvent, position_ns: int) -> Path:
    assert enqueue(queue_dir, event)
    path = queue_dir / event_filename(event)
    os.utime(path, ns=(position_ns, position_ns))
    return path


def cursor(state_root: Path, endpoint_id: str) -> dict:
    return json.loads((state_root / endpoint_id.replace(":", "-") / "cursor.json").read_text())


def test_forward_binding_skips_observe_profiles_and_empty_bootstrap(tmp_path):
    profiles, _bri, snapshot, endpoint_id = context()
    selected, _ = endpoints(snapshot, profiles)
    assert set(selected) == {endpoint_id}
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    result = run_once(snapshot, profiles, queue_dir, state_root, Inbox(), NOW)
    assert result == [{"endpoint_id": endpoint_id, "status": "bootstrapped_empty", "accepted": 0}]
    assert cursor(state_root, endpoint_id)["initialized"] is True
    assert not queue_dir.exists()


def test_delayed_published_at_is_accepted_after_later_queue_arrival(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    old = ChannelEvent(bri.channel_jid, "old", NOW, "old", (), (), NOW)
    queue_event(queue_dir, old, 1_000_000_000_000_000_000)
    inbox = Inbox()
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["status"] == "bootstrapped_empty"
    delayed = ChannelEvent(bri.channel_jid, "delayed", NOW - timedelta(days=1), "late arrival", (), (), NOW)
    queue_event(queue_dir, delayed, 2_000_000_000_000_000_000)
    result = run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)
    assert result[0]["accepted"] == 1
    assert inbox.events[0]["provider_event_id"] == "delayed"
    assert inbox.events[0]["published_at"] == delayed.published_at.isoformat()
    assert cursor(state_root, endpoint_id)["anchor"] == "delayed"


def test_bri_media_queue_item_is_durably_blocked_without_queue_mutation(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    old = ChannelEvent(bri.channel_jid, "old", NOW, "old", (), (), NOW)
    old_path = queue_event(queue_dir, old, 1_000_000_000_000_000_000)
    before = old_path.read_bytes()
    assert run_once(snapshot, profiles, queue_dir, state_root, Inbox(), NOW)[0]["status"] == "bootstrapped_empty"
    new = ChannelEvent(bri.channel_jid, "new", NOW + timedelta(minutes=1), "new text", (), (ChannelMedia("image", 0, "image/jpeg", "/private/image"),), NOW)
    new_path = queue_event(queue_dir, new, 2_000_000_000_000_000_000)
    result = run_once(snapshot, profiles, queue_dir, state_root, Inbox(), NOW)
    assert result[0]["reason"] == "media_blocked"
    marker = json.loads((state_root / endpoint_id.replace(":", "-") / "blocked-media.json").read_text())
    assert marker["payload"]["text"] == "new text"
    assert "/private/image" not in json.dumps(marker)
    assert old_path.read_bytes() == before and new_path.exists()
    assert cursor(state_root, endpoint_id)["anchor"] is None


def test_retained_history_over_500_files_is_not_parsed_on_new_arrival(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    for index in range(501):
        path = queue_dir / f"old-{index:04d}.json"
        path.write_text("invalid retained payload")
        stamp = 1_000_000_000_000_000_000 + index
        os.utime(path, ns=(stamp, stamp))
    state_root = tmp_path / "state"
    inbox = Inbox()
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["status"] == "bootstrapped_empty"
    new = ChannelEvent(bri.channel_jid, "fresh", NOW, "new source", (), (), NOW)
    queue_event(queue_dir, new, 2_000_000_000_000_000_000)
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["accepted"] == 1
    assert inbox.events[0]["provider_event_id"] == "fresh"
    assert cursor(state_root, endpoint_id)["anchor"] == "fresh"
    assert (queue_dir / "old-0000.json").read_text() == "invalid retained payload"
