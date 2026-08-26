from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

from fixtures.messages import analysis, at, header, image
from state import load_state, new_state, observe_messages, save_state


@dataclass
class Decision:
    kind: str
    lease_id: str | None = "lease"


class Client:
    def __init__(self, *, authorized: bool = True, connect_error: Exception | None = None) -> None:
        self.authorized = authorized
        self.connect_error = connect_error
        self.disconnected = False

    async def connect(self) -> None:
        if self.connect_error:
            raise self.connect_error

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def disconnect(self) -> None:
        self.disconnected = True


class Resilience:
    def __init__(self) -> None:
        self.auth = 0
        self.transport = 0
        self.success = 0
        self.released = 0

    def record_auth_required(self, *args: object) -> None:
        self.auth += 1

    def record_transport_failure(self, *args: object) -> None:
        self.transport += 1

    def record_authenticated_success(self, *args: object) -> None:
        self.success += 1

    def record_safe_release(self, *args: object) -> None:
        self.released += 1


def _configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, messages: list[object], *, decision: Decision | None = None, client: Client | None = None) -> tuple[Resilience, Client]:
    import scan

    control = Resilience()
    telegram = client or Client()
    monkeypatch.setenv("KELAS_INVESTASI_GTW_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(scan, "resilience", lambda: control)

    async def acquire(*args: object) -> Decision:
        return decision or Decision("probe")

    monkeypatch.setattr(scan, "acquire_probe_after_active_lease", acquire)
    monkeypatch.setattr(scan, "make_client", lambda: telegram)
    monkeypatch.setattr(scan, "resolve_source", lambda *args: _async(object()))
    monkeypatch.setattr(scan, "fetch_unseen_messages", lambda *args: _async(list(messages)))
    monkeypatch.setattr(scan, "capture_image", lambda *args: _async(Path(tmp_path / "media" / "image.jpg")))
    return control, telegram


async def _async(value: object) -> object:
    return value


def _initialized(path: Path, cursor: int = 100) -> None:
    value = new_state()
    value["cursor"] = cursor
    save_state(path, value)


def test_complete_final_bundle_wakes_only_after_quiet_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    _configure(monkeypatch, tmp_path, [header(101, "CTRA"), analysis(102)])
    _initialized(tmp_path / "state.json")

    assert scan.run(now=at("2026-08-11T09:19:59+07:00"), dry_run=True)["wakeAgent"] is False
    result = scan.run(now=at("2026-08-11T09:20:01+07:00"), dry_run=True)
    assert result["wakeAgent"] is True
    assert load_state(tmp_path / "state.json")["outbox"][0]["agent_lease_until"] == "2026-08-11T09:35:01+07:00"


@pytest.mark.parametrize("kind", ["cooldown", "auth_required"])
def test_shared_clean_skip_does_not_change_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str) -> None:
    import scan

    _configure(monkeypatch, tmp_path, [], decision=Decision(kind, None))
    _initialized(tmp_path / "state.json")
    before = (tmp_path / "state.json").read_bytes()

    assert scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=True) == {"wakeAgent": False}
    assert (tmp_path / "state.json").read_bytes() == before


