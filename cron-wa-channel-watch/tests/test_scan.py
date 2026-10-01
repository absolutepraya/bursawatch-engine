from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

import pytest

import scan
from event_queue import enqueue, serialize_event
from normalize import normalize_bridge_event
import state


def profile(**overrides):
    value = {
        "id": "bri-danareksa-sekuritas",
        "enabled": True,
        "mode": "forward",
        "channel_jid": "12345@newsletter",
        "channel_url": "https://whatsapp.com/channel/0029Example",
        "display_name": "BRI Danareksa Sekuritas",
        "emoji": "<:bridanareksa:1551797903927025797>",
        "status_emojis": {
            "up": "<:up:1531285100346740766>",
            "down": "<:down:1531285063986053200>",
            "hold": "<:hold:1531284248235868333>",
        },
        "discord_channels": [
            {"key": "macro_news", "channel_id": "1531655369884045382", "description": "Macro"},
            {"key": "id_stocks_news", "channel_id": "1525102508714889257", "description": "IDX news"},
            {"key": "id_stocks_swing", "channel_id": "1525102458253217803", "description": "IDX swing"},
        ],
        "forward_media": True,
        "enable_llm_title": True,
        "enable_llm_summary": True,
        "enable_llm_routing": True,
        "enable_llm_relevance_filter": True,
        "relevance_scope": "financial_market",
        "additional_prompt_instruction": "",
        "max_items_per_poll": 20,
    }
    value.update(overrides)
    return value


def write_config(tmp_path, profiles=None):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"version": 2, "profiles": profiles or [profile()]}), encoding="utf-8")
    return config_path


def observe_profile():
    return profile(
        id="ins",
        mode="observe",
        emoji=None,
        status_emojis={"up": None, "down": None, "hold": None},
        discord_channels=[],
        forward_media=False,
        enable_llm_title=False,
        enable_llm_summary=False,
        enable_llm_routing=False,
        enable_llm_relevance_filter=False,
    )


def event(message_id, timestamp, text="BBCA mencatat laba bersih naik", media=None):
    return normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": message_id,
        "published_at": timestamp,
        "text": text,
        "media": media or [],
    })


def test_run_reports_the_registered_hermes_job_to_the_control_plane(tmp_path, monkeypatch):
    calls = []
    events = []
    finishes = []

    class RecordingControlRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            calls.append((args, kwargs))
            return cls()

        def event(self, event_id, **kwargs):
            events.append((event_id, kwargs))
            return None

        def finish(self, status, error=None):
            finishes.append((status, error))
            return None

    monkeypatch.setattr(scan, "ControlPlaneRun", RecordingControlRun)

    scan.run(
        config_path=write_config(tmp_path),
        state_path=tmp_path / "state.json",
        queue_dir=tmp_path / "queue",
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        no_post=True,
    )

    assert calls == [
        (
            ("WHATSAPP_CHANNEL_WATCH", None),
            {"scheduler_job_id": "bursawatch-wa-channel-watch"},
        )
    ]
    assert [event_id for event_id, _kwargs in events] == [
        "run-started",
        "source-queue-inspected",
        "delivery-drain-completed",
        "run-completed",
    ]
    assert events[1][1]["attributes"] == {
        "queue_items": 0,
        "enabled_profiles": 1,
        "initialized_profiles": 0,
        "source_items": 0,
        "queued": 0,
        "archived": 0,
        "expired_agent_leases": 0,
    }
    assert finishes == [("ok", None)]


def test_first_run_is_future_only_and_later_run_claims_one(tmp_path):
    queue_dir = tmp_path / "queue"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("old", "2026-09-09T00:00:00Z"))
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    first = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    assert first["wakeAgent"] is False
    enqueue(queue_dir, event("new", "2026-09-10T00:01:00Z"))
    second = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    assert second["wakeAgent"] is True
    assert second["item"]["post_id"] == "new"
    third = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=2), no_post=True)
    assert third["wakeAgent"] is False


