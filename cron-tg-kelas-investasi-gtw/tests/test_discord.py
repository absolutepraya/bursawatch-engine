from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest

import discord
from discord import DiscordDeliveryError, DiscordRateLimitError, deliver_oldest_ready_event, nonce, post_text
from fixtures.messages import at, header
from render import render_event
from state import load_state, new_state, observe_messages, ready_events, save_state


def now() -> datetime:
    return datetime.fromisoformat("2026-08-11T09:00:00+07:00")


def image(path: Path, name: str) -> dict[str, object]:
    target = path / name
    target.write_bytes(b"\xff\xd8\xffsource image")
    return {"message_id": 101, "ordinal": 0, "path": str(target)}


def ready_event(*, media: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "event_key": "101:CTRA",
        "ticker": "CTRA",
        "header_message_id": 101,
        "source_message_ids": [101],
        "source_text": "Good to watch - CTRA #GTW",
        "source_published_at": "2026-08-11T09:00:00+07:00",
        "plan": {"buy_area": "-", "targets": "-", "stoploss": "-"},
        "media": media or [],
        "title": "CTRA: Akumulasi kuat",
        "summary": "*(Ringkasan)* Ringkasan tervalidasi.",
        "agent_phase": "ready",
        "agent_lease_until": None,
        "text_index": 0,
        "next_media_index": 0,
        "attempts": 0,
        "next_attempt_at": None,
        "last_error": None,
        "board_phase": "pending",
        "board_attempts": 0,
        "board_next_attempt_at": None,
        "board_last_error": None,
    }


def ready_gtw_event(header_text: str) -> dict[str, object]:
    """Create one accepted, All-delivered GTW bundle from the real state flow."""
    ticker = header_text.split(" - ", 1)[1].split(" ", 1)[0]
    value = new_state()
    value["cursor"] = 100
    observe_messages(value, [header(101, ticker), header(102, "BREN")], at("2026-08-11T09:00:00+07:00"))
    event = ready_events(value, now())[0]
    event.update(
        {
            "title": f"{ticker}: Akumulasi kuat",
            "summary": "*(Ringkasan)* Ringkasan tervalidasi.",
            "agent_phase": "delivering",
            "text_index": 1,
            "next_media_index": 0,
            "board_phase": "pending",
            "board_attempts": 0,
            "board_next_attempt_at": None,
            "board_last_error": None,
        }
    )
    assert len(render_event(event)) == 1
    return event


def state_with(event: dict[str, object]) -> dict[str, object]:
    return {"outbox": [event]}


def test_ready_gtw_event_keeps_media_until_board_accepts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_gtw_event("Good to watch - RAJA #GTW")
    state = {"version": 2, "cursor": None, "pending": [], "outbox": [event], "stats": {"observed": 0}}
    submitted: list[tuple[dict[str, object], Path | None, bool]] = []
    monkeypatch.setattr(discord, "post_text", lambda *_: "all-text")
    monkeypatch.setattr(discord, "post_file", lambda *_: "all-image")
    monkeypatch.setattr(discord, "submit_board_event", lambda payload, media, dry_run: submitted.append((payload, media, dry_run)) or True)

    assert deliver_oldest_ready_event(state, now(), False, media_root=tmp_path) is True

    assert state["outbox"] == []
    assert submitted[0][0]["event_key"] == "kelas-investasi:101:RAJA"


def test_gtw_payload_uses_exact_header_and_social_kind() -> None:
    event = ready_gtw_event("Good to watch - RAJA #GTW")
    payload = discord.board_payload(event)

    assert payload["kind"] == "social"
    assert payload["source_title"] == "Good to watch - RAJA #GTW"
    assert payload["ticker"] == "RAJA"
    assert payload["published_at"] == "2026-08-11T09:00:00+07:00"
    assert payload["source_url"] == "https://t.me/kelasinvestasiid/101"
    assert payload["source_status"] == "Good to watch"
    assert payload["all_content"] == render_event(event, include_board=False)[0]
    assert "**Board:**" not in payload["all_content"]


