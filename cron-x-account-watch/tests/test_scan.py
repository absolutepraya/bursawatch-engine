from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest

import scan
import render
import state
import supersession
from article_context import ArticleBundle, ArticleSource
from models import DiscordChannel, PostKind, Profile, SourceMedia, SourcePost, ThreadHandling
from vision_media import VisionAsset, VisionBundle


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


@pytest.mark.parametrize(("source_text", "candidate", "capabilities", "expected_outcome"), [
    ("KPIG: wave count points to support at 90", "id_stocks_swing", ["company_news", "macro_news"], "suppressed_ineligible"),
    ("IHSG technical chart shows broad market support", "id_stocks_swing", ["macro_news", "swing_chart_context"], "macro_news"),
])
def test_group_route_uses_one_candidate_and_frozen_capability_gate(tmp_path, monkeypatch, source_text, candidate, capabilities, expected_outcome):
    profile = profile_fixture()
    post = SourcePost(profile.id, "101", f"https://x.com/{profile.handle}/status/101", now(), source_text, PostKind.NORMAL, None, None, (), ())
    storage = tmp_path / "state.json"
    value = state.new_state()
    state._event_for_thread(value, profile, (post,), now(), 0)
    event = value["outbox"][0]
    event.update(source_event_key="source-event", enabled_capabilities=capabilities, source_catalog_revision=17,
                 agent_phase="awaiting_agent", agent_lease_until=(now() + timedelta(minutes=15)).isoformat())
    value["source_events"]["source-event"] = {"version": 1, "outcome": "accepted", "enabled_capabilities": capabilities, "source_catalog_revision": 17}
    state.save_state(storage, value)
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: tmp_path / "watches.json")
    monkeypatch.setattr(scan.config, "load_watch_config_for_run", lambda path: SimpleNamespace(config=SimpleNamespace(profiles=(profile,)), revision=None))
    classifier_calls = []
    classify = scan.deterministic_route
    def classify_once(*args):
        classifier_calls.append(args)
        return classify(*args)
    monkeypatch.setattr(scan, "deterministic_route", classify_once)
    deliveries = []
    monkeypatch.setattr(scan, "_deliver", lambda value, profiles, index, dry_run, storage, stats, now: deliveries.append(value["outbox"][index]["route"]) or value["outbox"].pop(index) or True)
    monkeypatch.setattr(scan, "submit_board_event", lambda *args, **kwargs: pytest.fail("Board handoff after ineligible route"))
    monkeypatch.setattr(scan.discord, "post_text", lambda *args, **kwargs: pytest.fail("Discord post after ineligible route"))

    result = scan.submit_analysis_payload({"event_key": f"{profile.id}:101", "is_relevant": True,
                                           "title": "KPIG: Analisis teknikal", "summary": "*(Ringkasan)* Analisis pasar.",
                                           "route": candidate}, dry_run=True)
    saved = state.load_state(storage)
    assert len(classifier_calls) == 1
    if expected_outcome == "suppressed_ineligible":
        assert result["suppressed"] == "suppressed_ineligible"
        assert saved["source_events"]["source-event"]["outcome"] == "suppressed_ineligible"
        assert saved["outbox"] == []
        assert deliveries == []
    else:
        assert deliveries == [expected_outcome]
        assert saved["source_events"]["source-event"]["outcome"] == "accepted"


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


def test_initialized_hybrid_profile_with_no_new_posts_is_not_an_empty_feed_alarm(tmp_path, monkeypatch, config_path):
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["profiles"][0]["source"] = "hybrid"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    storage = tmp_path / "state.json"
    value = state.new_state()
    value["profiles"][payload["profiles"][0]["id"]] = {"cursor": "101"}
    state.save_state(storage, value)
    heartbeats = []
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(scan.discord, "post_text", lambda message, *args: heartbeats.append(message))

    scan.run(now=now(), dry_run=True)

    assert len(heartbeats) == 1
    assert "empty source feed" not in heartbeats[0]
    assert "⚠️" not in heartbeats[0]


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