def test_iso_cutover_cursor_admits_a_future_numeric_bridge_timestamp(tmp_path):
    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    state.save(
        state_path,
        {
            "version": 1,
            "profiles": {
                "bri-danareksa-sekuritas": {
                    "cursor": {
                        "published_at": "2026-09-10T00:00:00Z",
                        "event_key": "12345@newsletter:cutover",
                    },
                    "cutover_complete": True,
                }
            },
            "outbox": [],
        },
    )
    published = datetime(2026, 9, 11, tzinfo=timezone.utc)
    raw_bridge_event = {
        "schema_version": 1,
        "event_key": "12345@newsletter:numeric-future",
        "channel_jid": "12345@newsletter",
        "message_id": "numeric-future",
        "published_at": int(published.timestamp()),
        "text": "BBCA mencatat laba bersih naik",
        "links": [],
        "media": [],
        "received_at": published.isoformat(),
    }
    (queue_dir / "numeric-future.json").write_text(json.dumps(raw_bridge_event), encoding="utf-8")

    result = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        now=published + timedelta(minutes=1),
        no_post=True,
    )

    assert result["wakeAgent"] is True
    assert result["item"]["event_key"] == "12345@newsletter:numeric-future"


def test_expired_agent_lease_is_reclaimable(tmp_path):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("new", "2026-09-10T00:01:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, event("newer", "2026-09-10T00:02:00Z"))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    assert claimed["wakeAgent"] is True
    reclaimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=17), no_post=True)
    assert reclaimed["wakeAgent"] is True


def test_submission_moves_event_to_ready_or_filtered(tmp_path):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    result = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    assert result["wakeAgent"] is False
    enqueue(queue_dir, event("new", "2026-09-10T00:01:00Z"))
    result = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    key = result["item"]["event_key"]
    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=1),
        payload={"event_key": key, "is_relevant": False},
        no_post=True,
    )
    assert submitted["agent_phase"] == "filtered"

    with pytest.raises(ValueError):
        scan.submit_analysis(config_path=config_path, state_path=state_path, now=now + timedelta(minutes=2), no_post=True, payload={"event_key": key, "is_relevant": False})


def test_forward_profile_without_llm_flags_delivers_a_deterministic_source_post(tmp_path, capsys):
    queue_dir = tmp_path / "queue"
    config_path = write_config(
        tmp_path,
        [
            profile(
                enable_llm_title=False,
                enable_llm_summary=False,
                enable_llm_routing=False,
                enable_llm_relevance_filter=False,
            )
        ],
    )
    state_path = tmp_path / "state.json"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, event("deterministic", "2026-09-10T00:01:00Z"))

    result = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        now=now + timedelta(minutes=1),
        no_post=True,
    )

    assert result["delivered"] == 1
    assert result["wakeAgent"] is False
    assert state.load(state_path)["outbox"][0]["agent_phase"] == "delivered"
    assert "[dry-run] Discord text" in capsys.readouterr().out


def test_scanner_and_submission_require_an_absolute_archive_root(tmp_path):
    config_path = write_config(tmp_path)

    with pytest.raises(ValueError, match="archive path"):
        scan.run(
            config_path=config_path,
            state_path=tmp_path / "state.json",
            queue_dir=tmp_path / "queue",
            archive_dir=Path("relative-archive"),
            no_post=False,
        )
    with pytest.raises(ValueError, match="archive path"):
        scan.submit_analysis(
            config_path=config_path,
            state_path=tmp_path / "state.json",
            archive_dir=Path("relative-archive"),
            payload={},
            no_post=False,
        )


