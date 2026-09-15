from datetime import UTC, datetime, timedelta

import pytest

import scan
import state
import supersession
from models import DiscordChannel, PostKind, Profile, SourceMedia, SourcePost, ThreadHandling


def now() -> datetime:
    return datetime(2026, 9, 15, 10, 0, tzinfo=scan.WIB)


def profile_fixture() -> Profile:
    return Profile(
        id="marketwriter",
        enabled=True,
        profile_url="https://x.com/marketwriter",
        handle="marketwriter",
        display_name="Market Writer",
        twitter_emoji="<:twitter:1531672630602498129>",
        emoji="<:marketwriter:1531673483459821729>",
        discord_channels=(
            DiscordChannel("macro_news", "1531655369884045382", "Macro"),
            DiscordChannel("id_stocks_swing", "1525102458253217803", "IDX swing"),
        ),
        forward_normal_post=True,
        forward_quote_post=True,
        forward_reply=False,
        forward_repost=False,
        forward_media=True,
        enable_llm_title=True,
        enable_llm_summary=True,
        enable_llm_routing=True,
        enable_llm_relevance_filter=True,
        relevance_scope="stock_market",
        additional_prompt_instruction="",
        max_items_per_poll=50,
        thread_handling=ThreadHandling("disabled", 1, 60, 1),
    )


def profiles() -> dict[str, Profile]:
    profile = profile_fixture()
    return {profile.id: profile}


def stats() -> scan.RunStats:
    return scan.RunStats()


def swing_event(source_text: str) -> dict:
    profile = profile_fixture()
    post = SourcePost(
        profile.id,
        "101",
        "https://x.com/marketwriter/status/101",
        now(),
        source_text,
        PostKind.NORMAL,
        None,
        None,
        (SourceMedia("https://img.example/chart.png", 0),),
        (SourceMedia("https://img.example/quoted.png", 0),),
    )
    return {
        "profile_id": profile.id,
        "post_id": post.post_id,
        "thread_root_id": post.post_id,
        "post": state.serialize_post(post),
        "thread_posts": [state.serialize_post(post)],
        "title": "KPIG: Analisis gelombang yang sudah diterima",
        "summary": "*(Ringkasan)* Ringkasan yang sudah diterima.",
        "route": "id_stocks_swing",
        "agent_phase": "ready",
        "agent_lease_until": None,
        "text_index": 1,
        "media_index": 2,
        "text_message_ids": ["all-message"],
        "media_message_ids": ["all-media", "all-quoted-media"],
    }


def ready_swing_state(tmp_path) -> dict:
    value = state.new_state()
    value["outbox"].append(swing_event("KPIG: Wave IV diproyeksikan menuju area 97 sampai 108"))
    state.save_state(tmp_path / "state.json", value)
    return value


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
    assert "<@" not in heartbeats[0]


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


def test_queue_only_run_skips_source_fetch_and_claims_oldest_agent(tmp_path, monkeypatch, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    now = datetime(2026, 8, 24, 10, 0, tzinfo=scan.WIB)
    observed_at = now - timedelta(hours=2)
    storage = tmp_path / "state.json"
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", observed_at, "A substantive market post", PostKind.NORMAL, None, None, (), ())
    state.observe_posts(value, profile, [post], lambda candidate: candidate.kind is PostKind.NORMAL, now=observed_at)
    state.save_state(storage, value)
    heartbeats = []
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("queue-only mode fetched a source")))
    monkeypatch.setattr(scan.discord, "post_text", lambda message, *args: heartbeats.append(message))
    monkeypatch.setenv("X_POST_WATCH_QUEUE_ONLY", "1")

    result = scan.run(now=now, dry_run=True)

    assert result["wakeAgent"] is True
    assert result["item"]["event_key"] == "kutekians:101"
    assert "1 pending · oldest 60m" in heartbeats[0]
    saved = state.load_state(storage)
    assert saved["outbox"][0]["agent_phase"] == "awaiting_agent"


def test_heartbeat_format_is_canonical():
    value = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), scan.RunStats())
    assert value == "🫀 x-post · 06:00 WIB · 0 fetched · 0 filtered · 0 queued · 0 delivered · 0 errors · 0 pending · oldest 0m"


def test_x_board_event_requires_one_exact_ticker_led_source_title() -> None:
    event = swing_event(source_text="KPIG: Wave IV diproyeksikan menuju area 97 sampai 108")

    board_event = scan.board_source_event(event, profile_fixture())

    assert board_event["source_title"] == "KPIG: Wave IV diproyeksikan menuju area 97 sampai 108"
    assert board_event["media_urls"] == ["https://img.example/chart.png"]


def test_x_board_title_preserves_source_visible_markdown_and_link_text() -> None:
    event = swing_event(
        '<p>KPIG: Wave | <a href="https://example.test/chart">support* &amp; resistance</a></p><p>Second source line</p>'
    )

    assert scan.board_source_event(event, profile_fixture())["source_title"] == "KPIG: Wave | support* & resistance"


def test_multiticker_or_non_ticker_led_x_source_stays_all_only() -> None:
    assert scan.board_source_event(swing_event(source_text="KPIG dan RAJA menarik"), profile_fixture()) is None
    assert scan.board_source_event(swing_event(source_text="Update teknikal hari ini"), profile_fixture()) is None
    assert scan.board_source_event(swing_event(source_text="KPIG: Technical setup; RAJA: setup lain"), profile_fixture()) is None


