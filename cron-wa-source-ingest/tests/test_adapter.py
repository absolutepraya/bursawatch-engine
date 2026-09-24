from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-wa-source-ingest" / "bin"))
from adapter import endpoints, run_once

sys.path.insert(0, str(ROOT / "cron-wa-channel-watch" / "bin"))
from config import load
from event_queue import serialize_event
from models import ChannelEvent, ChannelMedia

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def test_forward_binding_skips_observe_profiles_and_retains_bridge_queue(tmp_path):
    profiles = load(ROOT / "cron-wa-channel-watch" / "config" / "watches.json").profiles
    bri = profiles[0]
    row = {"platform": "whatsapp", "endpoint_id": "whatsapp:0029VbAjdnb60eBhwVdJxj1c", "publisher_id": "bri-danareksa", "address": bri.channel_url, "provider_id": bri.channel_jid, "capability_id": "swing_chart_context", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 4, "subscriptions": [row]}
    selected, _ = endpoints(snapshot, profiles)
    assert set(selected) == {row["endpoint_id"]}
    queue_dir = tmp_path / "queue"
    result = run_once(snapshot, profiles, queue_dir, tmp_path / "state", object(), NOW, list_queue=lambda _path: [])
    assert result == [{"endpoint_id": row["endpoint_id"], "status": "empty", "accepted": 0}]
    assert not queue_dir.exists()


def test_bri_media_queue_item_is_durably_blocked_without_queue_mutation(tmp_path):
    profiles = load(ROOT / "cron-wa-channel-watch" / "config" / "watches.json").profiles
    bri = profiles[0]
    row = {"platform": "whatsapp", "endpoint_id": "whatsapp:0029VbAjdnb60eBhwVdJxj1c", "publisher_id": "bri-danareksa", "address": bri.channel_url, "provider_id": bri.channel_jid, "capability_id": "swing_chart_context", "verification_status": "verified", "enabled": True}
    snapshot = {"revision": 4, "subscriptions": [row]}
    old = ChannelEvent(bri.channel_jid, "old", NOW, "old", (), (), NOW)
    new = ChannelEvent(bri.channel_jid, "new", NOW + timedelta(minutes=1), "new text", (), (ChannelMedia("image", 0, "image/jpeg", "/private/image"),), NOW)
    queue = [serialize_event(old)]
    state_root = tmp_path / "state"
    assert run_once(snapshot, profiles, tmp_path / "queue", state_root, object(), NOW, list_queue=lambda _path: queue)[0]["status"] == "bootstrapped"
    queue.append(serialize_event(new))
    assert run_once(snapshot, profiles, tmp_path / "queue", state_root, object(), NOW, list_queue=lambda _path: queue)[0]["reason"] == "media_blocked"
    marker = json.loads((state_root / "whatsapp-0029VbAjdnb60eBhwVdJxj1c" / "blocked-media.json").read_text())
    assert marker["payload"]["text"] == "new text"
    assert "/private/image" not in json.dumps(marker)
    assert len(queue) == 2