def test_submission_reports_safe_control_plane_outcome(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, event("new", "2026-09-10T00:01:00Z"))
    claimed = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        now=now + timedelta(minutes=1),
        no_post=True,
    )
    calls = []
    events = []
    finishes = []

    class RecordingControlRun:
        @classmethod
        def begin(cls, *args, **kwargs):
            calls.append((args, kwargs))
            return cls()

        def event(self, event_id, **kwargs):
            events.append((event_id, kwargs))

        def finish(self, status, error=None):
            finishes.append((status, error))

    monkeypatch.setattr(scan, "ControlPlaneRun", RecordingControlRun)

    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={"event_key": claimed["item"]["event_key"], "is_relevant": False},
    )

    assert submitted["agent_phase"] == "filtered"
    assert calls == [
        (
            ("WHATSAPP_CHANNEL_WATCH", None),
            {
                "scheduler_job_id": "bursawatch-wa-channel-watch",
                "trigger": "agent_submission",
            },
        )
    ]
    assert [event_id for event_id, _kwargs in events] == [
        "agent-submission-started",
        "agent-submission-accepted",
        "agent-delivery-drain-completed",
    ]
    assert events[1][1]["attributes"] == {
        "is_relevant": False,
        "agent_phase": "filtered",
    }
    assert finishes == [("ok", None)]


def test_no_post_delivery_handles_source_media_without_network(tmp_path, capsys):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    staging_dir = tmp_path / "media-staging"
    staging_dir.mkdir()
    media_path = staging_dir / "image.jpg"
    media_path.write_bytes(b"test image")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "media",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "BBCA mencatat laba bersih naik https://example.test/report",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(media_path)}],
    }))
    claimed = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        media_staging_dir=staging_dir,
        now=now + timedelta(minutes=1),
        no_post=True,
    )
    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "BBCA: Laba Bersih Naik",
                "summary": "*(Ringkasan)* Laba bersih naik.",
                "route": "macro_news",
            }],
        },
    )
    assert submitted["delivered"] == 1
    assert "[dry-run] Discord media" in capsys.readouterr().out


def test_technical_review_is_guarded_and_deterministically_delivered_to_swing(tmp_path, capsys, monkeypatch):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    image = tmp_path / "archived-chart.jpg"
    image.write_bytes(b"chart")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "technical",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "_*#TechnicalReview #ClientRequest*_\n*TINS* breakout resistance 4.600 dan bullish.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(image)}],
    }))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    assert claimed["item"]["relevance_guard_required"] is True
    monkeypatch.setattr(scan, "_archived_images", lambda _root, _event: (image,))

    with pytest.raises(ValueError, match="submitted as relevant"):
        scan.submit_analysis(
            config_path=config_path,
            state_path=state_path,
            now=now + timedelta(minutes=2),
            no_post=True,
            payload={"event_key": claimed["item"]["event_key"], "is_relevant": False},
        )

    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "TINS: Breakout Resistance 4.600",
                "summary": "TINS mempertahankan tren bullish setelah breakout resistance 4.600.",
                "route": "id_stocks_swing",
                "sentiment": "Bullish",
            }],
        },
    )
    assert submitted["agent_phase"] == "delivered"
    output = capsys.readouterr().out
    assert "1525102458253217803" in output
    assert "1531655369884045382" not in output


def test_technical_review_without_archive_image_delivers_source_text_without_board(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, event("technical-missing-chart", "2026-09-10T00:01:00Z", "#TechnicalReview\nTINS breakout resistance 4.600."))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    monkeypatch.setattr(scan, "_archived_images", lambda _root, _event: ())
    posted: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda content, *_args, **_kwargs: posted.append(content))
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args, **_kwargs: posted.append("media"))

    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "TINS: Breakout Resistance 4.600",
                "summary": "TINS menembus resistance 4.600.",
                "route": "id_stocks_swing",
                "ticker": "TINS",
                "sentiment": "Bullish",
            }],
        },
    )

    assert submitted["agent_phase"] == "delivered"
    assert submitted["delivered"] == 1
    assert len(posted) == 1
    assert "#TechnicalReview\\nTINS breakout resistance 4.600." in posted[0]
    assert "Source chart unavailable" in posted[0]
    assert "**Board:**" not in posted[0]
    saved = state.load(state_path)["outbox"][0]
    assert saved["media_delivery_status"] == "unavailable"
    assert saved["board_phase"] == "not_eligible"


