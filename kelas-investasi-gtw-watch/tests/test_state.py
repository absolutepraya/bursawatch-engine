from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from fixtures.messages import analysis, at, header, image, reply
from state import (
    CorruptStateError,
    claim_oldest_agent,
    load_state,
    new_state,
    observe_messages,
    ready_events,
    run_lock,
    save_state,
)


def initialized_state(cursor: int = 100) -> dict[str, object]:
    value = new_state()
    value["cursor"] = cursor
    return value


def test_first_observation_only_initializes_cursor() -> None:
    value = new_state()

    observe_messages(value, [header(100, "CTRA")], at("2026-08-11T09:00:00+07:00"))

    assert value["cursor"] == 100
    assert value["pending"] == []
    assert value["outbox"] == []


def test_final_bundle_is_ready_only_after_twenty_quiet_minutes() -> None:
    value = initialized_state()
    observe_messages(
        value,
        [header(101, "CTRA"), analysis(102)],
        at("2026-08-11T09:00:00+07:00"),
    )

    assert ready_events(value, at("2026-08-11T09:20:00+07:00")) == []
    assert [event["ticker"] for event in ready_events(value, at("2026-08-11T09:20:01+07:00"))] == ["CTRA"]


@pytest.mark.parametrize("gap", ["2026-08-11T09:00:00+07:00", "2026-08-11T09:00:17+07:00"])
def test_analysis_within_quiet_window_stays_in_its_header_bundle(gap: str) -> None:
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), analysis(102, posted_at=gap)], at(gap))

    event = ready_events(value, at("2026-08-11T09:20:18+07:00"))[0]

    assert event["source_message_ids"] == [101, 102]
    assert event["plan"] == {"buy_area": "605 sampai 630", "targets": "655", "stoploss": "<573"}


def test_only_header_image_is_kept_when_analysis_messages_include_media() -> None:
    value = initialized_state()
    observe_messages(
        value,
        [
            header(101, "CTRA", media=(image(101),)),
            analysis(102, media=(image(102),)),
            analysis(103, text="Katalis lanjutan", media=(image(103),)),
        ],
        at("2026-08-11T09:00:00+07:00"),
    )

    event = ready_events(value, at("2026-08-11T09:20:01+07:00"))[0]

    assert event["media"] == [{"message_id": 101, "ordinal": 0}]


def test_next_gtw_header_makes_prior_bundle_ready_immediately() -> None:
    value = initialized_state()
    observe_messages(
        value,
        [header(101, "CTRA"), analysis(102), header(103, "BREN", "2026-08-11T09:00:17+07:00")],
        at("2026-08-11T09:00:17+07:00"),
    )

    events = ready_events(value, at("2026-08-11T09:00:17+07:00"))

    assert [event["ticker"] for event in events] == ["CTRA"]
    assert value["pending"][0]["ticker"] == "BREN"


def test_same_timestamp_headers_preserve_message_sequence() -> None:
    value = initialized_state()
    moment = "2026-08-11T09:00:00+07:00"
    observe_messages(value, [header(102, "FORE", moment), header(101, "RATU", moment)], at(moment))

    assert [event["ticker"] for event in ready_events(value, at(moment))] == ["RATU"]
    assert value["pending"][0]["ticker"] == "FORE"


def test_late_replies_do_not_change_a_header_closed_bundle() -> None:
    value = initialized_state()
    observe_messages(value, [header(101, "RAJA"), analysis(102), header(103, "BREN")], at("2026-08-11T09:00:00+07:00"))

    observe_messages(
        value,
        [reply(201, "Disclaimer", 101), reply(202, "Baca selengkapnya https://example.test", 101)],
        at("2026-08-11T10:00:00+07:00"),
    )

    assert value["outbox"][0]["source_message_ids"] == [101, 102]
    assert value["outbox"][0]["source_text"] == "Good to watch - RAJA #GTW\nBuy area: 605-630\nTP 1: 655\nStoploss: <573"


def test_reply_with_gtw_header_never_opens_or_closes_a_bundle() -> None:
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), analysis(102)], at("2026-08-11T09:00:00+07:00"))

    observe_messages(value, [reply(103, "Good to watch - BREN #GTW", 101)], at("2026-08-11T09:00:17+07:00"))

    assert value["outbox"] == []
    assert value["pending"][0]["ticker"] == "CTRA"
    assert value["pending"][0]["source_message_ids"] == [101, 102]


