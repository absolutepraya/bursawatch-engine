from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib-bursawatch-control" / "bin"))
sys.path.insert(0, str(ROOT / "cron-tg-source-ingest" / "bin"))
from adapter import IntakeBlocked, endpoints, ingest_endpoint
from runner import PIPELINE_OWNERS, run_once


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
ENDPOINT = {"endpoint_id": "telegram:phintraprofits", "publisher_id": "phintraco", "address": "phintraprofits", "provider_id": "1444713822", "capabilities": {"trading_plans"}}


class FakeInbox:
    def __init__(self):
        self.accepted = []
        self.fail = False

    def accept(self, envelope):
        if self.fail:
            raise OSError("inbox unavailable")
        self.accepted.append(envelope)
        identity = [envelope[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        key = hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        return {"event_key": key, "version": 1, "duplicate": False, "work_keys": []}


class FakeTelegram:
    def __init__(self, messages, *, address="phintraprofits", entity_id=1444713822):
        self.messages = messages
        self.address = address
        self.entity_id = entity_id

    async def get_entity(self, address):
        assert address == self.address
        return SimpleNamespace(id=self.entity_id, username=self.address)

    async def get_messages(self, entity, limit):
        assert limit == 1
        return [self.messages[-1]] if self.messages else []

    async def iter_messages(self, entity, *, min_id, reverse, limit):
        assert reverse and limit <= 20
        for message in self.messages:
            if message.id > min_id:
                yield message

    async def download_media(self, message, *, file, progress_callback=None):
        data = b"\xff\xd8\xfftelegram-chart"
        Path(file).write_bytes(data)
        if progress_callback:
            progress_callback(len(data), len(data))
        return file


class FakeMediaStore:
    def __init__(self):
        self.uploads = []

    def upload(self, identity, data, *, kind, content_type, filename):
        ref = {"ref": "00000000-0000-4000-8000-000000000011", "sha256": hashlib.sha256(data).hexdigest(), "kind": kind, "content_type": content_type, "size_bytes": len(data), "filename": filename, "durable": True}
        self.uploads.append((identity, data, ref))
        return ref


def message(mid, text="BUY", *, media=None):
    return SimpleNamespace(id=mid, raw_text=text, message=text, date=NOW, media=media, photo=media, reply_to_msg_id=None)


def test_future_only_cursor_and_ack_order(tmp_path):
    asyncio.run(_future_only_cursor_and_ack_order(tmp_path))


async def _future_only_cursor_and_ack_order(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    first = await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    assert first == {"endpoint_id": ENDPOINT["endpoint_id"], "bootstrapped": True, "cursor": 10, "accepted": 0}
    client.messages.append(message(11))
    inbox.fail = True
    with pytest.raises(OSError):
        await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 10
    inbox.fail = False
    result = await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    assert result["cursor"] == 11
    assert [item["provider_event_id"] for item in inbox.accepted] == ["11"]
    assert inbox.accepted[0]["published_at"] == NOW.isoformat()


def test_media_keeps_cursor_at_previous_ack(tmp_path):
    asyncio.run(_media_keeps_cursor_at_previous_ack(tmp_path))


async def _media_keeps_cursor_at_previous_ack(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    client.messages.extend((message(11), message(12, media=object()), message(13)))
    with pytest.raises(IntakeBlocked, match="Source Media Owner"):
        await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 11
    blocked = json.loads((cursor.parent / "blocked-media.json").read_text())
    assert blocked["message_id"] == 12
    assert [item["provider_event_id"] for item in inbox.accepted] == ["11"]


def test_durable_media_upload_precedes_source_acceptance_and_retry_reuses_handoff(tmp_path):
    asyncio.run(_durable_media_upload_precedes_source_acceptance_and_retry_reuses_handoff(tmp_path))


async def _durable_media_upload_precedes_source_acceptance_and_retry_reuses_handoff(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    media_store = FakeMediaStore()
    await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    media_message = message(11, "chart plan", media=object())
    client.messages.append(media_message)
    inbox.fail = True
    with pytest.raises(OSError, match="inbox unavailable"):
        await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW, media_store=media_store)
    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 10
    assert len(media_store.uploads) == 1
    inbox.fail = False
    result = await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW, media_store=media_store)
    assert result["cursor"] == 11
    assert len(media_store.uploads) == 1
    accepted = inbox.accepted[0]
    assert accepted["media_required"] is True
    assert accepted["media_refs"] == [media_store.uploads[0][2]]
    assert accepted["payload"]["media_ref_ids"] == [media_store.uploads[0][2]["ref"]]
    assert not (cursor.parent / "blocked-media.json").exists()


def test_oversized_telegram_media_stops_during_download_before_upload(tmp_path):
    asyncio.run(_oversized_telegram_media_stops_during_download_before_upload(tmp_path))


async def _oversized_telegram_media_stops_during_download_before_upload(tmp_path):
    inbox = FakeInbox()
    client = FakeTelegram([message(10)])
    await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)

    class OversizedTelegram(FakeTelegram):
        async def download_media(self, message, *, file, progress_callback=None):
            Path(file).write_bytes(b"partial")
            assert progress_callback is not None
            progress_callback(8 * 1024 * 1024 + 1, 8 * 1024 * 1024 + 1)
            raise AssertionError("oversized transfer was not stopped")

    oversized = OversizedTelegram([message(11, "chart", media=object())])
    media_store = FakeMediaStore()
    with pytest.raises(IntakeBlocked, match="exceeds the 8 MiB"):
        await ingest_endpoint(oversized, ENDPOINT, tmp_path, inbox, NOW, media_store=media_store)

    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 10
    assert media_store.uploads == []
    assert json.loads((cursor.parent / "blocked-media.json").read_text())["message_id"] == 11


def test_effective_catalog_rejects_unknown_enabled_endpoint():
    row = {"platform": "telegram", "enabled": True, "endpoint_id": "telegram:phintraprofits", "capability_id": "trading_plans", "verification_status": "verified", "provider_id": "1444713822", "publisher_id": "phintraco", "address": "phintraprofits"}
    assert endpoints({"subscriptions": [row]})["telegram:phintraprofits"]["capabilities"] == {"trading_plans"}
    with pytest.raises(IntakeBlocked, match="not onboarded"):
        endpoints({"subscriptions": [{**row, "endpoint_id": "telegram:unknown"}]})
    with pytest.raises(IntakeBlocked, match="identity is not verified"):
        endpoints({"subscriptions": [{**row, "publisher_id": "kelas-investasi"}]})
    with pytest.raises(IntakeBlocked, match="identity is not verified"):
        endpoints({"subscriptions": [{**row, "endpoint_id": "telegram:tuntunsekuritas", "address": "tuntunsekuritas", "capability_id": "company_news", "provider_id": None, "publisher_id": "phintraco"}]})
    tuntun = {**row, "endpoint_id": "telegram:tuntunsekuritas", "address": "tuntunsekuritas", "capability_id": "company_news", "provider_id": None, "publisher_id": "tuntun"}
    assert endpoints({"subscriptions": [tuntun]}) == {}
    with pytest.raises(IntakeBlocked, match="identity is not verified"):
        endpoints({"subscriptions": [{**tuntun, "verification_status": "pending"}]})
    with pytest.raises(IntakeBlocked, match="not onboarded"):
        endpoints({"subscriptions": [{**tuntun, "capability_id": "trading_plans"}]})


@pytest.mark.parametrize("failing", ["news", "board"])
def test_board_and_synthetic_news_settle_independently(tmp_path, monkeypatch, failing):
    # Load the real Phintraco owner into this isolated package test. Its domain
    # handoff is no-post and uses an isolated ledger, while the News work is a
    # synthetic independent item. Production does not register a News handler.
    for package in ("cron-tg-phintraco-swing", "lib-swing-format", "lib-bursawatch-discord-delivery", "lib-telegram-resilience"):
        sys.path.insert(0, str(ROOT / package / "bin"))
    import scan as swing_scan
    spec = importlib.util.spec_from_file_location("phintraco_pipeline_owner_for_test", ROOT / "cron-tg-phintraco-swing" / "bin" / "pipeline_owner.py")
    assert spec and spec.loader
    swing_owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(swing_owner)
    monkeypatch.setenv("IDX_SWING_WATCH_PHINTRACO_DAILY_STATE_PATH", str(tmp_path / "swing.json"))
    configured = swing_scan.config.WatchConfig(1444713822, "phintraprofits", "1525102458253217803", "1505162000420835388")
    monkeypatch.setattr(swing_scan.config, "load_watch_config_for_run", lambda: swing_scan.config.LoadedWatchConfig(configured, 5))
    monkeypatch.setattr(swing_scan, "post_discord_text", lambda *args: "dry-text-11")
    board_events = []
    monkeypatch.setattr(swing_scan, "submit_board_event", lambda payload, chart, dry_run: board_events.append((payload.copy(), chart, dry_run)) or failing != "board")

    class WorkInbox(FakeInbox):
        def __init__(self):
            super().__init__()
            self.work = []
            self.settlements = []

        def accept(self, envelope):
            receipt = super().accept(envelope)
            event_key = receipt["event_key"]
            for pipeline, capability in (("swing_plan", "trading_plans"), ("company_news", "company_news")):
                effect = hashlib.sha256(f"{event_key}:1:{capability}".encode()).hexdigest()
                self.work.append({"work_key": effect, "effect_key": effect, "event_key": event_key, "version": 1, "capability_id": capability, "lease_token": pipeline, "pipeline_id": pipeline, "envelope": envelope})
            return receipt

        def claim(self, pipeline_ids, limit):
            selected = [item for item in self.work if item["pipeline_id"] in pipeline_ids][:limit]
            self.work = [item for item in self.work if item not in selected]
            return selected

        def begin(self, work_key, lease_token):
            return True

        def settle(self, work_key, lease_token, success, error_code=None):
            self.settlements.append((lease_token, success))
            return {"work_key": work_key, "status": "done" if success else "pending"}

    inbox = WorkInbox()
    telegram = FakeTelegram([message(10)])
    snapshot = {"subscriptions": [{"platform": "telegram", "enabled": True, "endpoint_id": "telegram:phintraprofits", "capability_id": "trading_plans", "verification_status": "verified", "provider_id": "1444713822", "publisher_id": "phintraco", "address": "phintraprofits"}]}
    assert "company_news" not in PIPELINE_OWNERS
    asyncio.run(run_once(telegram, snapshot, tmp_path, inbox, NOW, handlers={"swing_plan": lambda item: None}))
    text = (ROOT / "cron-tg-phintraco-swing" / "tests" / "fixtures" / "trading_buy.txt").read_text()
    telegram.messages.append(message(11, text))

    def failing_news(item):
        if failing == "news":
            raise RuntimeError("synthetic classifier failure")

    result = asyncio.run(run_once(telegram, snapshot, tmp_path, inbox, NOW, handlers={"company_news": failing_news, "swing_plan": lambda item: swing_owner.submit(item, no_post=True)}))
    assert result["source"][0]["accepted"] == 1
    assert {item["status"] for item in result["work"]} == {"done", "retry"}
    assert inbox.settlements == [("swing_plan", failing != "board"), ("company_news", failing != "news")]
    assert len(board_events) == 1
    assert board_events[0][0]["event_key"] == "phintraco:1444713822:11"
    assert board_events[0][0]["source"] == "phintraco"
    assert board_events[0][0]["kind"] == "buy"
    assert board_events[0][0]["plan"] == {"entry": "208 to 212", "stop_loss": "<200", "targets": ["230"]}
    assert board_events[0][0]["source_status"] == "New setup"
    assert board_events[0][2] is True
    assert len(inbox.accepted) == 1