def test_live_run_reports_structured_events_without_changing_heartbeat(tmp_path, monkeypatch, config_path):
    profile_config = __import__("config").load_watch_config(config_path)
    now = datetime(2026, 8, 24, 10, 0, tzinfo=scan.WIB)
    storage = tmp_path / "state.json"
    heartbeats = []

    class Reporter:
        def __init__(self):
            self.started = []
            self.events = []
            self.finished = []

        def start_run(self, revision, scheduler_job_id, trigger):
            self.started.append((revision, scheduler_job_id, trigger))
            return "run-1"

        def event(self, run_id, event_id, **kwargs):
            self.events.append((run_id, event_id, kwargs))

        def finish(self, run_id, status, error=None):
            self.finished.append((run_id, status, error))

    reporter = Reporter()
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(
        scan.config,
        "load_watch_config_for_run",
        lambda _path: SimpleNamespace(config=profile_config, revision=17),
    )
    monkeypatch.setattr(scan, "_control_plane_reporter", lambda: reporter)
    monkeypatch.setattr(scan.rsshub, "fetch_profile_items", lambda *args, **kwargs: [])
    monkeypatch.setattr(scan.discord, "post_text", lambda message, *args: heartbeats.append(message))

    scan.run(now=now, dry_run=True)

    assert reporter.started == [(17, "x-post-source", "scheduled")]
    assert [event[2]["event_type"] for event in reporter.events] == [
        "run.started",
        "source.fetch.completed",
        "delivery.drain.completed",
        "run.completed",
    ]
    source_event = next(event[2] for event in reporter.events if event[2]["event_type"] == "source.fetch.completed")
    assert source_event["level"] == "warning"
    assert source_event["attributes"]["reason"] == "empty source feed"
    assert reporter.finished == [("run-1", "degraded", None)]
    assert heartbeats[0].startswith("🫀 x-post · 10:00 WIB ·")


def test_control_plane_reason_sanitizes_source_secrets_urls_and_paths():
    reason = scan._sanitize_reason(
        "token=secret-value https://rss.example/feed?cookie=private /tmp/watcher-state.json"
    )

    assert reason == "token=<redacted> <external source> <local path>"


