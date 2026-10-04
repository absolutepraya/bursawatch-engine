from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import config
import discord
import pipeline_owner
from state import load_state


STAMP = datetime(2026, 9, 24, 2, 0, tzinfo=timezone.utc)
PHOTO = b"\xff\xd8\xffkelas-header-photo"
REF = {
    "ref": "00000000-0000-4000-8000-000000000042",
    "sha256": hashlib.sha256(PHOTO).hexdigest(),
    "kind": "image",
    "content_type": "image/jpeg",
    "size_bytes": len(PHOTO),
    "filename": "telegram-101.jpg",
    "durable": True,
}


def work(message_id: int, text: str, *, photo: bool = False, reply: int | None = None, minute: int = 0, previous: int | None = None, bootstrap: int = 100) -> dict:
    envelope = {
        "endpoint_id": "telegram:kelasinvestasiid",
        "publisher_id": "kelas-investasi",
        "platform": "telegram",
        "provider_event_id": str(message_id),
        "published_at": (STAMP + timedelta(minutes=minute)).isoformat(),
        "media_required": photo,
        "media_refs": [REF] if photo else [],
        "payload": {"text": text, "reply_to_message_id": reply, "previous_provider_event_id": previous if previous is not None else message_id - 1,
                    "bootstrap_provider_event_id": bootstrap,
                    **({"media_ref_ids": [REF["ref"]]} if photo else {})},
    }
    identity = json.dumps(["telegram", envelope["endpoint_id"], str(message_id)], separators=(",", ":"))
    event_key = hashlib.sha256(identity.encode()).hexdigest()
    effect = hashlib.sha256(f"{event_key}:1:swing_support".encode()).hexdigest()
    return {"pipeline_id": "swing_support", "capability_id": "swing_support", "event_key": event_key,
            "version": 1, "effect_key": effect, "work_key": effect, "envelope": envelope}


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    path = tmp_path / "kelas-state.json"
    monkeypatch.setenv("KELAS_INVESTASI_GTW_STATE_PATH", str(path))
    loaded = config.LoadedWatchConfig(config.default_watch_config(), 7)
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: loaded)
    return path


class MediaReader:
    def __init__(self, data: bytes = PHOTO):
        self.data = data
        self.reads: list[str] = []

    def download(self, ref: str):
        self.reads.append(ref)
        return SimpleNamespace(data=self.data)


