from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

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


class IdempotentMediaStore:
    def __init__(self, order):
        self.order = order
        self.uploads = {}

    def upload(self, key, data, *, kind, content_type, filename):
        self.order.append("upload")
        value = self.uploads.get(key)
        if value is None:
            value = {
                "ref": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "kind": kind,
                "content_type": content_type,
                "size_bytes": len(data),
                "filename": filename,
                "durable": True,
            }
            self.uploads[key] = (data, value)
        else:
            assert value[0] == data
        return self.uploads[key][1]


class OrderedInbox(Inbox):
    def __init__(self, order):
        super().__init__()
        self.order = order
        self.fail = False

    def accept(self, event):
        self.order.append("accept")
        if self.fail:
            raise OSError("inbox unavailable")
        return super().accept(event)


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


def test_archive_media_upload_precedes_acceptance_and_survives_retry(tmp_path):
    profiles, bri, snapshot, endpoint_id = context()
    queue_dir = tmp_path / "queue"
    state_root = tmp_path / "state"
    archive_root = tmp_path / "archive"
    old = ChannelEvent(bri.channel_jid, "old", NOW, "old", (), (), NOW)
    old_path = queue_event(queue_dir, old, 1_000_000_000_000_000_000)
    inbox_order = []
    inbox = OrderedInbox(inbox_order)
    assert run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW)[0]["status"] == "bootstrapped_empty"
    bootstrap_cursor = cursor(state_root, endpoint_id)
    assert bootstrap_cursor["anchor"] is None
    assert bootstrap_cursor["position"].endswith(old_path.name)

    staging = tmp_path / "staging"
    staging.mkdir()
    staged_media = staging / "private-source.jpg"
    staged_media.write_bytes(b"\xff\xd8\xffdurable-channel-image")
    new = ChannelEvent(
        bri.channel_jid,
        "with-media",
        NOW + timedelta(minutes=1),
        "chart update",
        (),
        (ChannelMedia("image", 0, "image/jpeg", str(staged_media)),),
        NOW,
    )
    import archive
    archive.ensure(archive_root, bri.id, new, 4, staging_root=staging)
    queue_path = queue_event(queue_dir, new, 2_000_000_000_000_000_000)
    assert not staged_media.exists(), "the bridge staging copy is disposable after archive capture"

    media_store = IdempotentMediaStore(inbox_order)
    inbox.fail = True
    failed = run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW, archive_root=archive_root, media_store=media_store)
    assert failed[0]["status"] == "blocked"
    assert cursor(state_root, endpoint_id) == bootstrap_cursor
    assert queue_path.exists()
    assert inbox_order == ["upload", "accept"]

    inbox.fail = False
    recovered = run_once(snapshot, profiles, queue_dir, state_root, inbox, NOW, archive_root=archive_root, media_store=media_store)
    assert cursor(state_root, endpoint_id)["anchor"] == "with-media"
    assert len(inbox.events) == 1
    assert inbox_order == ["upload", "accept", "accept"]
    assert list(media_store.uploads) == [f"{endpoint_id}:with-media:attachment:0"]
    event = inbox.events[0]
    assert event["media_required"] is True
    assert event["media_refs"] == [media_store.uploads[next(iter(media_store.uploads))][1]]
    assert event["payload"]["media_ref_ids"] == [event["media_refs"][0]["ref"]]
    serialized = json.dumps(event)
    assert str(staged_media) not in serialized
    assert "archive_path" not in serialized and "media/" not in serialized
    assert "durable-channel-image" not in serialized


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