def test_technical_review_always_forwards_its_verified_chart(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path, [profile(forward_media=False)])
    state_path = tmp_path / "state.json"
    image = tmp_path / "archived-chart.jpg"
    image.write_bytes(b"chart")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "technical-chart-required",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "#TechnicalReview\nTINS breakout resistance 4.600.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(image)}],
    }))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    monkeypatch.setattr(scan, "_archived_images", lambda _root, _event: (image,))
    posted: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args, **_kwargs: posted.append("text"))
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args, **_kwargs: posted.append("media"))

    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "TINS: Breakout Resistance 4.600",
                "summary": "TINS menembus resistance 4.600.",
                "route": "id_stocks_swing",
                "sentiment": "Bullish",
            }],
        },
    )

    assert submitted["agent_phase"] == "delivered"
    assert posted == ["text", "media"]


def test_non_technical_posts_cannot_submit_the_swing_route(tmp_path):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, event("nontechnical", "2026-09-10T00:01:00Z", "TINS has strong earnings and a chart image."))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)

    with pytest.raises(ValueError, match="requires a leading #TechnicalReview"):
        scan.submit_analysis(
            config_path=config_path,
            state_path=state_path,
            now=now + timedelta(minutes=2),
            no_post=True,
            payload={
                "event_key": claimed["item"]["event_key"],
                "is_relevant": True,
                "items": [{
                    "title": "TINS: Analisis Saham",
                    "summary": "TINS mencatat kinerja yang kuat.",
                    "route": "id_stocks_swing",
                    "sentiment": "Bullish",
                }],
            },
        )


def test_cutover_quarantines_legacy_outbox_without_rewriting_it(tmp_path):
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    legacy = event("legacy", "2026-09-09T00:00:00Z")
    record = {
        "event_key": legacy.event_key,
        "profile_id": "bri-danareksa-sekuritas",
        "event": serialize_event(legacy),
        "agent_phase": "ready",
        "items": [{
            "title": "BBCA: Laba Bersih Naik",
            "summary": "*(Ringkasan)* BBCA mencatat laba bersih naik.",
            "route": "id_stocks_news",
            "ticker": "BBCA",
        }],
        "item_index": 0,
        "text_index": 0,
        "media_index": 0,
    }
    state.save(
        state_path,
        {
            "version": 1,
            "profiles": {
                "bri-danareksa-sekuritas": {
                    "cursor": {"published_at": "2026-09-10T00:00:00Z", "event_key": "cutover"},
                    "cutover_complete": True,
                }
            },
            "outbox": [record],
        },
    )

    result = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=tmp_path / "queue",
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        no_post=True,
    )

    assert result["delivered"] == 0
    assert result["wakeAgent"] is False
    assert state.load(state_path)["outbox"] == [record]


def test_observe_profile_never_processes_preexisting_outbox_work(tmp_path):
    state_path = tmp_path / "state.json"
    observed = event("observed-outbox", "2026-09-10T00:00:00Z")
    ready = {
        "event_key": observed.event_key,
        "profile_id": "ins",
        "event": serialize_event(observed),
        "agent_phase": "ready",
        "items": [{"title": "BBCA: Laba Bersih Naik", "summary": "*(Ringkasan)* BBCA mencatat laba bersih naik.", "route": "macro_news"}],
        "item_index": 0,
        "text_index": 0,
        "media_index": 0,
    }
    pending = {**ready, "event_key": "12345@newsletter:observed-pending", "agent_phase": "pending"}
    state.save(state_path, {"version": 1, "profiles": {}, "outbox": [ready, pending]})

    result = scan.run(
        config_path=write_config(tmp_path, [observe_profile()]),
        state_path=state_path,
        queue_dir=tmp_path / "queue",
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        no_post=True,
    )

    assert result["delivered"] == 0
    assert result["wakeAgent"] is False
    assert state.load(state_path)["outbox"] == [ready, pending]


