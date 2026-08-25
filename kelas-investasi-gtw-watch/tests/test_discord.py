from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

import discord
from discord import DiscordRateLimitError, deliver_oldest_ready_event, nonce, post_text
from state import load_state, new_state, save_state


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
    }


def state_with(event: dict[str, object]) -> dict[str, object]:
    return {"outbox": [event]}


def test_delivery_sends_text_then_images_in_source_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    event = ready_event(media=[image(tmp_path, "one.jpg"), image(tmp_path, "two.jpg")])
    sent: list[str] = []
    monkeypatch.setattr(discord, "post_text", lambda *args: sent.append("text"))
    monkeypatch.setattr(discord, "post_file", lambda path, *args: sent.append(Path(path).name))
    state = state_with(event)

    for _ in range(4):
        deliver_oldest_ready_event(state, now(), False, media_root=tmp_path)

    assert sent == ["text", "one.jpg", "two.jpg"]
    assert state["outbox"] == []


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


def test_rejects_outside_or_nonimage_media_without_leaking_path(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"\xff\xd8\xffimage")
    event = ready_event(media=[{"message_id": 101, "ordinal": 0, "path": str(outside)}])
    event["text_index"] = 1
    assert not deliver_oldest_ready_event(state_with(event), now(), False, media_root=tmp_path)
    assert event["last_error"] == "captured source media is unavailable"
    assert str(outside) not in str(event["last_error"])
