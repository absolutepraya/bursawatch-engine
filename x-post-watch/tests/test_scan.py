from datetime import UTC, datetime

import scan
import state
from models import PostKind, SourceMedia, SourcePost


def test_heartbeat_format_is_canonical():
    value = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), scan.RunStats())
    assert value == "🫀 x-post · 06:00 WIB · 0 fetched · 0 filtered · 0 queued · 0 delivered · 0 errors"


def test_run_stats_marks_an_empty_profile_feed_as_degraded():
    stats = scan.RunStats()

    stats.note_empty_profile("InsiderTrackX")

    assert stats.degraded is True
    assert stats.reasons == ["InsiderTrackX: empty source feed"]
    assert stats.needs_attention is False


def test_heartbeat_mentions_owner_for_authentication_failure():
    stats = scan.RunStats()

    stats.note_source_error("insidertracker: RSSHub X feed HTTP 403: authentication rejected")

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert stats.needs_attention is True
    assert heartbeat.endswith("<@443342168434933760>")


def test_heartbeat_does_not_mention_owner_for_non_auth_source_failure():
    stats = scan.RunStats()

    stats.note_source_error("insidertracker: RSSHub X feed HTTP 500")

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert stats.needs_attention is False
    assert "443342168434933760" not in heartbeat


def test_delivery_sends_thread_media_then_external_quote_media(tmp_path, monkeypatch, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    root = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", datetime.now(UTC), "Root", PostKind.QUOTE, "https://x.com/external/status/0", "Earlier external quote", (SourceMedia("https://img.example/root.jpg", 0),), (SourceMedia("https://img.example/root-quote.jpg", 0),))
    latest = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Latest", PostKind.QUOTE, "https://x.com/external/status/1", "External: Quote", (SourceMedia("https://img.example/latest.jpg", 0),), (SourceMedia("https://img.example/quote.jpg", 0),))
    value = state.new_state()
    value["outbox"].append({
        "profile_id": profile.id, "post_id": latest.post_id, "text_index": 1, "media_index": 0,
        "post": state.serialize_post(latest), "thread_posts": [state.serialize_post(root), state.serialize_post(latest)],
    })
    delivered = []
    monkeypatch.setattr(scan.discord, "post_media", lambda url, *_args: delivered.append(url) or "test")
    storage = tmp_path / "state.json"
    while value["outbox"]:
        assert scan._deliver(value, {profile.id: profile}, 0, True, storage, scan.RunStats()) is True
    assert delivered == ["https://img.example/root.jpg", "https://img.example/latest.jpg", "https://img.example/root-quote.jpg", "https://img.example/quote.jpg"]
