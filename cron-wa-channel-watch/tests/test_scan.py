from datetime import datetime, timezone, timedelta
import json

import pytest

import scan
from event_queue import enqueue
from normalize import normalize_bridge_event


def profile():
    return {
        "id": "bri-danareksa-sekuritas",
        "enabled": True,
        "channel_jid": "12345@newsletter",
        "channel_url": "https://whatsapp.com/channel/0029Example",
        "display_name": "BRI Danareksa Sekuritas",
        "emoji": "<:bridanareksa:1549256273109848124>",
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


def write_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"version": 1, "profiles": [profile()]}), encoding="utf-8")
    return config_path


def event(message_id, timestamp, text="BBCA mencatat laba bersih naik", media=None):
    return normalize_bridge_event({
        "channel_jid": "12345@newsletter",
        "message_id": message_id,
        "published_at": timestamp,
        "text": text,
        "media": media or [],
    })


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


def test_no_post_delivery_handles_source_media_without_network(tmp_path, capsys):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    media_path = tmp_path / "image.jpg"
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
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    submitted = scan.submit_analysis(
        config_path=config_path,
        state_path=state_path,
        now=now + timedelta(minutes=2),
        no_post=True,
        payload={
            "event_key": claimed["item"]["event_key"],
            "is_relevant": True,
            "title": "BBCA: Laba Bersih Naik",
            "summary": "*(Ringkasan)* Laba bersih naik.",
            "route": "macro_news",
        },
    )
    assert submitted["delivered"] == 1
    assert "[dry-run] Discord media" in capsys.readouterr().out


def test_technical_review_is_guarded_and_deterministically_delivered_to_swing(tmp_path, capsys):
    queue_dir = tmp_path / "queue"
    config_path = write_config(tmp_path)
    state_path = tmp_path / "state.json"
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    enqueue(queue_dir, event("baseline", "2026-09-09T00:00:00Z"))
    scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now, no_post=True)
    enqueue(queue_dir, event(
        "technical",
        "2026-09-10T00:01:00Z",
        "_*#TechnicalReview #ClientRequest*_\n*TINS* breakout resistance 4.600 dan bullish.",
    ))
    claimed = scan.run(config_path=config_path, state_path=state_path, queue_dir=queue_dir, now=now + timedelta(minutes=1), no_post=True)
    assert claimed["item"]["relevance_guard_required"] is True

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
            "title": "TINS: Breakout Resistance 4.600",
            "summary": "*(Ringkasan)* TINS mempertahankan tren bullish setelah breakout resistance 4.600.",
            "route": "macro_news",
        },
    )
    assert submitted["agent_phase"] == "delivered"
    output = capsys.readouterr().out
    assert "1525102458253217803" in output
    assert "1531655369884045382" not in output


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
                "title": "TINS: Analisis Saham",
                "summary": "*(Ringkasan)* TINS mencatat kinerja yang kuat.",
                "route": "id_stocks_swing",
            },
        )