def test_live_agent_submission_reports_structured_events(tmp_path, monkeypatch, config_path):
    from test_summary_context import staged_claim
    profile_config = __import__("config").load_watch_config(config_path)
    profile = profile_config.profiles[0]
    storage = tmp_path / "state.json"
    observed_at = now() - timedelta(hours=2)
    post = SourcePost(
        profile.id,
        "101",
        "https://x.com/Kutekians/status/101",
        observed_at,
        "A substantive market post",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(
        value,
        profile,
        [post],
        lambda candidate: candidate.kind is PostKind.NORMAL,
        now=observed_at,
    )
    state.claim_oldest_agent(value, {profile.id: profile}, now())
    state.save_state(storage, value)

    class Reporter:
        def __init__(self):
            self.started = []
            self.events = []
            self.finished = []

        def start_run(self, revision, scheduler_job_id, trigger):
            self.started.append((revision, scheduler_job_id, trigger))
            return "agent-run-1"

        def event(self, run_id, event_id, **kwargs):
            self.events.append((run_id, event_id, kwargs))

        def finish(self, run_id, status, error=None):
            self.finished.append((run_id, status, error))

    reporter = Reporter()
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(
        scan.config,
        "load_watch_config_for_run",
        lambda _path: SimpleNamespace(config=profile_config, revision=17),
    )
    monkeypatch.setattr(scan, "_control_plane_reporter", lambda: reporter)
    optional_asset = staged_claim(tmp_path, monkeypatch, f"{profile.id}:101")
    with pytest.raises(ValueError):
        scan.submit_analysis_payload({"event_key": f"{profile.id}:101", "is_relevant": "invalid"}, dry_run=True)
    assert optional_asset.is_file()
    reporter.started.clear(); reporter.events.clear(); reporter.finished.clear()

    result = scan.submit_analysis_payload(
        {"event_key": f"{profile.id}:101", "is_relevant": False},
        dry_run=True,
    )

    assert result == {"submitted": True, "ignored": True, "delivered": 0}
    assert not optional_asset.exists()
    assert reporter.started == [(17, "x-post-source", "agent_submission")]
    assert [event[2]["event_type"] for event in reporter.events] == [
        "agent.submission.started",
        "agent.submission.accepted",
    ]
    assert reporter.finished == [("agent-run-1", "ok", None)]


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
    assert "1 pending · owner pending 0 · oldest 60m" in heartbeats[0]
    saved = state.load_state(storage)
    assert saved["outbox"][0]["agent_phase"] == "awaiting_agent"


@pytest.mark.parametrize("profile_mode,source_text,capabilities,swing_expected", [
    ("news", "A substantive market post", None, False),
    ("mixed", "A substantive market post", None, False),
    ("mixed", "KPIG: wave count at support 90", None, True),
    ("mixed", "IHSG technical chart shows support", None, False),
    ("mixed", "KPIG: wave count at support 90", ["company_news", "macro_news"], False),
    ("mixed", "KPIG: wave count at support 90", ["swing_chart_context"], True),
    ("fixed_swing", "KPIG: wave count at support 90", ["swing_chart_context"], True),
])
def test_queue_worker_keeps_upfront_vision_only_for_specialized_swing(tmp_path, monkeypatch, config_path, profile_mode, source_text, capabilities, swing_expected):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    if profile_mode != "news":
        from dataclasses import replace
        from models import DiscordChannel
        profile = replace(profile, enable_llm_routing=True, discord_channels=(*profile.discord_channels, DiscordChannel("id_stocks_swing","1525102458253217803","Swing")))
        if profile_mode == "fixed_swing":
            profile = replace(profile, enable_llm_routing=False, discord_channels=(profile.discord_channels[-1],))
        monkeypatch.setattr(scan.config, "load_watch_config_for_run", lambda *args: __import__("config").LoadedWatchConfig(__import__("models").WatchConfig(1,(profile,)),None))
    current = datetime(2026, 8, 24, 10, 0, tzinfo=scan.WIB)
    storage = tmp_path / "state.json"
    post = SourcePost(
        profile.id,
        "101",
        "https://x.com/Kutekians/status/101",
        current - timedelta(hours=2),
        source_text,
        PostKind.QUOTE,
        "https://x.com/other/status/100",
        "Quoted market context",
        (SourceMedia("https://pbs.twimg.com/media/authored.jpg", 0),),
        (SourceMedia("https://pbs.twimg.com/media/quoted.jpg", 0),),
    )
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(value, profile, [post], lambda candidate: candidate.kind is PostKind.QUOTE, now=post.published_at)
    if capabilities is not None:
        value["outbox"][0]["enabled_capabilities"] = capabilities
    state.save_state(storage, value)
    root = tmp_path / "vision" / profile.id / post.post_id
    root.mkdir(parents=True)
    authored = root / "0.jpg"
    quoted = root / "1.jpg"
    authored.write_bytes(b"authored")
    quoted.write_bytes(b"quoted")
    bundle = VisionBundle(
        root,
        (
            VisionAsset("tweet", post.post_id, 0, authored),
            VisionAsset("quoted_tweet", post.post_id, 0, quoted),
        ),
        0,
    )
    articles = ArticleBundle(
        (
            ArticleSource(
                "https://example.com/article",
                "https://example.com/article",
                "Article context",
                "Article market detail.",
                False,
            ),
        ),
        1,
        0,
    )
    prepared = []
    prepared_articles = []
    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(
        scan.rsshub,
        "fetch_profile_items",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("queue-only mode fetched a source")),
    )
    monkeypatch.setattr(scan, "_prepare_agent_vision", lambda *args: prepared.append(args) or bundle)
    monkeypatch.setattr(scan, "_prepare_article_context", lambda *args: prepared_articles.append(args) or articles)
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: None)
    flock_operations = []
    monkeypatch.setattr(scan.fcntl, "flock", lambda _lock, operation: flock_operations.append(operation))
    monkeypatch.setenv("X_POST_WATCH_QUEUE_ONLY", "1")

    result = scan.run(now=current, dry_run=False)

    assert prepared == ([(post, storage, False, (post,))] if swing_expected else [])
    assert prepared_articles == [((post,), False)]
    assert result["item"]["vision_asset_paths"] == ([str(authored),str(quoted)] if swing_expected else [])
    assert ("Authored X post image 1" in result["item"]["post_text"]) is swing_expected
    assert ("Quoted X post image 1" in result["item"]["post_text"]) is swing_expected
    assert "Article 1 title: Article context" in result["item"]["post_text"]
    assert flock_operations == [
        scan.fcntl.LOCK_EX | scan.fcntl.LOCK_NB,
        scan.fcntl.LOCK_UN,
        scan.fcntl.LOCK_EX,
    ]