def test_invalid_summary_keeps_exact_claimed_event_pending(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    _configure(monkeypatch, tmp_path, [])
    value = new_state()
    value["cursor"] = 103
    observe_messages(value, [header(101, "CTRA"), analysis(102), header(103, "BREN")], at("2026-08-11T09:00:00+07:00"))
    # Create a valid durable outbox explicitly because observation starts after the stored cursor.
    value = new_state()
    value["cursor"] = 100
    observe_messages(value, [header(101, "CTRA"), analysis(102), header(103, "BREN")], at("2026-08-11T09:00:00+07:00"))
    event = value["outbox"][0]
    event["agent_phase"] = "claimed"
    event["agent_lease_until"] = "2026-08-11T09:15:00+07:00"
    save_state(tmp_path / "state.json", value)

    with pytest.raises(ValueError):
        scan.submit_analysis_payload({"event_key": "101:CTRA", "title": "CTRA: Thesis", "summary": "invalid"}, dry_run=True, now=at("2026-08-11T09:01:00+07:00"))

    saved = load_state(tmp_path / "state.json")
    assert saved["outbox"][0]["title"] is None
    assert saved["outbox"][0]["agent_phase"] == "claimed"


def test_unavailable_source_attempts_fatal_heartbeat_and_main_returns_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    _, client = _configure(monkeypatch, tmp_path, [])
    posted: list[str] = []
    monkeypatch.setattr(scan, "post_text", lambda content, *_args: posted.append(content))
    monkeypatch.setattr(scan, "resolve_source", lambda *args: _raise_async(RuntimeError("source secret-token unavailable")))

    with pytest.raises(RuntimeError, match="source secret-token unavailable"):
        scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=False)

    assert client.disconnected is True
    assert posted == ["❌ kelas-investasi-gtw, 09:00 WIB, failed: Telegram source is unavailable"]
    monkeypatch.setattr(scan, "run", lambda: (_ for _ in ()).throw(RuntimeError("source unavailable")))
    assert scan.main([]) == 1


def test_heartbeat_uses_a_stable_discord_length_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    import scan

    calls: list[tuple[str, str, bool, str]] = []
    monkeypatch.setattr(scan, "post_text", lambda *args: calls.append(args))
    moment = at("2026-08-11T09:00:00+07:00")

    scan.post_heartbeat("heartbeat", moment, False)

    assert calls == [("heartbeat", "1505162000420835388", False, "3abb1eb66e74807b23239d72")]


async def _raise_async(error: BaseException) -> object:
    raise error


def test_unauthenticated_client_records_shared_auth_and_does_not_write_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    control, client = _configure(monkeypatch, tmp_path, [], client=Client(authorized=False))

    assert scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=True) == {"wakeAgent": False}
    assert (control.auth, control.success, client.disconnected) == (1, 0, True)
    assert not (tmp_path / "state.json").exists()


def test_transport_failure_is_classified_and_does_not_write_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    control, client = _configure(monkeypatch, tmp_path, [], client=Client(connect_error=TimeoutError("session=secret")))
    monkeypatch.setattr(scan, "is_transport_error", lambda error: isinstance(error, TimeoutError))

    assert scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=True) == {"wakeAgent": False}
    assert (control.transport, control.success, client.disconnected) == (1, 0, True)
    assert not (tmp_path / "state.json").exists()


def test_make_client_failure_safely_releases_acquired_probe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    control, _ = _configure(monkeypatch, tmp_path, [])
    monkeypatch.setattr(scan, "make_client", lambda: (_ for _ in ()).throw(RuntimeError("local initialization failed")))

    with pytest.raises(RuntimeError, match="local initialization failed"):
        scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=True)

    assert (control.released, control.success, control.transport, control.auth) == (1, 0, 0, 0)


def test_lock_contention_does_not_create_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan
    from state import run_lock

    _configure(monkeypatch, tmp_path, [])
    with run_lock(tmp_path / "state.json.lock"):
        assert scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=True) == {"wakeAgent": False}


def test_no_eligible_source_has_no_wake_and_no_discord_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    _configure(monkeypatch, tmp_path, [analysis(101, "Promo premium")])

    assert scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=True) == {"wakeAgent": False}


def test_media_capture_failure_is_fatal_and_leaves_event_unpersisted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    _configure(monkeypatch, tmp_path, [header(101, "CTRA"), analysis(102, media=(image(102),)), header(103, "BREN")])
    _initialized(tmp_path / "state.json")
    monkeypatch.setattr(scan, "capture_image", lambda *args: _raise_async(RuntimeError("download failed")))

    with pytest.raises(RuntimeError, match="download failed"):
        scan.run(now=at("2026-08-11T09:00:00+07:00"), dry_run=True)
    assert load_state(tmp_path / "state.json")["outbox"] == []


