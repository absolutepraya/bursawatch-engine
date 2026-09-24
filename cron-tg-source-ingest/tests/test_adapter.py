from __future__ import annotations

import asyncio
import hashlib
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
from runner import run_once


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
    with pytest.raises(IntakeBlocked, match="durable storage"):
        await ingest_endpoint(client, ENDPOINT, tmp_path, inbox, NOW)
    cursor = tmp_path / "telegram-phintraprofits" / "cursor.json"
    assert json.loads(cursor.read_text())["cursor"] == 11
    blocked = json.loads((cursor.parent / "blocked-media.json").read_text())
    assert blocked["message_id"] == 12
    assert [item["provider_event_id"] for item in inbox.accepted] == ["11"]


def test_effective_catalog_rejects_unknown_enabled_endpoint():
    row = {"platform": "telegram", "enabled": True, "endpoint_id": "telegram:phintraprofits", "capability_id": "trading_plans", "verification_status": "verified", "provider_id": "1444713822", "publisher_id": "phintraco", "address": "phintraprofits"}
    assert endpoints({"subscriptions": [row]})["telegram:phintraprofits"]["capabilities"] == {"trading_plans"}
    with pytest.raises(IntakeBlocked, match="not onboarded"):
        endpoints({"subscriptions": [{**row, "endpoint_id": "telegram:unknown"}]})
    assert endpoints({"subscriptions": [{**row, "endpoint_id": "telegram:tuntunsekuritas"}]}) == {}


def test_fanout_failure_isolated_from_other_subscription(tmp_path):
    class WorkInbox(FakeInbox):
        def __init__(self):
            super().__init__()
            self.work = []
            self.settlements = []

        def accept(self, envelope):
            receipt = super().accept(envelope)
            for pipeline in ("stock_status", "company_news"):
                self.work.append({"work_key": hashlib.sha256(pipeline.encode()).hexdigest(), "lease_token": pipeline, "pipeline_id": pipeline, "envelope": envelope})
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
    telegram = FakeTelegram([message(10)], address="phintasprofits")
    snapshot = {"subscriptions": [{"platform": "telegram", "enabled": True, "endpoint_id": "telegram:phintasprofits", "capability_id": capability, "verification_status": "verified", "provider_id": None, "publisher_id": "phintraco", "address": "phintasprofits"} for capability in ("company_news", "stock_status")]}
    asyncio.run(run_once(telegram, snapshot, tmp_path, inbox, NOW, handlers={"stock_status": lambda item: None, "company_news": lambda item: None}))
    telegram.messages.append(message(11, "synthetic event"))

    def failing_news(item):
        raise RuntimeError("synthetic classifier failure")

    result = asyncio.run(run_once(telegram, snapshot, tmp_path, inbox, NOW, handlers={"company_news": failing_news, "stock_status": lambda item: None}))
    assert result["source"][0]["accepted"] == 1
    assert {item["status"] for item in result["work"]} == {"done", "retry"}
    assert inbox.settlements == [("stock_status", True), ("company_news", False)]
    assert len(inbox.accepted) == 1