def test_queue_worker_discards_context_when_the_claimed_lease_changes(tmp_path, monkeypatch, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    current = datetime(2026, 8, 24, 10, 0, tzinfo=scan.WIB)
    storage = tmp_path / "state.json"
    post = SourcePost(
        profile.id,
        "101",
        "https://x.com/Kutekians/status/101",
        current - timedelta(hours=2),
        "A substantive market post",
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )
    value = state.new_state()
    value["profiles"][profile.id] = {"cursor": "100"}
    state.observe_posts(value, profile, [post], lambda _candidate: True, now=post.published_at)
    state.save_state(storage, value)

    def change_lease(*_args):
        current_value = state.load_state(storage)
        current_value["outbox"][0]["agent_lease_until"] = "2026-08-24T10:30:00+07:00"
        state.save_state(storage, current_value)
        return None

    monkeypatch.setattr(scan, "state_path", lambda: storage)
    monkeypatch.setattr(scan, "config_path", lambda: config_path)
    monkeypatch.setattr(scan, "_prepare_agent_vision", change_lease)
    monkeypatch.setattr(scan, "_prepare_article_context", change_lease)
    monkeypatch.setattr(scan.discord, "post_text", lambda *args: None)
    monkeypatch.setenv("X_POST_WATCH_QUEUE_ONLY", "1")

    result = scan.run(now=current, dry_run=False)

    assert result == {"wakeAgent": False, "item": None}
    assert state.load_state(storage)["outbox"][0]["agent_phase"] == "awaiting_agent"


def test_cleanup_agent_vision_ignores_os_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(
        scan.vision_media,
        "cleanup_event",
        lambda *_args: (_ for _ in ()).throw(OSError("filesystem unavailable")),
    )

    scan._cleanup_agent_vision(tmp_path / "state.json", {"profile_id": "kutekians", "post_id": "101"})


def test_heartbeat_format_is_canonical():
    value = scan.format_heartbeat(datetime(2026, 7, 28, 6, 0, tzinfo=scan.WIB), scan.RunStats())
    assert value == "🫀 x-post · 06:00 WIB · 0 fetched · 0 filtered · 0 queued · 0 delivered · 0 errors · 0 pending · owner pending 0 · oldest 0m"


def test_x_board_event_requires_one_exact_ticker_led_source_title() -> None:
    event = swing_event(source_text="KPIG: Wave IV diproyeksikan menuju area 97 sampai 108")

    board_event = scan.board_source_event(event, profile_fixture())

    assert board_event["source_title"] == "KPIG: Wave IV diproyeksikan menuju area 97 sampai 108"
    assert board_event["media_urls"] == ["https://img.example/chart.png", "https://img.example/quoted.png"]


def test_x_board_event_accepts_whitespace_ticker_title_and_normalizes_only_board_title() -> None:
    event = swing_event(source_text="PGAS Berpeluang Memulai Uptrendnya")
    event["title"] = "PGAS: Berpeluang Memulai Uptrend"

    board_event = scan.board_source_event(event, profile_fixture())

    assert board_event["source_title"] == "PGAS: Berpeluang Memulai Uptrendnya"
    assert "*(Ringkasan)*" in board_event["all_content"]
    assert "PGAS Berpeluang Memulai Uptrendnya" not in board_event["all_content"]
    assert board_event["plan"] is None


def test_x_board_title_preserves_source_visible_markdown_and_link_text() -> None:
    event = swing_event(
        '<p>KPIG: Wave | <a href="https://example.test/chart">support* &amp; resistance</a></p><p>Second source line</p>'
    )

    assert scan.board_source_event(event, profile_fixture())["source_title"] == "KPIG: Wave | support* & resistance"


def test_multiticker_or_non_ticker_led_x_source_stays_all_only() -> None:
    assert scan.board_source_event(swing_event(source_text="KPIG dan RAJA menarik"), profile_fixture()) is None
    assert scan.board_source_event(swing_event(source_text="Update teknikal hari ini"), profile_fixture()) is None
    assert scan.board_source_event(swing_event(source_text="KPIG: Technical setup; RAJA: setup lain"), profile_fixture()) is None


@pytest.mark.parametrize("text", ["KPIG: Technical setup\nRAJA: setup lain", "<p>KPIG: Technical setup</p><p>RAJA: setup lain</p>"])
def test_multiline_multi_ticker_source_is_all_only(text):
    assert scan.board_source_event(swing_event(text), profile_fixture()) is None


def test_second_ticker_in_another_thread_post_is_all_only():
    event = swing_event("KPIG: Technical setup")
    event["thread_posts"].append(swing_event("RAJA: setup lain")["post"])
    assert scan.board_source_event(event, profile_fixture()) is None


def test_board_failure_does_not_repost_existing_all_messages(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    monkeypatch.setattr(scan.discord, "post_text", lambda *_: "all-message")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)

    assert scan._deliver(value, profiles(), 0, False, tmp_path / "state.json", stats(), now()) is False
    assert value["outbox"][0]["text_message_ids"] == ["all-message"]
    assert value["outbox"][0]["board_phase"] == "pending"


def test_swing_all_delivery_includes_board_link_before_view_on_x(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    value["outbox"][0]["text_index"] = 0
    sent = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_: sent.append(content) or "all-message")

    assert scan._deliver(value, profiles(), 0, False, tmp_path / "state.json", stats(), now()) is False
    assert "**Board:** <#1548273399069933720>" in sent[0]
    assert "**Status date:** 15 Sep 2026 10:00 WIB" in sent[0]
    assert sent[0].index("**Board:**") < sent[0].index("[View on X]")
    assert value["outbox"][0]["delivery_at"] == now().isoformat()


def test_board_retry_accepts_without_reposting_all_messages(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    all_messages = []
    board_payloads = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *_: all_messages.append("all-message") or "all-message")
    monkeypatch.setattr(scan.discord, "post_media", lambda *_: all_messages.append("all-media") or "all-media")
    monkeypatch.setattr(scan, "submit_board_event", lambda *_: False)

    assert scan._deliver(value, profiles(), 0, False, tmp_path / "state.json", stats(), now()) is False

    monkeypatch.setattr(scan, "submit_board_event", lambda payload, *_: board_payloads.append(payload) or True)
    assert scan._deliver(value, profiles(), 0, False, tmp_path / "state.json", stats(), now() + timedelta(minutes=1)) is True
    assert value["outbox"] == []
    assert all_messages == []
    assert "**Status date:** 15 Sep 2026 10:00 WIB" in board_payloads[0]["all_content"]


def test_all_text_then_ordered_images_then_board_in_one_delivery(tmp_path, monkeypatch) -> None:
    swing_profile = replace(profile_fixture(), media_policy="omit_last")
    value = ready_swing_state(tmp_path)
    event = value["outbox"][0]
    event["text_index"] = event["media_index"] = 0
    event["text_message_ids"] = []
    event["media_message_ids"] = []
    refs = [f"20000000-0000-4000-8000-{index:012d}" for index in range(1, 4)]
    urls = [f"source-media-ref:{ref}" for ref in refs]
    event["post"]["media"] = [{"index": index, "url": url} for index, url in enumerate(urls[:2])]
    event["post"]["quoted_media"] = [{"index": 0, "url": urls[2]}]
    event["thread_posts"] = [event["post"]]
    event["source_media_refs"] = {ref: {"ref": ref} for ref in refs}
    event["source_media_paths"] = {ref: str(tmp_path / f"chart-{index}.jpg") for index, ref in enumerate(refs)}
    sequence = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_: sequence.append(("text", content)) or "text-1")
    monkeypatch.setattr(scan.discord, "post_media", lambda url, *_args, **_kwargs: sequence.append(("media", url)) or f"media-{len(sequence)}")
    monkeypatch.setattr(scan, "submit_board_event", lambda payload, *_: sequence.append(("board", payload["media_paths"])) or False)
    storage = tmp_path / "state.json"
    assert scan._deliver(value, {swing_profile.id: swing_profile}, 0, False, storage, stats(), now()) is False
    assert [kind for kind, _ in sequence] == ["text", "media", "media", "media", "board"]
    assert [item[1] for item in sequence[1:4]] == urls
    assert sequence[-1][1] == [event["source_media_paths"][ref] for ref in refs]
    assert event["text_message_ids"] == ["text-1"]
    assert len(event["media_message_ids"]) == 3
    assert scan._deliver(value, {swing_profile.id: swing_profile}, 0, False, storage, stats(), now() + timedelta(minutes=1)) is False
    assert [kind for kind, _ in sequence] == ["text", "media", "media", "media", "board", "board"]


