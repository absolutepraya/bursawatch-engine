from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from telegram_resilience import PolyCopResilience, ProbeDecision, StateBlockedError


WIB_NOW = datetime.fromisoformat("2026-08-10T15:00:00+07:00")


def _resilience(tmp_path: Path) -> PolyCopResilience:
    return PolyCopResilience.for_paths(tmp_path / "state.json", tmp_path / "events.jsonl")


def _state(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))


def test_from_defaults_accepts_explicit_isolated_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("BURSAWATCH_RELEASE_NO_POST", raising=False)
    monkeypatch.delenv("BURSAWATCH_RELEASE_NO_POST_TEMP", raising=False)
    state_path = tmp_path / "isolated-state.json"
    log_path = tmp_path / "isolated-events.jsonl"
    monkeypatch.setenv("POLYCOP_RESILIENCE_STATE_PATH", str(state_path))
    monkeypatch.setenv("POLYCOP_RESILIENCE_LOG_PATH", str(log_path))

    resilience = PolyCopResilience.from_defaults()

    assert resilience.state_path == state_path
    assert resilience.log_path == log_path


def test_release_no_post_defaults_to_its_temporary_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BURSAWATCH_RELEASE_NO_POST", "1")
    monkeypatch.setenv("BURSAWATCH_RELEASE_NO_POST_TEMP", str(tmp_path))
    monkeypatch.setenv("POLYCOP_RESILIENCE_STATE_PATH", "/production/state.json")
    monkeypatch.setenv("POLYCOP_RESILIENCE_LOG_PATH", "/production/events.jsonl")

    resilience = PolyCopResilience.from_defaults()

    assert resilience.state_path == tmp_path / "telegram-resilience.json"
    assert resilience.log_path == tmp_path / "telegram-resilience.jsonl"


def test_release_no_post_requires_a_temporary_root(monkeypatch) -> None:
    monkeypatch.setenv("BURSAWATCH_RELEASE_NO_POST", "1")
    monkeypatch.delenv("BURSAWATCH_RELEASE_NO_POST_TEMP", raising=False)

    with pytest.raises(StateBlockedError, match="release no-post resilience paths are unavailable"):
        PolyCopResilience.from_defaults()


def test_new_state_is_private_and_versioned(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)

    decision = resilience.acquire_probe("idx-swing-watch-phintraco-daily", WIB_NOW)

    state = _state(tmp_path)
    assert decision.kind == "probe"
    assert state["version"] == 1
    assert state["circuit"]["status"] == "probing"
    assert oct((tmp_path / "state.json").stat().st_mode & 0o777) == "0o600"
    assert "SESSION" not in json.dumps(state).upper()
    assert "TOKEN" not in json.dumps(state).upper()


def test_only_one_of_three_watchers_gets_a_probe(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)

    owner = resilience.acquire_probe("idx-market-news-watch", WIB_NOW)
    later = [
        resilience.acquire_probe(name, WIB_NOW).kind
        for name in (
            "idx-swing-watch-phintraco-daily",
            "polymarket-signal-watch",
        )
    ]

    assert owner.kind == "probe"
    assert later == ["leased", "leased"]


def test_transport_failure_opens_one_incident_and_marks_cooldown_watchers(
    tmp_path: Path,
) -> None:
    resilience = _resilience(tmp_path)
    owner = resilience.acquire_probe("idx-market-news-watch", WIB_NOW)

    resilience.record_transport_failure(
        owner.lease_id, "idx-market-news-watch", TimeoutError("secret"), WIB_NOW
    )
    skipped = resilience.acquire_probe(
        "idx-swing-watch-phintraco-daily", WIB_NOW
    )

    state = _state(tmp_path)
    assert skipped.kind == "cooldown"
    assert state["circuit"]["status"] == "transport_open"
    assert state["incident"]["affected_watchers"] == [
        "idx-market-news-watch",
        "idx-swing-watch-phintraco-daily",
    ]
    assert state["incident"]["last_error"] == "TimeoutError"


def test_transport_backoff_starts_in_60_to_75_second_window(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)
    owner = resilience.acquire_probe("idx-market-news-watch", WIB_NOW)

    resilience.record_transport_failure(
        owner.lease_id, "idx-market-news-watch", TimeoutError(), WIB_NOW
    )

    retry_at = datetime.fromisoformat(_state(tmp_path)["circuit"]["next_probe_at"])
    assert timedelta(seconds=60) <= retry_at - WIB_NOW <= timedelta(seconds=75)