def test_observation_profile_archives_but_never_wakes_or_changes_forward_cursor(tmp_path):
    queue_dir = tmp_path / "queue"
    enqueue(queue_dir, event("observed", "2026-09-10T00:01:00Z"))

    result = scan.run(
        config_path=write_config(tmp_path, [observe_profile()]),
        state_path=tmp_path / "state.json",
        queue_dir=queue_dir,
        archive_dir=tmp_path / "archive",
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        no_post=True,
    )

    assert result["archived"] == 1
    assert result["wakeAgent"] is False
    assert state.load(tmp_path / "state.json")["profiles"] == {}


def test_forwarding_waits_for_archive_before_claiming(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    archive_dir = tmp_path / "archive"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        archive_dir=archive_dir,
        now=now,
        no_post=True,
    )
    enqueue(queue_dir, event("blocked", "2026-09-10T00:01:00Z"))
    monkeypatch.setattr(
        scan.archive,
        "ensure",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        archive_dir=archive_dir,
        now=now + timedelta(minutes=1),
        no_post=True,
    )

    assert result["wakeAgent"] is False
    assert "disk full" in result["errors"][0]
    assert state.load(state_path)["profiles"]["bri-danareksa-sekuritas"]["cursor"]["event_key"].endswith(":baseline")


def test_one_macro_item_forwards_its_image_once_after_text(tmp_path, capsys):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    staging_dir = tmp_path / "media-staging"
    staging_dir.mkdir()
    image = staging_dir / "macro.jpg"
    image.write_bytes(b"macro image")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "macro-image",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "Menkeu baru dan revisi HPM nikel efektif.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(image)}],
    }))
    claimed = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        media_staging_dir=staging_dir,
        now=now + timedelta(minutes=1),
        no_post=True,
    )

    scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "Menkeu Baru dan Revisi HPM Nikel",
                "summary": "*(Ringkasan)* Pemerintah memperbarui kebijakan fiskal dan formula HPM nikel.",
                "route": "macro_news",
            }],
        },
    )

    output = capsys.readouterr().out
    assert output.count("[dry-run] Discord text") == 1
    assert output.count("[dry-run] Discord media") == 1
    assert "macro.jpg" not in output
    assert "Menkeu Baru dan Revisi HPM Nikel" in output


def test_delivery_never_uses_a_queue_media_path_outside_archive_staging(tmp_path, capsys):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    staging_dir = tmp_path / "media-staging"
    staging_dir.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"untrusted source")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "outside-media",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "BBCA mencatat laba bersih naik.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(outside)}],
    }))
    claimed = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        media_staging_dir=staging_dir,
        now=now + timedelta(minutes=1),
        no_post=True,
    )

    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "BBCA: Laba Bersih Naik",
                "summary": "*(Ringkasan)* BBCA mencatat laba bersih naik.",
                "route": "id_stocks_news",
            }],
        },
    )

    assert submitted["delivered"] == 1
    output = capsys.readouterr().out
    assert "[dry-run] Discord text" in output
    assert "[dry-run] Discord media" not in output
    record = state.load(state_path)["outbox"][0]
    assert record["agent_phase"] == "delivered"
    assert record["media_delivery_status"] == "unavailable"
    assert record["media_skipped_indexes"] == [0]
    assert record["media_error"] == "archived source media unavailable"
    assert record["last_error"] is None
    assert "source media unavailable" in submitted["errors"][0]