@pytest.mark.parametrize(
    "text",
    [
        "Disclaimer: bukan rekomendasi investasi",
        "Promo premium, gabung kelas kami sekarang",
        "Baca selengkapnya https://example.test/article",
        "Selamat pagi semuanya, jangan lupa webinar malam ini",
    ],
)
def test_in_window_non_reply_non_analysis_is_excluded(text: str) -> None:
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), analysis(102), analysis(103, text)], at("2026-08-11T09:00:17+07:00"))

    event = ready_events(value, at("2026-08-11T09:20:18+07:00"))[0]

    assert event["source_message_ids"] == [101, 102]


def test_image_only_continuation_is_not_forwarded() -> None:
    value = initialized_state()
    observe_messages(
        value,
        [header(101, "CTRA"), analysis(102, "", media=(image(102, 0), image(102, 1)))],
        at("2026-08-11T09:00:00+07:00"),
    )

    event = ready_events(value, at("2026-08-11T09:20:01+07:00"))[0]

    assert event["source_message_ids"] == [101, 102]
    assert event["media"] == []


def test_replayed_messages_are_not_duplicated() -> None:
    value = initialized_state()
    messages = [header(101, "CTRA"), analysis(102)]
    observe_messages(value, messages, at("2026-08-11T09:00:00+07:00"))
    observe_messages(value, messages, at("2026-08-11T09:00:00+07:00"))

    event = ready_events(value, at("2026-08-11T09:20:01+07:00"))[0]

    assert value["cursor"] == 102
    assert event["source_message_ids"] == [101, 102]


def test_state_round_trip_is_private_and_json_serializable(tmp_path: Path) -> None:
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA")], at("2026-08-11T09:00:00+07:00"))
    path = tmp_path / "state.json"

    save_state(path, value)

    assert load_state(path) == value
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_version_one_state_migrates_without_resetting_cursor(tmp_path: Path) -> None:
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), header(102, "BREN")], at("2026-08-11T09:00:00+07:00"))
    value["version"] = 1
    for field in ("source_published_at", "board_phase", "board_attempts", "board_next_attempt_at", "board_last_error"):
        del value["outbox"][0][field]
    path = tmp_path / "state.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    migrated = load_state(path)

    assert migrated["version"] == 3
    assert migrated["cursor"] == 102
    event = migrated["outbox"][0]
    assert event["source_published_at"] is None
    assert event["board_phase"] == "unavailable"
    assert event["board_attempts"] == 0
    assert event["board_next_attempt_at"] is None
    assert event["board_last_error"] is None
    assert event["text_message_ids"] == []


@pytest.mark.parametrize("close_by_header", [False, True])
def test_migrated_pending_bundle_stays_valid_when_closed(tmp_path, close_by_header):
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA")], at("2026-08-11T09:00:00+07:00"))
    value["version"] = 1
    del value["pending"][0]["source_published_at"]
    path = tmp_path / "state.json"
    save_state(path, value)
    migrated = load_state(path)
    observe_messages(migrated, [header(102, "BREN")] if close_by_header else [], at("2026-08-11T09:21:00+07:00"))
    ready_events(migrated, at("2026-08-11T09:21:00+07:00"))
    save_state(path, migrated)
    event = load_state(path)["outbox"][0]
    assert event["source_published_at"] is None
    assert event["board_phase"] == "unavailable"
    assert event["board_attempts"] == 0


def test_corrupt_state_is_quarantined_and_never_reinitialized(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(CorruptStateError):
        load_state(path)

    assert not path.exists()
    assert len(list(tmp_path.glob("state.corrupt-*.json"))) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.__setitem__("cursor", "101"),
        lambda value: value.__setitem__("pending", [{"ticker": "CTRA"}]),
        lambda value: value["outbox"].append({"event_key": "bad"}),
        lambda value: value["stats"].__setitem__("observed", True),
    ],
)
def test_json_shaped_but_invalid_state_is_quarantined(tmp_path: Path, mutate) -> None:
    path = tmp_path / "state.json"
    value = new_state()
    mutate(value)
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(CorruptStateError):
        load_state(path)

    assert not path.exists()
    assert len(list(tmp_path.glob("state.corrupt-*.json"))) == 1


def test_corrupt_state_quarantine_names_do_not_collide(tmp_path: Path, monkeypatch) -> None:
    import state

    path = tmp_path / "state.json"
    fixed_now = state.datetime.now(state.timezone.utc)

    class FrozenDateTime:
        @classmethod
        def now(cls, tz):
            return fixed_now

    monkeypatch.setattr(state, "datetime", FrozenDateTime)
    for content in ("bad one", "bad two"):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(CorruptStateError):
            load_state(path)

    quarantined = sorted(tmp_path.glob("state.corrupt-*.json"))
    assert len(quarantined) == 2
    assert {item.read_text(encoding="utf-8") for item in quarantined} == {"bad one", "bad two"}