def test_transport_backoff_doubles_and_caps_at_fifteen_minutes(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)
    now = WIB_NOW
    delays: list[int] = []

    for _ in range(6):
        owner = resilience.acquire_probe("idx-market-news-watch", now)
        assert owner.kind == "probe"
        resilience.record_transport_failure(
            owner.lease_id, "idx-market-news-watch", TimeoutError(), now
        )
        retry_at = datetime.fromisoformat(
            _state(tmp_path)["circuit"]["next_probe_at"]
        )
        delays.append(int((retry_at - now).total_seconds()))
        now = retry_at

    assert 120 <= delays[1] <= 135
    assert delays[-1] == 900


def test_expired_probe_lease_can_be_reclaimed(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)
    resilience.acquire_probe("idx-market-news-watch", WIB_NOW)

    later = resilience.acquire_probe(
        "idx-swing-watch-phintraco-daily", WIB_NOW + timedelta(seconds=75)
    )

    assert later.kind == "probe"


def test_unauthorized_session_never_auto_retries(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)
    owner = resilience.acquire_probe("polymarket-signal-watch", WIB_NOW)

    resilience.record_auth_required(
        owner.lease_id, "polymarket-signal-watch", WIB_NOW
    )
    later = resilience.acquire_probe(
        "idx-swing-watch-phintraco-daily", WIB_NOW + timedelta(days=1)
    )

    assert later.kind == "auth_required"
    assert _state(tmp_path)["circuit"]["next_probe_at"] is None


def test_waiting_for_a_healthy_active_probe_allows_the_next_watcher_to_run() -> None:
    from telegram_resilience import acquire_probe_after_active_lease

    class FakeResilience:
        def __init__(self) -> None:
            self.decisions = iter(
                (
                    ProbeDecision("leased", None, None, WIB_NOW + timedelta(seconds=75)),
                    ProbeDecision("probe", "lease-2", None, None),
                )
            )

        def acquire_probe(self, watcher: str, now: datetime) -> ProbeDecision:
            assert watcher == "idx-market-news-watch"
            assert now == WIB_NOW
            return next(self.decisions)

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    decision = asyncio.run(
        acquire_probe_after_active_lease(
            FakeResilience(),
            "idx-market-news-watch",
            WIB_NOW,
            sleep=fake_sleep,
        )
    )

    assert decision.kind == "probe"
    assert sleeps == [0.25]


def test_waiting_for_an_active_probe_stops_when_it_opens_cooldown() -> None:
    from telegram_resilience import acquire_probe_after_active_lease

    class FakeResilience:
        def __init__(self) -> None:
            self.decisions = iter(
                (
                    ProbeDecision("leased", None, None, WIB_NOW + timedelta(seconds=75)),
                    ProbeDecision("cooldown", None, "incident", WIB_NOW + timedelta(minutes=1)),
                )
            )

        def acquire_probe(self, _watcher: str, _now: datetime) -> ProbeDecision:
            return next(self.decisions)

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    decision = asyncio.run(
        acquire_probe_after_active_lease(
            FakeResilience(), "idx-market-news-watch", WIB_NOW, sleep=fake_sleep
        )
    )

    assert decision.kind == "cooldown"
    assert sleeps == [0.25]


def test_invalid_state_is_preserved_and_blocks_probes(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"version": 999}', encoding="utf-8")

    decision = PolyCopResilience.for_paths(
        state_path, tmp_path / "events.jsonl"
    ).acquire_probe("idx-market-news-watch", WIB_NOW)

    assert decision.kind == "state_blocked"
    assert state_path.read_text(encoding="utf-8") == '{"version": 999}'