def test_missing_nontechnical_media_is_terminal_and_does_not_retry(tmp_path, monkeypatch):
    source = event(
        "missing-macro-media",
        "2026-09-10T00:01:00Z",
        "BBCA mencatat laba bersih naik.",
        media=[{"kind": "image", "mime": "image/jpeg"}],
    )
    profile_value = scan.config.load(write_config(tmp_path)).profiles[0]
    value = {
        "version": 1,
        "profiles": {},
        "outbox": [{
            "event_key": source.event_key,
            "profile_id": profile_value.id,
            "event": serialize_event(source),
            "agent_phase": "ready",
            "items": [{
                "title": "BBCA: Laba Bersih Naik",
                "summary": "*(Ringkasan)* BBCA mencatat laba bersih naik.",
                "route": "id_stocks_news",
            }],
            "item_index": 0,
            "text_index": 0,
            "media_index": 0,
            "board_phase": "pending",
        }],
    }
    posted: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args, **_kwargs: posted.append("text") or "text-id")
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args, **_kwargs: posted.append("media"))

    errors: list[str] = []
    assert scan._deliver_ready(
        value,
        {profile_value.id: profile_value},
        dry_run=False,
        state_path=tmp_path / "state.json",
        archive_dir=tmp_path / "archive",
        errors=errors,
    ) == 1
    record = value["outbox"][0]
    assert posted == ["text"]
    assert record["agent_phase"] == "delivered"
    assert record["media_delivery_status"] == "unavailable"
    assert record["media_skipped_indexes"] == [0]
    assert errors == [f"bri-danareksa-sekuritas: source media unavailable for {source.event_key}; text delivered without missing media"]

    retry_errors: list[str] = []
    assert scan._deliver_ready(
        value,
        {profile_value.id: profile_value},
        dry_run=False,
        state_path=tmp_path / "state.json",
        archive_dir=tmp_path / "archive",
        errors=retry_errors,
    ) == 0
    assert posted == ["text"]
    assert retry_errors == []


def test_partial_media_miss_is_preserved_across_a_transport_retry(tmp_path, monkeypatch):
    source = event(
        "partial-macro-media",
        "2026-09-10T00:01:00Z",
        "BBCA mencatat laba bersih naik.",
        media=[
            {"kind": "image", "mime": "image/jpeg"},
            {"kind": "image", "mime": "image/jpeg"},
        ],
    )
    profile_value = scan.config.load(write_config(tmp_path)).profiles[0]
    available = tmp_path / "available.jpg"
    available.write_bytes(b"available image")
    value = {
        "version": 1,
        "profiles": {},
        "outbox": [{
            "event_key": source.event_key,
            "profile_id": profile_value.id,
            "event": serialize_event(source),
            "agent_phase": "ready",
            "items": [{
                "title": "BBCA: Laba Bersih Naik",
                "summary": "*(Ringkasan)* BBCA mencatat laba bersih naik.",
                "route": "id_stocks_news",
            }],
            "item_index": 0,
            "text_index": 0,
            "media_index": 0,
            "board_phase": "pending",
        }],
    }
    posted_text: list[str] = []
    media_attempts: list[int] = []
    monkeypatch.setattr(scan, "_archived_media", lambda _root, _event: {1: ("image", available)})
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args, **_kwargs: posted_text.append("text") or "text-id")

    def fail_once_then_succeed(*_args, **_kwargs):
        media_attempts.append(1)
        if len(media_attempts) == 1:
            raise RuntimeError("discord upload unavailable")

    monkeypatch.setattr(scan.discord, "post_media", fail_once_then_succeed)

    first_errors: list[str] = []
    assert scan._deliver_ready(
        value,
        {profile_value.id: profile_value},
        dry_run=False,
        state_path=tmp_path / "state.json",
        archive_dir=tmp_path / "archive",
        errors=first_errors,
    ) == 0
    record = value["outbox"][0]
    assert record["agent_phase"] == "ready"
    assert record["media_index"] == 1
    assert record["media_skipped_indexes"] == [0]
    assert first_errors == ["discord upload unavailable"]

    second_errors: list[str] = []
    assert scan._deliver_ready(
        value,
        {profile_value.id: profile_value},
        dry_run=False,
        state_path=tmp_path / "state.json",
        archive_dir=tmp_path / "archive",
        errors=second_errors,
    ) == 1
    assert posted_text == ["text"]
    assert len(media_attempts) == 2
    assert record["agent_phase"] == "delivered"
    assert record["media_delivery_status"] == "partial"
    assert record["media_error"] == "archived source media unavailable"
    assert second_errors == [f"bri-danareksa-sekuritas: source media unavailable for {source.event_key}; text delivered without missing media"]


