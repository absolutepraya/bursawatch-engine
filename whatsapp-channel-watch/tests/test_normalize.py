from datetime import datetime, timezone

import pytest

from normalize import deserialize_queue_event, normalize_bridge_event
from event_queue import serialize_event


def event(**overrides):
    value = {
        "channel_jid": "12345@newsletter",
        "message_id": "ABC-001",
        "published_at": 1_756_000_000,
        "text": "BBCA mencatat laba bersih naik. https://example.test/report.",
        "media": [],
    }
    value.update(overrides)
    return value


def test_normalizes_text_and_deduplicates_links():
    result = normalize_bridge_event(event(text="Lihat https://example.test/a dan https://example.test/a."), received_at=datetime(2026, 9, 10, tzinfo=timezone.utc))
    assert result.event_key == "12345@newsletter:ABC-001"
    assert result.links == ("https://example.test/a",)
    assert result.published_at.tzinfo is not None


def test_accepts_image_and_video_metadata():
    result = normalize_bridge_event(event(media=[
        {"kind": "image", "mime": "image/jpeg", "path": "/private/image.jpg"},
        {"kind": "video", "mime": "video/mp4", "path": "/private/video.mp4"},
    ]))
    assert [item.kind for item in result.media] == ["image", "video"]


@pytest.mark.parametrize("payload", [
    event(channel_jid="12345@g.us"),
    event(media=[{"kind": "audio", "mime": "audio/ogg"}]),
    event(text="", media=[]),
])
def test_rejects_non_channel_or_unsupported_empty_events(payload):
    with pytest.raises(ValueError):
        normalize_bridge_event(payload)


def test_rejects_extra_fields_and_invalid_media_path_type():
    with pytest.raises(ValueError):
        normalize_bridge_event(event(extra="not allowed"))
    with pytest.raises(ValueError):
        normalize_bridge_event(event(media=[{"kind": "image", "path": 4}]))


def test_queue_round_trip_rechecks_derived_links():
    original = normalize_bridge_event(event())
    assert deserialize_queue_event(serialize_event(original)).event_key == original.event_key
    broken = serialize_event(original)
    broken["links"] = []
    with pytest.raises(ValueError):
        deserialize_queue_event(broken)