def test_board_failure_does_not_repost_existing_all_messages(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    monkeypatch.setattr(scan.discord, "post_text", lambda *_: "all-message")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)

    assert scan._deliver(value, profiles(), 0, False, tmp_path / "state.json", stats(), now()) is False
    assert value["outbox"][0]["text_message_ids"] == ["all-message"]
    assert value["outbox"][0]["board_phase"] == "pending"


def test_board_retry_accepts_without_reposting_all_messages(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    all_messages = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *_: all_messages.append("all-message") or "all-message")
    monkeypatch.setattr(scan.discord, "post_media", lambda *_: all_messages.append("all-media") or "all-media")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)

    assert scan._deliver(value, profiles(), 0, False, tmp_path / "state.json", stats(), now()) is False

    monkeypatch.setattr(scan, "submit_board_event", lambda *_: True)
    assert scan._deliver(value, profiles(), 0, False, tmp_path / "state.json", stats(), now() + timedelta(minutes=1)) is True
    assert value["outbox"] == []
    assert all_messages == []


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('{"accepted":true}', True),
        ('{"accepted":1}', False),
        ('{"accepted":true,"extra":false}', False),
        ('{"accepted":false}', False),
        ("not-json", False),
    ],
)
def test_board_submission_accepts_only_the_owner_acknowledgement(monkeypatch, stdout, expected) -> None:
    completed = type("Completed", (), {"returncode": 0, "stdout": stdout})()
    monkeypatch.setattr(scan.subprocess, "run", lambda *args, **kwargs: completed)

    assert scan.submit_board_event({"event_key": "x:marketwriter:101"}, False) is expected


def test_run_stats_marks_an_empty_profile_feed_as_degraded():
    stats = scan.RunStats()

    stats.note_empty_profile("InsiderTrackX")

    assert stats.degraded is True
    assert stats.reasons == ["InsiderTrackX: empty source feed"]
    assert stats.needs_attention is True

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert heartbeat.endswith("InsiderTrackX: empty source feed ⚠️")
    assert "<@" not in heartbeat


def test_heartbeat_does_not_mention_owner_for_authentication_failure():
    stats = scan.RunStats()

    stats.note_source_error("insidertracker: RSSHub X feed HTTP 403: authentication rejected")

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert stats.needs_attention is True
    assert heartbeat.endswith("authentication rejected ⚠️")
    assert "<@" not in heartbeat


def test_heartbeat_does_not_mention_owner_for_non_auth_source_failure():
    stats = scan.RunStats()

    stats.note_source_error("insidertracker: RSSHub X feed HTTP 500")

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)
    assert stats.needs_attention is True
    assert heartbeat.endswith("HTTP 500 ⚠️")
    assert "<@" not in heartbeat


def test_heartbeat_does_not_mention_owner_for_any_degraded_state():
    stats = scan.RunStats(degraded=True)

    heartbeat = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), stats)

    assert heartbeat.endswith("⚠️")
    assert "<@" not in heartbeat


def test_fatal_heartbeat_does_not_mention_owner():
    value = scan.format_fatal(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), "unexpected runtime failure")

    assert value == "❌ x-post · 06:00 WIB · failed: unexpected runtime failure"
    assert "<@" not in value


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


def test_delivery_omit_last_removes_only_final_unique_bundle_media(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["media_policy"] = "omit_last"
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
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
    assert delivered == ["https://img.example/root.jpg", "https://img.example/latest.jpg", "https://img.example/root-quote.jpg"]


def test_delivery_omit_last_drops_the_only_media_item(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["media_policy"] = "omit_last"
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", datetime.now(UTC), "Post", PostKind.NORMAL, None, None, (SourceMedia("https://img.example/only.jpg", 0),), ())
    value = state.new_state()
    value["outbox"].append({
        "profile_id": profile.id, "post_id": post.post_id, "text_index": 1, "media_index": 0,
        "post": state.serialize_post(post), "thread_posts": [state.serialize_post(post)],
    })
    delivered = []
    monkeypatch.setattr(scan.discord, "post_media", lambda url, *_args: delivered.append(url) or "test")

    assert scan._deliver(value, {profile.id: profile}, 0, True, tmp_path / "state.json", scan.RunStats()) is True
    assert delivered == []
    assert value["outbox"] == []


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


def test_cleanup_failure_keeps_new_delivery_without_owner_mention(tmp_path, monkeypatch):
    value = state.new_state()
    value["deliveries"].append({"delivery_id": "old", "superseded_by": None, "replacement_pending": True})
    value["cleanup"].append({"old_delivery_id": "old", "replacement_delivery_id": "new", "channel_id": "channel", "message_ids": ["old-text"], "attempts": 0})
    monkeypatch.setattr(scan.discord, "delete_message", lambda *args: (_ for _ in ()).throw(RuntimeError("delete failed")))
    stats = scan.RunStats()

    scan._retry_cleanup(value, False, tmp_path / "state.json", stats)

    assert value["cleanup"][0]["message_ids"] == ["old-text"]
    assert stats.needs_attention is True
    heartbeat = scan.format_heartbeat(datetime(2026, 8, 21, 10, tzinfo=scan.WIB), stats)
    assert heartbeat.endswith("⚠️")
    assert "<@" not in heartbeat


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