def test_many_items_never_duplicate_one_source_image(tmp_path, capsys):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    image = tmp_path / "roundup.jpg"
    image.write_bytes(b"roundup image")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "two-items",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "BBCA melaporkan laba. Kebijakan nikel direvisi.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(image)}],
    }))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)

    scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [
                {"title": "BBCA: Laba Bersih Meningkat", "summary": "*(Ringkasan)* BBCA melaporkan laba meningkat.", "route": "id_stocks_news"},
                {"title": "Revisi Kebijakan Nikel", "summary": "*(Ringkasan)* Pemerintah merevisi kebijakan nikel.", "route": "macro_news"},
            ],
        },
    )

    output = capsys.readouterr().out
    assert output.count("[dry-run] Discord text") == 2
    assert "[dry-run] Discord media" not in output


def test_single_ticker_technical_review_hands_off_only_after_all_swing_text_and_image(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    image = tmp_path / "archived-chart.jpg"
    archive_dir = tmp_path / "archive"
    staging_dir = tmp_path / "media-staging"
    staging_dir.mkdir()
    image.write_bytes(b"chart")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    order: list[str] = []
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args, **_kwargs: order.append("text"))
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args, **_kwargs: order.append("media"))
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        archive_dir=archive_dir,
        media_staging_dir=staging_dir,
        now=now,
        no_post=False,
    )
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "technical-board",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "#TechnicalReview\nTINS breakout resistance 4.600.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(image)}],
    }))
    claimed = scan.run(
        config_path=config_path,
        state_path=state_path,
        queue_dir=queue_dir,
        archive_dir=archive_dir,
        media_staging_dir=staging_dir,
        now=now + timedelta(minutes=1),
        no_post=False,
    )
    order.clear()
    monkeypatch.setattr(scan, "_archived_images", lambda _root, _event: (image,))
    monkeypatch.setattr(
        scan.swing_board,
        "submit_chart_context",
        lambda *_args, **_kwargs: order.append("board") or scan.swing_board.BoardSubmission(True, None, True),
    )

    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        archive_dir=archive_dir,
        now=now + timedelta(minutes=2),
        no_post=False,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "TINS: Breakout Resistance 4.600",
                "summary": "TINS menembus resistance 4.600.",
                "route": "id_stocks_swing",
                "ticker": "TINS",
                "sentiment": "Bullish",
            }],
        },
    )

    assert submitted["delivered"] == 0
    assert order == ["text", "media", "board"]
    record = state.load(state_path)["outbox"][0]
    assert record["board_phase"] == "pending"
    assert record["agent_phase"] == "ready"


def test_swing_delivery_patches_direct_board_topic_after_media(tmp_path, monkeypatch):
    image = tmp_path / "archived-chart.jpg"
    image.write_bytes(b"chart")
    source = event("technical-direct-board", "2026-09-10T00:01:00Z", "#TechnicalReview\nTINS breakout resistance 4.600.", media=[{"kind": "image", "path": str(image)}])
    config_path = write_config(tmp_path)
    profile_value = scan.config.load(config_path).profiles[0]
    value = {
        "version": 1,
        "profiles": {},
        "outbox": [{
            "event_key": source.event_key,
            "profile_id": profile_value.id,
            "event": serialize_event(source),
            "agent_phase": "ready",
            "items": [{
                "title": "TINS: Breakout Resistance 4.600",
                "summary": "TINS menembus resistance 4.600.",
                "route": "id_stocks_swing",
                "ticker": "TINS",
                "sentiment": "Bullish",
            }],
            "item_index": 0,
            "text_index": 0,
            "media_index": 0,
            "board_phase": "pending",
        }],
    }
    monkeypatch.setattr(scan, "_archived_images", lambda _root, _event: (image,))
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args, **_kwargs: "discord-message-1")
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args, **_kwargs: "discord-media-1")
    monkeypatch.setattr(
        scan.swing_board,
        "submit_chart_context",
        lambda *_args, **_kwargs: scan.swing_board.BoardSubmission(
            True,
            "https://discord.com/channels/940285152335110204/999",
            False,
        ),
    )
    edits = []
    monkeypatch.setattr(scan.discord, "edit_board_link", lambda *args, **kwargs: edits.append((args, kwargs)) or True)

    delivered = scan._deliver_ready(
        value,
        {profile_value.id: profile_value},
        dry_run=False,
        state_path=tmp_path / "state.json",
        archive_dir=tmp_path / "archive",
        errors=[],
    )

    assert delivered == 1
    assert value["outbox"][0]["agent_phase"] == "delivered"
    assert value["outbox"][0]["text_message_ids"] == ["discord-message-1"]
    assert value["outbox"][0]["media_message_ids"] == ["discord-media-1"]
    assert edits and edits[0][0][1] == ["discord-message-1"]
    assert edits[0][0][2] == "https://discord.com/channels/940285152335110204/999"