def test_swing_transient_retry_reuses_delivery_and_board_keys_without_live_clients(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    event = value["outbox"][0]
    event["text_index"] = event["media_index"] = 0
    event["text_message_ids"] = []
    event["media_message_ids"] = []
    event["post"]["quoted_media"] = []
    event["thread_posts"][0]["quoted_media"] = []
    sequence = []
    text_nonces = []
    media_nonces = []
    board_keys = []
    attempts = {"media": 0}

    def fake_text(content, channel_id, dry_run, nonce):
        text_nonces.append(nonce)
        sequence.append("all-text")
        return "all-message"

    def fake_media(url, channel_id, dry_run, nonce, *_args, **_kwargs):
        media_nonces.append(nonce)
        attempts["media"] += 1
        sequence.append("all-media")
        if attempts["media"] == 1:
            raise scan.discord.DeliveryOwnerPending("fake pending media")
        return "media-message"

    def fake_board(payload, *_args):
        board_keys.append(payload["event_key"])
        sequence.append("board")
        return len(board_keys) > 1

    monkeypatch.setattr(scan.discord, "post_text", fake_text)
    monkeypatch.setattr(scan.discord, "post_media", fake_media)
    monkeypatch.setattr(scan, "submit_board_event", fake_board)
    monkeypatch.setattr(scan.discord, "delivery_client_from_environment", lambda **_kwargs: pytest.fail("live Delivery Owner client used"))
    import source_media
    monkeypatch.setattr(source_media, "client_from_environment", lambda: pytest.fail("live Source Media Owner client used"))

    storage = tmp_path / "state.json"
    assert scan._deliver(value, profiles(), 0, False, storage, stats(), now()) is False
    assert scan._deliver(value, profiles(), 0, False, storage, stats(), now() + timedelta(minutes=1)) is False
    assert scan._deliver(value, profiles(), 0, False, storage, stats(), now() + timedelta(minutes=2)) is True

    assert sequence == ["all-text", "all-media", "all-media", "board", "board"]
    assert len(text_nonces) == 1
    assert len(media_nonces) == 2 and media_nonces[0] == media_nonces[1]
    assert scan.discord.operation_key_for_nonce(media_nonces[0]) == scan.discord.operation_key_for_nonce(media_nonces[1])
    assert len(board_keys) == 2 and board_keys[0] == board_keys[1]
    assert value["outbox"] == []


def test_permanent_missing_media_is_skipped_and_board_handoff_continues(tmp_path, monkeypatch) -> None:
    value = ready_swing_state(tmp_path)
    event = value["outbox"][0]
    event["media_index"] = 0
    event["post"]["quoted_media"] = []
    event["thread_posts"][0]["quoted_media"] = []
    board_payloads = []
    monkeypatch.setattr(scan.discord, "post_media", lambda *_: (_ for _ in ()).throw(scan.discord.MediaUnavailable(404)))
    monkeypatch.setattr(scan, "submit_board_event", lambda payload, *_: board_payloads.append(payload) or True)
    stats = scan.RunStats()
    storage = tmp_path / "state.json"

    assert scan._deliver(value, profiles(), 0, False, storage, stats, now()) is True
    assert value["outbox"][0]["media_index"] == 1
    assert value["outbox"][0]["media_skipped_urls"] == ["https://img.example/chart.png"]
    assert stats.degraded is True

    assert scan._deliver(value, profiles(), 0, False, storage, stats, now()) is True
    assert value["outbox"] == []
    assert board_payloads[0]["media_urls"] == []
    assert value["deliveries"][0]["media_skipped_urls"] == ["https://img.example/chart.png"]


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('{"accepted":true}', True),
        ('{"accepted":1}', False),
        ('{"accepted":true,"board_url":"https://discord.com/channels/940285152335110204/123"}', True),
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


def test_delivery_includes_quoted_media_when_each_quoting_post_has_media(tmp_path, monkeypatch, config_path):
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
    assert delivered == ["https://img.example/root.jpg", "https://img.example/root-quote.jpg",
                         "https://img.example/latest.jpg", "https://img.example/quote.jpg"]


def test_delivery_uses_quoted_media_when_quoting_post_has_no_media(tmp_path, monkeypatch, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = SourcePost(
        profile.id, "101", "https://x.com/Kutekians/status/101", datetime.now(UTC),
        "Quote", PostKind.QUOTE, "https://x.com/external/status/0", "External quote",
        (), (SourceMedia("https://img.example/quoted.jpg", 0),),
    )
    value = state.new_state()
    value["outbox"].append({
        "profile_id": profile.id, "post_id": post.post_id, "text_index": 1, "media_index": 0,
        "post": state.serialize_post(post), "thread_posts": [state.serialize_post(post)],
    })
    delivered = []
    monkeypatch.setattr(scan.discord, "post_media", lambda url, *_args: delivered.append(url) or "test")

    while value["outbox"]:
        assert scan._deliver(value, {profile.id: profile}, 0, True, tmp_path / "state.json", scan.RunStats()) is True

    assert delivered == ["https://img.example/quoted.jpg"]


def test_delivery_omit_last_removes_only_final_unique_bundle_media(tmp_path, monkeypatch, config_path, profile_payload):
    profile_payload["media_policy"] = "omit_last"
    config_path.write_text(__import__("json").dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    root = SourcePost(profile.id, "101", "https://x.com/Kutekians/status/101", datetime.now(UTC), "Root", PostKind.QUOTE, "https://x.com/external/status/0", "Earlier external quote", (SourceMedia("https://img.example/root.jpg", 0),), (SourceMedia("https://img.example/root-quote.jpg", 0),))
    latest = SourcePost(profile.id, "102", "https://x.com/Kutekians/status/102", datetime.now(UTC), "Latest", PostKind.QUOTE, "https://x.com/external/status/1", "External: Quote", (SourceMedia("https://img.example/latest.jpg", 0),), (SourceMedia("https://img.example/quote.jpg", 0),))
    value = state.new_state()
    value["outbox"].append({
        "profile_id": profile.id, "post_id": latest.post_id, "route": "macro_news", "text_index": 1, "media_index": 0,
        "post": state.serialize_post(latest), "thread_posts": [state.serialize_post(root), state.serialize_post(latest)],
    })
    delivered = []
    monkeypatch.setattr(scan.discord, "post_media", lambda url, *_args: delivered.append(url) or "test")
    storage = tmp_path / "state.json"
    while value["outbox"]:
        assert scan._deliver(value, {profile.id: profile}, 0, True, storage, scan.RunStats()) is True
    assert delivered == ["https://img.example/root.jpg", "https://img.example/root-quote.jpg",
                         "https://img.example/latest.jpg"]


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