def test_expired_submission_restores_claim_without_mutation_or_delivery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    _configure(monkeypatch, tmp_path, [])
    value = new_state()
    value["cursor"] = 100
    observe_messages(value, [header(101, "CTRA"), analysis(102), header(103, "BREN")], at("2026-08-11T09:00:00+07:00"))
    event = value["outbox"][0]
    event["agent_phase"] = "claimed"
    event["agent_lease_until"] = "2026-08-11T09:15:00+07:00"
    save_state(tmp_path / "state.json", value)
    monkeypatch.setattr(scan, "deliver_oldest_ready_event", lambda *_args, **_kwargs: pytest.fail("delivery was called"))

    with pytest.raises(ValueError, match="lease has expired"):
        scan.submit_analysis_payload({"event_key": "101:CTRA", "title": "CTRA: Thesis", "summary": "invalid"}, dry_run=False, now=at("2026-08-11T09:15:00.000001+07:00"))

    restored = load_state(tmp_path / "state.json")["outbox"][0]
    assert (restored["agent_phase"], restored["title"], restored["summary"]) == ("ready", None, None)


def test_submission_drains_text_then_two_images_without_reclaim(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    _configure(monkeypatch, tmp_path, [])
    value = new_state()
    value["cursor"] = 100
    observe_messages(value, [header(101, "CTRA"), analysis(102), header(103, "BREN")], at("2026-08-11T09:00:00+07:00"))
    event = value["outbox"][0]
    media_root = tmp_path / "media"
    media_root.mkdir()
    paths = [media_root / "one.jpg", media_root / "two.jpg"]
    for path in paths:
        path.write_bytes(b"\xff\xd8\xffsource")
    event["media"] = [{"message_id": 101, "ordinal": index, "path": str(path)} for index, path in enumerate(paths)]
    event["agent_phase"] = "claimed"
    event["agent_lease_until"] = "2026-08-11T09:15:00+07:00"
    save_state(tmp_path / "state.json", value)
    sent: list[str] = []
    import discord
    monkeypatch.setattr(discord, "post_text", lambda *_args: sent.append("text"))
    monkeypatch.setattr(discord, "post_file", lambda path, *_args: sent.append(Path(path).name))

    result = scan.submit_analysis_payload(json.dumps({"event_key": "101:CTRA", "title": "CTRA: Buy area", "summary": "*(Ringkasan)* Buy area 605 sampai 630."}), dry_run=False, now=at("2026-08-11T09:01:00+07:00"))

    assert result == {"wakeAgent": False, "delivered": 3}
    assert sent == ["text", "one.jpg", "two.jpg"]
    assert load_state(tmp_path / "state.json")["outbox"] == []


def test_restart_reuses_verified_captured_media_without_redownload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scan

    destination = tmp_path / "media"
    destination.mkdir()
    cached = destination / "already.jpg"
    cached.write_bytes(b"\xff\xd8\xffsource")
    event = {"media": [{"message_id": 102, "ordinal": 0, "path": str(cached)}]}
    calls: list[int] = []

    async def capture(*_args: object) -> Path:
        calls.append(1)
        return destination / "unexpected.jpg"

    monkeypatch.setattr(scan, "capture_image", capture)
    import asyncio
    asyncio.run(scan._capture_event_media(object(), object(), event, destination))
    asyncio.run(scan._capture_event_media(object(), object(), event, destination))

    assert calls == []
    assert event["media"] == [{"message_id": 102, "ordinal": 0, "path": str(cached.resolve())}]


def test_heartbeat_and_fatal_formats_are_exact_and_sanitized() -> None:
    import scan

    moment = at("2026-08-11T09:03:00+07:00")
    assert scan.format_heartbeat(moment, scanned=2, pending=1, delivered=0) == "🫀 kelas-investasi-gtw, 09:03 WIB, scanned=2 pending=1 delivered=0"
    assert scan.format_fatal(moment, "token=abc\nvery bad") == "❌ kelas-investasi-gtw, 09:03 WIB, failed: watcher operation failed"