def test_no_post_technical_delivery_never_invokes_the_board_adapter(tmp_path, monkeypatch):
    image = tmp_path / "archived-chart.jpg"
    image.write_bytes(b"chart")
    source = event("technical-no-post", "2026-09-10T00:01:00Z", "#TechnicalReview\nTINS breakout resistance 4.600.", media=[{"kind": "image", "path": str(image)}])
    config_path = write_config(tmp_path)
    profile_value = scan.config.load(config_path).profiles[0]
    value = {
        "version": 1,
        "profiles": {},
        "outbox": [{
            "event_key": source.event_key,
            "profile_id": profile_value.id,
            "event": serialize_event(source),
            "agent_phase": "ready",
            "items": [{
                "title": "TINS: Breakout Resistance 4.600",
                "summary": "TINS menembus resistance 4.600.",
                "route": "id_stocks_swing",
                "ticker": "TINS",
                "sentiment": "Bullish",
            }],
            "item_index": 0,
            "text_index": 0,
            "media_index": 0,
            "board_phase": "pending",
        }],
    }
    calls: list[str] = []
    monkeypatch.setattr(scan, "_archived_images", lambda _root, _event: (image,))
    monkeypatch.setattr(scan.discord, "post_text", lambda *_args, **_kwargs: calls.append("text"))
    monkeypatch.setattr(scan.discord, "post_media", lambda *_args, **_kwargs: calls.append("media"))
    monkeypatch.setattr(
        scan.swing_board,
        "submit_chart_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Board adapter must not run in no-post mode")),
    )

    delivered = scan._deliver_ready(
        value,
        {profile_value.id: profile_value},
        dry_run=True,
        state_path=tmp_path / "state.json",
        archive_dir=tmp_path / "archive",
        errors=[],
    )

    assert delivered == 1
    assert calls == ["text", "media"]
    assert value["outbox"][0]["board_phase"] == "accepted"


def test_missing_or_ambiguous_technical_chart_never_creates_board_context(tmp_path, monkeypatch):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    image = tmp_path / "archived-chart.jpg"
    image.write_bytes(b"chart")
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": "technical-ambiguous",
        "published_at": "2026-09-10T00:01:00Z",
        "text": "#TechnicalReview\nTINS dan ANTM breakout.",
        "media": [{"kind": "image", "mime": "image/jpeg", "path": str(image)}],
    }))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    monkeypatch.setattr(scan, "_archived_images", lambda _root, _event: (image,))
    board = []
    monkeypatch.setattr(scan.swing_board, "submit_chart_context", lambda *_args, **_kwargs: board.append(True))

    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "items": [{
                "title": "TINS: Breakout",
                "summary": "TINS dan ANTM mencatat breakout.",
                "route": "id_stocks_swing",
                "ticker": "TINS",
                "sentiment": "Sideways",
            }],
        },
    )

    assert submitted["delivered"] == 1
    assert board == []
    assert state.load(state_path)["outbox"][0]["board_phase"] == "not_eligible"
