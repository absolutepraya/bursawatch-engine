from datetime import UTC, datetime, timedelta

import scan
import state
import supersession
from models import PostKind, SourceMedia, SourcePost


def test_run_skips_a_profile_during_source_retry_cooldown(tmp_path, monkeypatch, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    now = datetime(2026, 8, 24, 10, 0, tzinfo=scan.WIB)
    storage = tmp_path / "state.json"
    value = state.new_state()
    value["source_retry_until"] = (now + timedelta(minutes=10)).isoformat()
    value["profiles"][profile.id] = {"cursor": "101"}
    state.save_state(storage, value)
    calls = []
    heartbeats = []
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *args, **kwargs: calls.append(args) or [])
    monkeypatch.setattr(scan.discord, "post_text", lambda message, *args: heartbeats.append(message))

    result = scan.run(now=now, dry_run=True)

    assert result["wakeAgent"] is False
    assert calls == []
    assert "<@443342168434933760>" not in heartbeats[0]


def test_run_persists_source_retry_after(tmp_path, monkeypatch, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    now = datetime(2026, 8, 24, 10, 0, tzinfo=scan.WIB)
    storage = tmp_path / "state.json"
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(
        scan.rsshub,
        "fetch_profile_items",
        lambda *args, **kwargs: (_ for _ in ()).throw(scan.rsshub.SourceFetchError("HTTP 429", retry_after_seconds=60)),
    )
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: None)

    scan.run(now=now, dry_run=True)

    saved = state.load_state(storage)
    assert saved["source_retry_until"] == (now + timedelta(seconds=60)).isoformat()


def test_heartbeat_format_is_canonical():
    value = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), scan.RunStats())
    assert value == "🫀 x-post · 06:00 WIB · 0 fetched · 0 filtered · 0 queued · 0 delivered · 0 errors"


def test_run_stats_marks_an_empty_profile_feed_as_degraded():
    stats = scan.RunStats()

    stats.note_empty_profile("InsiderTrackX")

    assert stats.degraded is True
    assert stats.reasons == ["InsiderTrackX: empty source feed"]
    assert stats.needs_attention is True

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert heartbeat.endswith("<@443342168434933760>")


def test_heartbeat_mentions_owner_for_authentication_failure():
    stats = scan.RunStats()

    stats.note_source_error("insidertracker: RSSHub X feed HTTP 403: authentication rejected")

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert stats.needs_attention is True
    assert heartbeat.endswith("<@443342168434933760>")


def test_heartbeat_mentions_owner_for_non_auth_source_failure():
    stats = scan.RunStats()

    stats.note_source_error("insidertracker: RSSHub X feed HTTP 500")

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert stats.needs_attention is True
    assert heartbeat.endswith("<@443342168434933760>")


def test_heartbeat_mentions_owner_for_any_degraded_state():
    stats = scan.RunStats(degraded=True)

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)

    assert heartbeat.endswith("<@443342168434933760>")


def test_fatal_heartbeat_mentions_owner():
    value = scan.format_fatal(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), "unexpected runtime failure")

    assert value == "❌ x-post · 06:00 WIB · failed: unexpected runtime failure <@443342168434933760>"


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


def test_delivery_persists_discord_message_id_in_ledger(tmp_path, monkeypatch, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", datetime.now(UTC), "A post", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["outbox"].append({
        "profile_id": profile.id, "post_id": "101", "thread_root_id": "101", "text_index": 0, "media_index": 0,
        "post": state.serialize_post(post), "thread_posts": [state.serialize_post(post)],
    })
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: "new-text")
    storage = tmp_path / "state.json"
    stats = scan.RunStats()

    assert scan._deliver(value, {profile.id: profile}, 0, False, storage, stats) is True
    assert scan._deliver(value, {profile.id: profile}, 0, False, storage, stats) is True
    assert value["deliveries"][0]["text_message_ids"] == ["new-text"]


def test_cleanup_failure_keeps_new_delivery_and_mentions_owner(tmp_path, monkeypatch):
    value = state.new_state()
    value["deliveries"].append({"delivery_id": "old", "superseded_by": None, "replacement_pending": True})
    value["cleanup"].append({"old_delivery_id": "old", "replacement_delivery_id": "new", "channel_id": "channel", "message_ids": ["old-text"], "attempts": 0})
    monkeypatch.setattr(scan.discord, "delete_message", lambda *args: (_ for _ in ()).throw(RuntimeError("delete failed")))
    stats = scan.RunStats()

    scan._retry_cleanup(value, False, tmp_path / "state.json", stats)

    assert value["cleanup"][0]["message_ids"] == ["old-text"]
    assert stats.needs_attention is True
    assert scan.format_heartbeat(datetime(2026, 8, 21, 10, tzinfo=scan.WIB), stats).endswith("<@443342168434933760>")


def test_confirmed_edit_history_marks_new_event_as_updated_replacement(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    published = datetime(2026, 8, 21, 10, tzinfo=UTC)
    old_post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", published, "Revenue rose 12 percent after guidance.", PostKind.NORMAL, None, None, (), ())
    new_post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", published.replace(minute=30), "Revenue rose 12 percent after guidance.", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["deliveries"].append({
        "delivery_id": "kutekians:101", "profile_id": profile.id, "thread_posts": [state.serialize_post(old_post)],
        "superseded_by": None, "replacement_pending": False,
    })
    value["outbox"].append({
        "profile_id": profile.id, "post_id": "102", "thread_posts": [state.serialize_post(new_post)],
        "post": state.serialize_post(new_post), "replacement_of": [],
    })

    class Confirmed:
        def verify(self, *args):
            return supersession.Verification("confirmed", "confirmed")

    stats = scan.RunStats()
    scan._annotate_replacements(value, profile, {"102"}, Confirmed(), published, stats)

    assert value["outbox"][0]["replacement_of"] == ["kutekians:101"]
    assert value["outbox"][0]["updated_tweet"] is True


def test_self_chain_continuation_replaces_previous_bundle_without_x_edit_check(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    published = datetime(2026, 8, 21, 10, tzinfo=UTC)
    root = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", published, "Root", PostKind.NORMAL, None, None, (), ())
    child = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", published.replace(minute=30), "Child", PostKind.REPLY, None, None, (), (), "https://x.com/Kutekians/status/101")
    value = state.new_state()
    value["deliveries"].append({
        "delivery_id": "kutekians:101", "profile_id": profile.id, "thread_root_id": "101", "source_post_ids": ["101"],
        "published_at": published.isoformat(), "thread_posts": [state.serialize_post(root)],
        "superseded_by": None, "replacement_pending": False,
    })
    value["outbox"].append({
        "profile_id": profile.id, "post_id": "102", "thread_root_id": "101", "thread_posts": [state.serialize_post(root), state.serialize_post(child)],
        "post": state.serialize_post(child), "replacement_of": [],
    })

    class UnexpectedVerifier:
        def verify(self, *args):
            raise AssertionError("thread extension must not call X edit verification")

    scan._annotate_replacements(value, profile, {"102"}, UnexpectedVerifier(), published.replace(minute=30), scan.RunStats())

    assert value["outbox"][0]["replacement_of"] == ["kutekians:101"]
