from datetime import datetime, timezone

from normalize import normalize_bridge_event
from event_queue import enqueue, event_filename, list_events


def make_event(message_id="one"):
    return normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": message_id,
        "published_at": "2026-09-10T00:00:00Z",
        "text": "BBCA mencatat laba bersih naik",
        "media": [],
    }, received_at=datetime(2026, 9, 10, tzinfo=timezone.utc))


def test_enqueue_is_atomic_and_idempotent(tmp_path):
    event = make_event()
    assert enqueue(tmp_path, event) is True
    assert enqueue(tmp_path, event) is False
    files = list(tmp_path.glob("*.json"))
    assert files == [tmp_path / event_filename(event)]
    assert (files[0].stat().st_mode & 0o777) == 0o600
    assert len(list_events(tmp_path)) == 1