def test_gtw_board_adapter_creates_a_no_post_supporting_episode_with_current_format(
    tmp_path: Path,
) -> None:
    """Exercise the real GTW adapter through the Board's durable no-post owner."""
    event = ready_gtw_event("Good to watch - RAJA #GTW")
    payload = discord.board_payload(event)
    assert payload is not None

    board_bin = Path(__file__).resolve().parents[2] / "cron-dc-swing-board" / "bin"
    module_names = ("calendar", "models", "store", "discord_forum", "engine", "render")
    saved_modules = {name: sys.modules.get(name) for name in module_names}
    sys.path.insert(0, str(board_bin))
    for name in module_names:
        sys.modules.pop(name, None)
    try:
        from discord_forum import DiscordForumClient
        from engine import BoardEngine
        from models import SourceEvent
        from store import BoardStore

        owner = BoardEngine(
            BoardStore(tmp_path / "board.sqlite3"),
            DiscordForumClient(no_post=True),
        )
        incoming = SourceEvent.from_json(payload)
        assert owner.submit(incoming, now()) == "board_submitted"
        assert owner.drain(now=now()) == 1

        episode = owner.store.active_episode("RAJA")
        assert episode is not None
        assert (episode.lifecycle, episode.lifecycle_tag, episode.title) == (
            "source",
            "Supporting setup",
            "RAJA",
        )
        operations = owner.store.operations_for_ticker("RAJA")
        create = next(operation for operation in operations if operation.operation == "create_thread")
        assert create.status == "complete"
        assert create.payload["tag_names"] == ["Supporting setup"]
        assert create.payload["content"] == payload["all_content"]
        assert "**Source status:** Good to watch <:grey:1531279158913536182>" in create.payload["content"]
        assert "**Last updated:** 11 Aug 2026 09:00 WIB" in create.payload["content"]
        assert "**Board:**" not in create.payload["content"]
        assert all(operation.status == "complete" for operation in operations)
    finally:
        for name in module_names:
            sys.modules.pop(name, None)
        for name, module in saved_modules.items():
            if module is not None:
                sys.modules[name] = module
        sys.path.remove(str(board_bin))


def test_gtw_payload_skips_board_context_when_a_legacy_event_has_no_source_time() -> None:
    event = ready_gtw_event("Good to watch - RAJA #GTW")
    event["source_published_at"] = None

    assert discord.board_payload(event) is None


def test_gtw_board_handoff_uses_the_captured_header_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_gtw_event("Good to watch - RAJA #GTW")
    event["media"] = [image(tmp_path, "header.jpg")]
    event["next_media_index"] = 1
    submitted: list[tuple[dict[str, object], Path | None]] = []
    monkeypatch.setattr(discord, "submit_board_event", lambda payload, media, _dry_run: submitted.append((payload, media)) or True)

    assert deliver_oldest_ready_event(state_with(event), now(), False, media_root=tmp_path) is True

    assert submitted[0][0]["media_path"] == str(tmp_path / "header.jpg")
    assert submitted[0][1] == tmp_path / "header.jpg"