def test_header_photo_bundle_agent_and_golden_all_board(owner, monkeypatch: pytest.MonkeyPatch):
    path = owner
    media = MediaReader()
    header = work(101, "Good to watch - CTRA #GTW", photo=True)
    analysis = work(102, "Akumulasi kuat\nBuy area: 605-630\nTP 1: 655\nStoploss: <573", minute=1)
    later_photo = work(103, "Analisis tambahan", photo=True, minute=2)
    next_header = work(104, "Good to watch - BREN #GTW", minute=3)

    for item in (header, analysis, later_photo, next_header):
        assert pipeline_owner.submit(item, no_post=True, media_store=media) == "accepted"
    assert pipeline_owner.submit(header, no_post=True, media_store=media) == "accepted"
    assert media.reads == [REF["ref"]]
    state = load_state(path)
    event = state["outbox"][0]
    assert event["event_key"] == "101:CTRA"
    assert event["source_message_ids"] == [101, 102, 103]
    assert len(event["media"]) == 1
    assert event["source_published_at"] == STAMP.isoformat()

    sent_text: list[str] = []
    sent_files: list[bytes] = []
    board: list[dict] = []

    def post_text(content, *_args):
        sent_text.append(content)
        return "123456789012345678"

    def post_file(source, *_args):
        sent_files.append(Path(source).read_bytes())
        return "123456789012345679"

    def submit_board(payload, source, no_post):
        board.append({"payload": dict(payload), "media": Path(source).read_bytes(), "no_post": no_post})
        payload["_board_url"] = "https://discord.com/channels/940285152335110204/123456789012345680"
        return True

    monkeypatch.setattr(discord, "post_text", post_text)
    monkeypatch.setattr(discord, "post_file", post_file)
    monkeypatch.setattr(discord, "submit_board_event", submit_board)
    monkeypatch.setattr(discord, "edit_board_links", lambda *_args, **_kwargs: True)
    wake = pipeline_owner.claim_agent(now=STAMP + timedelta(minutes=3), no_post=True)
    assert wake["wakeAgent"] is True
    assert wake["item"]["event_key"] == "101:CTRA"
    assert wake["item"]["plan"] == {"buy_area": "605 sampai 630", "targets": "655", "stoploss": "<573"}
    assert pipeline_owner.claim_agent(now=STAMP + timedelta(minutes=4), no_post=True)["wakeAgent"] is False

    result = pipeline_owner.submit_analysis({"event_key": "101:CTRA", "title": "CTRA: Akumulasi kuat",
                                             "summary": "*(Ringkasan)* Akumulasi kuat pada area 605 sampai 630"},
                                            now=STAMP + timedelta(minutes=5))
    assert result["accepted"] is True
    assert sent_text == [
        "### <:kelasinvestasi:1536570114772574218> CTRA: Akumulasi kuat\n"
        "-# Kelas Investasi GTW\n\n"
        "*(Ringkasan)* Akumulasi kuat pada area 605 sampai 630\n\n"
        "**Buy area:** 605 sampai 630\n**Target:** 655\n**Stoploss:** <573\n\n"
        "**Source status:** Good to watch <:grey:1531279158913536182>\n"
        "**Last updated:** 24 Sep 2026 09:00 WIB\n"
        "**Board:** <#1548273399069933720>\n\n"
        "[View on Telegram](<https://t.me/kelasinvestasiid/101>)"
    ]
    assert sent_files == [PHOTO]
    assert len(board) == 1
    assert board[0]["payload"]["event_key"] == "kelas-investasi:101:CTRA"
    assert board[0]["payload"]["source"] == "kelas-investasi"
    assert board[0]["payload"]["published_at"] == STAMP.isoformat()
    assert board[0]["payload"]["plan"] is None
    assert "**Board:**" not in board[0]["payload"]["all_content"]
    assert board[0]["media"] == PHOTO
    assert load_state(path)["outbox"] == []


def test_media_read_failure_does_not_accept_header_or_advance_owner_cursor(owner):
    with pytest.raises(pipeline_owner.OwnerPending):
        pipeline_owner.submit(work(101, "Good to watch - CTRA #GTW", photo=True), no_post=True,
                              media_store=MediaReader(b"wrong"))
    assert not owner.exists()


def test_quiet_window_and_rejected_agent_output_preserve_retry(owner):
    assert pipeline_owner.submit(work(101, "Good to watch - CTRA #GTW"), no_post=True) == "accepted"
    assert pipeline_owner.claim_agent(now=STAMP + timedelta(minutes=20), no_post=True)["wakeAgent"] is False
    assert pipeline_owner.claim_agent(now=STAMP + timedelta(minutes=20, seconds=1), no_post=True)["wakeAgent"] is True
    with pytest.raises(ValueError):
        pipeline_owner.submit_analysis({"event_key": "101:CTRA", "title": "CTRA: invented", "summary": "bad"},
                                       now=STAMP + timedelta(minutes=21), no_post=True)
    assert load_state(owner)["outbox"][0]["agent_phase"] == "claimed"
    assert load_state(owner)["outbox"][0]["text_index"] == 0


def test_out_of_order_claim_does_not_skip_a_bundle_message(owner):
    later = work(102, "Akumulasi kuat", previous=101, minute=1)
    assert pipeline_owner.submit(work(101, "Good to watch - CTRA #GTW", previous=100), no_post=True) == "accepted"
    with pytest.raises(pipeline_owner.OwnerPending, match="out of order"):
        pipeline_owner.submit(work(103, "Buy area: 605-630", previous=102, minute=2), no_post=True)
    assert load_state(owner)["cursor"] == 101
    assert pipeline_owner.submit(later, no_post=True) == "accepted"
    assert load_state(owner)["cursor"] == 102