def test_corrupt_state_quarantine_reserves_a_collision_free_name_atomically(tmp_path: Path, monkeypatch) -> None:
    import state

    path = tmp_path / "state.json"
    fixed_now = state.datetime.now(state.timezone.utc)

    class FrozenDateTime:
        @classmethod
        def now(cls, tz):
            return fixed_now

    monkeypatch.setattr(state, "datetime", FrozenDateTime)
    first_name = f"state.corrupt-{fixed_now.strftime('%Y%m%dT%H%M%S.%fZ')}-{state.os.getpid()}.json"
    first_quarantine = tmp_path / first_name
    first_quarantine.write_text("already quarantined", encoding="utf-8")
    path.write_text("new corruption", encoding="utf-8")

    original_link = state.os.link
    link_destinations = []

    def reserve_without_replacement(source, destination):
        link_destinations.append(Path(destination))
        return original_link(source, destination)

    monkeypatch.setattr(state.os, "link", reserve_without_replacement)
    with pytest.raises(CorruptStateError):
        load_state(path)

    second_quarantine = tmp_path / f"{first_quarantine.stem}-1.json"
    assert link_destinations == [first_quarantine, second_quarantine]
    assert first_quarantine.read_text(encoding="utf-8") == "already quarantined"
    assert second_quarantine.read_text(encoding="utf-8") == "new corruption"
    assert not path.exists()


def test_nonblocking_run_lock_rejects_contention(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"

    with run_lock(path):
        with pytest.raises(RuntimeError, match="already running"):
            with run_lock(path):
                pass


def test_claim_oldest_agent_leases_only_once_until_expired() -> None:
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), header(102, "BREN")], at("2026-08-11T09:00:00+07:00"))
    event = ready_events(value, at("2026-08-11T09:00:00+07:00"))[0]

    assert claim_oldest_agent(value, at("2026-08-11T09:00:00+07:00")) is event
    assert claim_oldest_agent(value, at("2026-08-11T09:01:00+07:00")) is None
    assert claim_oldest_agent(value, at("2026-08-11T09:15:00+07:00")) is event


@pytest.mark.parametrize(
    "mutate",
    [
        lambda event: event.__setitem__("event_key", "wrong-key"),
        lambda event: event.__setitem__("media", [{"message_id": 999, "ordinal": 0}]),
        lambda event: event.__setitem__("media", [{"message_id": 101, "ordinal": 0}, {"message_id": 101, "ordinal": 0}]),
        lambda event: event.__setitem__("next_media_index", 1),
        lambda event: event.update({"agent_phase": "ready", "agent_lease_until": "2026-08-11T09:05:00+07:00"}),
        lambda event: event.update({"agent_phase": "claimed", "agent_lease_until": None}),
        lambda event: event.update({"agent_phase": "claimed", "agent_lease_until": "2026-08-11T09:05:00"}),
    ],
)
def test_invalid_outbox_invariants_are_quarantined(tmp_path: Path, mutate) -> None:
    path = tmp_path / "state.json"
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), header(102, "BREN")], at("2026-08-11T09:00:00+07:00"))
    mutate(value["outbox"][0])
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(CorruptStateError):
        load_state(path)

    assert not path.exists()
    assert len(list(tmp_path.glob("state.corrupt-*.json"))) == 1


def test_claimed_outbox_event_with_an_aware_lease_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), header(102, "BREN")], at("2026-08-11T09:00:00+07:00"))
    event = value["outbox"][0]
    event["agent_phase"] = "claimed"
    event["agent_lease_until"] = "2026-08-11T09:05:00+07:00"

    save_state(path, value)

    assert load_state(path) == value


@pytest.mark.parametrize("relative,content", [("../outside.jpg", b"\xff\xd8\xffimage"), ("media/not-image.jpg", b"not an image")])
def test_persisted_media_must_be_captured_image_under_state_media_root(tmp_path: Path, relative: str, content: bytes) -> None:
    path = tmp_path / "state.json"
    value = initialized_state()
    observe_messages(value, [header(101, "CTRA"), header(102, "BREN")], at("2026-08-11T09:00:00+07:00"))
    candidate = (tmp_path / relative).resolve()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(content)
    value["outbox"][0]["media"] = [{"message_id": 101, "ordinal": 0, "path": str(candidate)}]
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(CorruptStateError):
        load_state(path)
    assert len(list(tmp_path.glob("state.corrupt-*.json"))) == 1