@pytest.mark.parametrize(
    "stdout",
    [
        '{"accepted":1}',
        '{"accepted":"true"}',
        '{"accepted":true,"extra":false}',
        '{"accepted":false}',
        '[]',
        'not-json',
    ],
)
def test_board_submission_requires_the_exact_boolean_owner_acknowledgement(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    completed = type("Completed", (), {"returncode": 0, "stdout": stdout})()
    monkeypatch.setattr(discord.subprocess, "run", lambda *_args, **_kwargs: completed)

    assert discord.submit_board_event({"event_key": "kelas-investasi:101:RAJA"}, None, False) is False


def test_board_submission_accepts_only_the_exact_true_owner_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = type("Completed", (), {"returncode": 0, "stdout": '{"accepted":true}'})()
    monkeypatch.setattr(discord.subprocess, "run", lambda *_args, **_kwargs: completed)

    assert discord.submit_board_event({"event_key": "kelas-investasi:101:RAJA"}, None, False) is True


def test_board_submission_retains_topic_url_for_the_followup_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = type("Completed", (), {"returncode": 0, "stdout": '{"accepted":true,"board_url":"https://discord.com/channels/940285152335110204/123"}'})()
    monkeypatch.setattr(discord.subprocess, "run", lambda *_args, **_kwargs: completed)
    payload = {"event_key": "kelas-investasi:101:RAJA"}

    assert discord.submit_board_event(payload, None, False) is True
    assert payload["_board_url"].endswith("/123")


def test_failed_gtw_board_handoff_retries_without_replaying_all_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_gtw_event("Good to watch - RAJA #GTW")
    state = state_with(event)
    monkeypatch.setattr(discord, "post_text", lambda *_: pytest.fail("All text must not replay"))
    monkeypatch.setattr(discord, "post_file", lambda *_: pytest.fail("All image must not replay"))
    handoffs = []
    monkeypatch.setattr(discord, "submit_board_event", lambda payload, *_: handoffs.append(payload["event_key"]) or False)

    assert deliver_oldest_ready_event(state, now(), False, media_root=tmp_path) is False
    assert state["outbox"] == [event]
    assert handoffs == [f"kelas-investasi:{event['event_key']}"]
    assert event["board_attempts"] == 1

    monkeypatch.setattr(discord, "submit_board_event", lambda *_: True)
    assert deliver_oldest_ready_event(state, now() + timedelta(seconds=60), False, media_root=tmp_path) is True
    assert state["outbox"] == []


def test_board_backoff_does_not_block_later_all_text_or_image(tmp_path, monkeypatch):
    first = ready_gtw_event("Good to watch - RAJA #GTW")
    first["board_attempts"] = 1
    first["board_next_attempt_at"] = (now() + timedelta(minutes=10)).isoformat()
    second = ready_event(media=[image(tmp_path, "second.jpg")])
    value = {"outbox": [first, second]}
    sent = []
    monkeypatch.setattr(discord, "post_text", lambda *_: sent.append("second-text"))
    monkeypatch.setattr(discord, "post_file", lambda *_: sent.append("second-image"))
    handoffs = []
    monkeypatch.setattr(discord, "submit_board_event", lambda payload, *_: handoffs.append(payload["event_key"]) or False)
    for _ in range(4):
        deliver_oldest_ready_event(value, now(), False, media_root=tmp_path)
    assert sent == ["second-text", "second-image"]
    assert second["text_index"] == 1 and second["next_media_index"] == 1
    assert len(value["outbox"]) == 2
    assert second["board_attempts"] == 0
    assert handoffs == []
    deliver_oldest_ready_event(value, now() + timedelta(minutes=10), False, media_root=tmp_path)
    assert handoffs == [f"kelas-investasi:{first['event_key']}"]


def test_delivery_sends_text_then_images_in_source_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_event(media=[image(tmp_path, "one.jpg"), image(tmp_path, "two.jpg")])
    sent: list[str] = []
    monkeypatch.setattr(discord, "post_text", lambda *args: sent.append("text"))
    monkeypatch.setattr(discord, "post_file", lambda path, *args: sent.append(Path(path).name))
    monkeypatch.setattr(discord, "submit_board_event", lambda *_: True)
    state = state_with(event)

    for _ in range(4):
        deliver_oldest_ready_event(state, now(), False, media_root=tmp_path)

    assert sent == ["text", "one.jpg", "two.jpg"]
    assert state["outbox"] == []


def test_delivery_targets_id_stocks_swing(monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_event()
    channels: list[str] = []
    monkeypatch.setattr(discord, "post_text", lambda _content, channel_id, *_args: channels.append(channel_id))
    monkeypatch.setattr(discord, "submit_board_event", lambda *_: True)

    assert deliver_oldest_ready_event(state_with(event), now(), False) is True

    assert channels == ["1525102458253217803"]


def test_second_image_failure_retries_only_second_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_event(media=[image(tmp_path, "one.jpg"), image(tmp_path, "two.jpg")])
    event["text_index"] = 1
    event["next_media_index"] = 1
    calls: list[str] = []

    def post(path: Path, *args: object) -> None:
        calls.append(path.name)
        if len(calls) == 1:
            raise RuntimeError("temporary")

    monkeypatch.setattr(discord, "post_file", post)
    monkeypatch.setattr(discord, "submit_board_event", lambda *_: True)
    state = state_with(event)
    assert deliver_oldest_ready_event(state, now(), False, media_root=tmp_path) is False
    assert event["text_index"] == 1
    assert event["next_media_index"] == 1
    assert deliver_oldest_ready_event(state, now() + timedelta(seconds=60), False, media_root=tmp_path) is True
    assert event["next_media_index"] == 2
    assert calls == ["two.jpg", "two.jpg"]


def test_dry_run_prints_without_http_or_delivery_state_advance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    event = ready_event(media=[image(tmp_path, "one.jpg")])
    monkeypatch.setattr(discord.requests, "post", lambda *args, **kwargs: pytest.fail("HTTP was called"))

    assert deliver_oldest_ready_event(state_with(event), now(), True, media_root=tmp_path) is False

    assert (event["text_index"], event["next_media_index"]) == (0, 0)
    assert "would post text" in capsys.readouterr().out


def test_text_limit_is_rejected_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discord.requests, "post", lambda *args, **kwargs: pytest.fail("HTTP was called"))
    with pytest.raises(ValueError, match="2,000"):
        post_text("x" * 2001, "123", False, "nonce")


def test_429_uses_retry_after(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_event(media=[image(tmp_path, "one.jpg")])
    monkeypatch.setattr(discord, "post_text", lambda *args: (_ for _ in ()).throw(DiscordRateLimitError(17.5)))

    assert deliver_oldest_ready_event(state_with(event), now(), False, media_root=tmp_path) is False

    assert event["next_attempt_at"] == (now() + timedelta(seconds=17.5)).isoformat()
    assert event["attempts"] == 1


def test_discord_delivery_errors_have_a_safe_category() -> None:
    assert str(DiscordDeliveryError("Discord request failed")) == "Discord request failed"
    assert str(DiscordRateLimitError(17.5)) == "Discord rate limited"


def test_missing_local_image_is_retried_with_sanitized_error(tmp_path: Path) -> None:
    event = ready_event(media=[{"message_id": 101, "ordinal": 0, "path": str(tmp_path / "gone.jpg")}])
    event["text_index"] = 1

    assert deliver_oldest_ready_event(state_with(event), now(), False, media_root=tmp_path) is False

    assert event["next_media_index"] == 0
    assert event["attempts"] == 1
    assert len(str(event["last_error"])) <= 180
    assert event["last_error"] == "captured source media is unavailable"


def test_nonce_is_deterministic_unique_per_leg() -> None:
    assert nonce("101:CTRA", "text:0") == nonce("101:CTRA", "text:0")
    values = {nonce("101:CTRA", leg) for leg in ("text:0", "media:0", "media:1")}
    assert all(len(value) == 24 for value in values)
    assert len(values) == 3


def test_successful_leg_is_persisted_before_a_fresh_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_event()
    state = new_state()
    state["outbox"].append(event)
    state_path = tmp_path / "state.json"
    save_state(state_path, state)
    monkeypatch.setattr(discord, "post_text", lambda *args: None)
    monkeypatch.setattr(discord, "submit_board_event", lambda *_: True)

    assert deliver_oldest_ready_event(state, now(), False, state_path=state_path)
    # A new process sees the completed leg even though no scanner save follows.
    assert load_state(state_path)["outbox"] == []


def test_retry_reuses_the_same_nonce(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_event()
    sent: list[str] = []

    def post(*args: object) -> None:
        sent.append(str(args[-1]))
        if len(sent) == 1:
            raise RuntimeError("temporary server body /secret/token")

    monkeypatch.setattr(discord, "post_text", post)
    monkeypatch.setattr(discord, "submit_board_event", lambda *_: True)
    state = state_with(event)
    assert not deliver_oldest_ready_event(state, now(), False, media_root=tmp_path)
    assert deliver_oldest_ready_event(state, now() + timedelta(seconds=60), False, media_root=tmp_path)
    assert sent == [nonce("101:CTRA", "text:0"), nonce("101:CTRA", "text:0")]
    assert event["last_error"] is None


def test_cursor_past_rendered_text_is_not_removed(tmp_path: Path) -> None:
    event = ready_event()
    event["text_index"] = 99
    state = state_with(event)
    assert not deliver_oldest_ready_event(state, now(), False, media_root=tmp_path)
    assert state["outbox"] == [event]
    assert event["last_error"] == "delivery cursor is invalid"


@pytest.mark.parametrize("retry_after", [0, -1, float("nan"), float("inf"), "not-a-number"])
def test_invalid_429_retry_after_uses_bounded_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retry_after: object) -> None:
    class Response:
        def json(self):
            return {"retry_after": retry_after}

    event = ready_event()
    monkeypatch.setattr(discord, "post_text", lambda *args: (_ for _ in ()).throw(DiscordRateLimitError(discord._retry_after(Response()))))
    assert not deliver_oldest_ready_event(state_with(event), now(), False, media_root=tmp_path)
    assert event["next_attempt_at"] == (now() + timedelta(seconds=60)).isoformat()


def test_no_post_environment_is_resolved_by_delivery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KELAS_INVESTASI_GTW_NO_POST", "1")
    monkeypatch.setattr(discord.requests, "post", lambda *args, **kwargs: pytest.fail("HTTP was called"))
    event = ready_event()
    assert not deliver_oldest_ready_event(state_with(event), now(), media_root=tmp_path)
    assert event["text_index"] == 0


def test_no_post_uses_effective_custom_media_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    media_root = tmp_path / "custom-media"
    media_root.mkdir()
    event = ready_event(media=[image(media_root, "one.jpg")])
    event["text_index"] = 1

    assert not deliver_oldest_ready_event(state_with(event), now(), True, media_root=media_root)

    output = capsys.readouterr().out
    assert str(media_root / "one.jpg") in output
    assert "<missing-source-image>" not in output


def test_rejects_outside_or_nonimage_media_without_leaking_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"\xff\xd8\xffimage")
    event = ready_event(media=[{"message_id": 101, "ordinal": 0, "path": str(outside)}])
    event["text_index"] = 1
    assert not deliver_oldest_ready_event(state_with(event), now(), False, media_root=tmp_path)
    assert event["last_error"] == "captured source media is unavailable"
    assert str(outside) not in str(event["last_error"])