def test_later_claim_cannot_initialize_empty_owner_from_its_predecessor(owner):
    later = work(103, "Buy area: 605-630", previous=101, minute=2)
    with pytest.raises(pipeline_owner.OwnerPending, match="first source work arrived out of order"):
        pipeline_owner.submit(later, no_post=True)
    assert not owner.exists()
    first = work(101, "Good to watch - CTRA #GTW", previous=100)
    assert pipeline_owner.submit(first, no_post=True) == "accepted"
    assert pipeline_owner.submit(later, no_post=True) == "accepted"
    state = load_state(owner)
    assert state["cursor"] == 103
    assert state["pending"][0]["source_message_ids"] == [101, 103]


def test_ingress_retry_requires_exact_source_event_and_effect_identity(owner):
    item = work(101, "Good to watch - CTRA #GTW")
    assert pipeline_owner.submit(item, no_post=True) == "accepted"
    for altered in ({**item, "event_key": "bad"}, {**item, "effect_key": "bad"}):
        with pytest.raises(ValueError):
            pipeline_owner.submit(altered, no_post=True)
    assert load_state(owner)["cursor"] == 101


def test_no_post_agent_submission_prints_intent_without_delivery_cursor_change(owner, capsys):
    assert pipeline_owner.submit(work(101, "Good to watch - CTRA #GTW", photo=True), no_post=True,
                                 media_store=MediaReader()) == "accepted"
    assert pipeline_owner.claim_agent(now=STAMP + timedelta(minutes=21), no_post=True)["wakeAgent"] is True
    result = pipeline_owner.submit_analysis({"event_key": "101:CTRA", "title": "CTRA: CTRA",
                                             "summary": "*(Ringkasan)* CTRA"},
                                            now=STAMP + timedelta(minutes=22), no_post=True)
    assert result == {"accepted": True, "event_key": "101:CTRA", "delivered": 0}
    output = capsys.readouterr().out
    assert "would post text channel=1525102458253217803" in output
    assert "would post file channel=1525102458253217803" in output
    event = load_state(owner)["outbox"][0]
    assert event["text_index"] == event["next_media_index"] == 0
    assert event["board_phase"] == "pending"


def test_read_only_agent_status_exposes_one_ready_timestamp(owner):
    assert pipeline_owner.submit(work(101, "Good to watch - CTRA #GTW"), no_post=True) == "accepted"
    before = owner.read_bytes()
    assert pipeline_owner.agent_status(now=STAMP + timedelta(minutes=20), no_post=True) == {
        "ready": False, "pipeline_id": "swing_support"}
    assert pipeline_owner.agent_status(now=STAMP + timedelta(minutes=21), no_post=True) == {
        "ready": True, "pipeline_id": "swing_support", "event_key": "101:CTRA",
        "published_at": STAMP.isoformat()}
    assert owner.read_bytes() == before


def test_pipeline_accepts_version_two_pwon_without_primary_promotion(owner,monkeypatch):
    from test_agent_protocol import pwon_payload
    for item in (work(101,"Good to watch - PWON #GTW"),work(102,"Watch on 270–282\nSupport utama 260\nTarget 1 288\nTarget 2 298",minute=1),work(103,"Good to watch - BREN #GTW",minute=2)):
        pipeline_owner.submit(item,no_post=True)
    wake = pipeline_owner.claim_agent(now=STAMP+timedelta(minutes=3),no_post=True)
    payload = pwon_payload(wake["item"]["source_text"]);payload["event_key"] = wake["item"]["event_key"]
    texts=[];board=[]
    monkeypatch.setattr(discord,"post_text",lambda content,*args:texts.append(content) or "123456789012345678")
    monkeypatch.setattr(discord,"submit_board_event",lambda payload,*args:board.append(payload.copy()) or True)
    result = pipeline_owner.submit_analysis(payload,now=STAMP+timedelta(minutes=4))
    assert result["accepted"] and "**Stop-loss:** <260" in texts[0]
    assert board[0]["plan"] is None and board[0]["source"] == "kelas-investasi"
