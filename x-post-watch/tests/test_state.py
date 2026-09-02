import json

import state
from datetime import UTC, datetime, timedelta
from models import PostKind, SourceMedia, SourcePost


def test_load_state_migrates_legacy_ready_summary_to_pending_agent_task(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "version": 1,
        "profiles": {"rickyho1989": {"cursor": "102"}},
        "outbox": [{
            "profile_id": "rickyho1989",
            "post_id": "102",
            "text_index": 0,
            "media_index": 0,
            "post": {},
            "summary": "*(Ringkasan)* Legacy output.",
            "summary_phase": "ready",
            "summary_lease_until": None,
        }],
    }), encoding="utf-8")

    value = state.load_state(path)

    event = value["outbox"][0]
    assert event["agent_phase"] == "pending"
    assert event["agent_lease_until"] is None
    assert event["title"] is None
    assert event["summary"] is None
    assert "summary_phase" not in event


def test_load_state_adds_filtered_counter_to_existing_live_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 1, "profiles": {}, "outbox": []}), encoding="utf-8")

    value = state.load_state(path)

    assert state.take_filtered_since_last_heartbeat(value) == 0
    assert value["filtered_since_last_heartbeat"] == 0


def test_new_state_contains_delivery_ledger_and_cleanup_queue():
    value = state.new_state()

    assert value["version"] == 2
    assert value["deliveries"] == []
    assert value["cleanup"] == []


def test_source_retry_cooldown_expires_without_touching_cursor():
    now = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    value = state.new_state()
    value["profiles"]["kutekians"] = {"cursor": "101"}

    state.set_source_retry(value, now, 60)

    assert state.source_retry_active(value, now + timedelta(seconds=59)) is True
    assert value["profiles"]["kutekians"]["cursor"] == "101"
    assert state.source_retry_active(value, now + timedelta(seconds=60)) is False
    assert "source_retry_until" not in value


def test_delivery_ledger_keeps_message_ids_and_queues_old_bundle_cleanup():
    value = state.new_state()
    event = {
        "profile_id": "kutekians",
        "post_id": "101",
        "thread_root_id": "101",
        "post": {"post_id": "101", "published_at": "2026-08-21T10:00:00+00:00", "url": "https://x.com/Kutekians/status/101"},
        "thread_posts": [{"post_id": "101", "published_at": "2026-08-21T10:00:00+00:00", "url": "https://x.com/Kutekians/status/101"}],
        "text_message_ids": ["old-text"],
        "media_message_ids": ["old-media"],
    }
    old = state.record_delivery(value, event, "channel", datetime(2026, 8, 21, tzinfo=UTC), False)
    replacement = dict(event, post_id="102", thread_root_id="102", post={**event["post"], "post_id": "102"}, thread_posts=[{**event["thread_posts"][0], "post_id": "102"}], text_message_ids=["new-text"], media_message_ids=[], replacement_of=[old["delivery_id"]])

    new = state.record_delivery(value, replacement, "channel", datetime(2026, 8, 21, 1, tzinfo=UTC), False)
    state.queue_replacement_cleanup(value, new)

    assert new["text_message_ids"] == ["new-text"]
    assert value["cleanup"][0]["message_ids"] == ["old-text", "old-media"]
    assert old["replacement_pending"] is True


def test_empty_first_poll_then_first_post_initializes_without_backfill(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    first_poll = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    first_post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", first_poll + timedelta(minutes=5), "First observed post", PostKind.NORMAL, None, None, (), ())
    newer_post = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", first_poll + timedelta(minutes=15), "Genuinely newer post", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()

    assert state.observe_posts(value, profile, [], lambda post: post.kind is PostKind.NORMAL, now=first_poll) == (0, None)
    assert value["profiles"][profile.id]["cursor"] is None

    assert state.observe_posts(value, profile, [first_post], lambda post: post.kind is PostKind.NORMAL, now=first_poll + timedelta(minutes=10)) == (0, None)
    assert value["profiles"][profile.id]["cursor"] == "101"
    assert value["outbox"] == []

    assert state.observe_posts(value, profile, [first_post, newer_post], lambda post: post.kind is PostKind.NORMAL, now=first_poll + timedelta(minutes=20)) == (1, None)
    assert [event["post_id"] for event in value["outbox"]] == ["102"]


def test_lone_self_chain_keeps_one_deadline_then_child_is_ready_immediately(config_path):
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["profiles"][0]["thread_handling"]["settle_minutes"] = 15
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    started = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    root = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", started, "Root context", PostKind.NORMAL, None, None, (SourceMedia("https://img.example/root.jpg", 0),), ())
    child = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", started + timedelta(minutes=1), "Continuation", PostKind.QUOTE, "https://x.com/Kutekians/status/101", "Root context", (SourceMedia("https://img.example/child.jpg", 0),), (), "https://x.com/Kutekians/status/101")
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(value, profile, [root], lambda post: post.kind is PostKind.NORMAL, lambda post: post.related_url is not None, started)
    assert state.is_ready(value["outbox"][0], started + timedelta(minutes=14)) is False
    assert state.is_ready(value["outbox"][0], started + timedelta(minutes=15)) is True
    state.observe_posts(value, profile, [root, child], lambda post: post.kind is PostKind.NORMAL, lambda post: post.related_url is not None, started + timedelta(minutes=1))
    event = value["outbox"][0]
    assert len(value["outbox"]) == 1
    assert [post["post_id"] for post in event["thread_posts"]] == ["101", "102"]
    assert state.is_ready(event, started + timedelta(minutes=1)) is True


def test_same_poll_root_and_continuation_use_the_newest_complete_thread(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    now = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    root = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", now, "Root", PostKind.NORMAL, None, None, (), ())
    child = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", now + timedelta(minutes=2), "Child", PostKind.QUOTE, "https://x.com/Kutekians/status/101", "Root", (), (), "https://x.com/Kutekians/status/101")
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(value, profile, [root, child], lambda post: post.kind is PostKind.NORMAL, lambda post: post.related_url is not None, now)
    event = value["outbox"][0]
    assert len(value["outbox"]) == 1
    assert event["post_id"] == "102"
    assert [post["post_id"] for post in event["thread_posts"]] == ["101", "102"]
    assert state.is_ready(event, now) is True


def test_disabled_thread_handling_delivers_without_a_quiet_window(config_path, profile_payload):
    profile_payload["thread_handling"]["mode"] = "disabled"
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    now = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", now, "Immediate", PostKind.NORMAL, None, None, (), ())
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}

    state.observe_posts(value, profile, [post], lambda candidate: candidate.kind is PostKind.NORMAL, now=now)

    assert state.is_ready(value["outbox"][0], now) is True