def test_naive_times_are_rejected(tmp_path: Path) -> None:
    resilience = _resilience(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        resilience.acquire_probe("idx-market-news-watch", datetime(2026, 8, 10))


def _open_transport_incident(tmp_path: Path) -> PolyCopResilience:
    resilience = _resilience(tmp_path)
    owner = resilience.acquire_probe("idx-market-news-watch", WIB_NOW)
    resilience.record_transport_failure(
        owner.lease_id, "idx-market-news-watch", TimeoutError(), WIB_NOW
    )
    return resilience


def test_failed_notification_claim_retries_with_same_event_key(tmp_path: Path) -> None:
    resilience = _open_transport_incident(tmp_path)

    first = resilience.claim_notification("idx-swing-watch-phintraco-daily", WIB_NOW)
    assert first is not None
    assert first.event_key == f"{first.incident_id}:transport_outage"
    assert resilience.claim_notification("idx-market-news-watch", WIB_NOW) is None

    retry = resilience.claim_notification(
        "idx-market-news-watch", WIB_NOW + timedelta(seconds=76)
    )
    assert retry is not None
    assert retry.event_key == first.event_key


def test_acknowledged_notification_is_never_claimed_again(tmp_path: Path) -> None:
    resilience = _open_transport_incident(tmp_path)
    notice = resilience.claim_notification("polymarket-signal-watch", WIB_NOW)
    assert notice is not None

    resilience.acknowledge_notification(notice.claim_id, WIB_NOW)

    assert resilience.claim_notification(
        "idx-market-news-watch", WIB_NOW + timedelta(seconds=76)
    ) is None


def test_authenticated_recovery_queues_one_recovery_notice(tmp_path: Path) -> None:
    resilience = _open_transport_incident(tmp_path)
    outage = resilience.claim_notification("idx-market-news-watch", WIB_NOW)
    assert outage is not None
    resilience.acknowledge_notification(outage.claim_id, WIB_NOW)
    retry_at = datetime.fromisoformat(_state(tmp_path)["circuit"]["next_probe_at"])
    owner = resilience.acquire_probe("idx-swing-watch-phintraco-daily", retry_at)

    resilience.record_authenticated_success(
        owner.lease_id,
        "idx-swing-watch-phintraco-daily",
        retry_at,
        2,
        "149.154.167.51:443?session=must-not-be-logged",
    )

    recovery = resilience.claim_notification(
        "idx-swing-watch-phintraco-daily", retry_at
    )
    assert recovery is not None
    assert recovery.kind == "recovery"
    assert "recovered after" in recovery.content
    assert "must-not-be-logged" not in json.dumps(_state(tmp_path))


def _probe_module():
    path = Path(__file__).resolve().parents[1] / "bin" / "telegram-resilience-probe.py"
    spec = spec_from_file_location("telegram_resilience_probe", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_only_connects_authenticates_gets_me_and_disconnects(
    tmp_path: Path,
) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.session = type("Session", (), {"dc_id": 2})()

        async def connect(self) -> None:
            self.calls.append("connect")

        async def is_user_authorized(self) -> bool:
            self.calls.append("is_user_authorized")
            return True

        async def get_me(self):
            self.calls.append("get_me")
            return type("Me", (), {"id": 5274241637})()

        async def disconnect(self) -> None:
            self.calls.append("disconnect")

        async def get_entity(self, *_):
            pytest.fail("probe must not read a Telegram entity")

        async def send_message(self, *_):
            pytest.fail("probe must not send Telegram messages")

    client = FakeClient()
    probe = _probe_module()
    result = asyncio.run(
        probe.run_probe(
            client,
            PolyCopResilience.for_paths(
                tmp_path / "state.json", tmp_path / "events.jsonl"
            ),
            WIB_NOW,
        )
    )

    assert result == {"connected": True, "authorized": True, "dc_id": 2}
    assert client.calls == ["connect", "is_user_authorized", "get_me", "disconnect"]


def test_log_redacts_exception_text_and_omits_expired_records(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "at": "2026-07-01T15:00:00+07:00",
                "event": "old",
                "secret": "must disappear",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    resilience = PolyCopResilience.for_paths(tmp_path / "state.json", log_path)
    owner = resilience.acquire_probe("idx-market-news-watch", WIB_NOW)

    resilience.record_transport_failure(
        owner.lease_id,
        "idx-market-news-watch",
        TimeoutError("POLYCOP_SESSION_STRING=must-not-be-logged"),
        WIB_NOW,
    )

    contents = log_path.read_text(encoding="utf-8")
    assert "must-not-be-logged" not in contents
    assert "must disappear" not in contents
    assert "TimeoutError" in contents
