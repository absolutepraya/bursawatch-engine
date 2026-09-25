from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
for package_path in (
    ROOT / "lib-bursawatch-control/bin",
    ROOT / "lib-bursawatch-pipeline-runtime/bin",
    ROOT / "lib-bursawatch-source-ingest/bin",
    ROOT / "service-bursawatch-discord-delivery/bin",
):
    sys.path.append(str(package_path))

from control_plane.source_catalog import MemoryCatalogStore, initial_config
from control_plane.source_inbox import MemoryInboxStore
from discord_delivery.models import OperationIntent
from discord_delivery.store import DeliveryStore
from pipeline_runtime import PipelineRuntime
from source_event_client import SourceEventHandoff
from source_ingest import _save_cursor, envelope


class InProcessSourceInbox:
    """Contract adapter for the synthetic Control Plane inbox."""

    def __init__(self, inbox: MemoryInboxStore):
        self.inbox = inbox

    def accept(self, value: dict[str, object]) -> dict[str, object]:
        return self.inbox.accept(value)

    def claim(self, pipeline_ids: list[str], limit: int) -> list[dict[str, object]]:
        return self.inbox.claim(pipeline_ids, limit)

    def begin(self, work_key: str, lease_token: str) -> bool:
        return self.inbox.begin(work_key, lease_token)

    def settle(self, work_key: str, lease_token: str, success: bool, error_code: str | None = None) -> dict[str, object]:
        return self.inbox.settle(work_key, lease_token, success=success, error_code=error_code)


def _catalog_inbox() -> MemoryInboxStore:
    catalog = MemoryCatalogStore()
    config = initial_config()
    config["publisher_defaults"] = [
        {"publisher_id": "phintraco", "capability_id": "company_news", "enabled": True, "settings": {}}
    ]
    catalog.put(1, config, "synthetic-test")
    return MemoryInboxStore(catalog)


def test_synthetic_cutover_and_rollback_keep_source_work_and_delivery_receipt(tmp_path: Path) -> None:
    endpoint = {
        "endpoint_id": "telegram:phintasprofits",
        "platform": "telegram",
        "publisher_id": "phintraco",
    }
    old_state = {
        "schema_version": 1,
        "cursor": {"anchor": "100", "position": "100"},
        "pending": [
            {
                "provider_event_id": "101",
                "published_at": "2026-09-24T07:00:00+07:00",
                "source_url": "https://t.me/phintasprofits/101",
                "payload": {"text": "synthetic pending source"},
            },
            {
                "provider_event_id": "102",
                "published_at": "2026-09-24T07:02:00+07:00",
                "source_url": "https://t.me/phintasprofits/102",
                "payload": {"text": "synthetic uncertain delivery"},
            },
        ],
    }
    legacy_path = tmp_path / "legacy-reader" / "endpoint-state.json"
    legacy_path.parent.mkdir()
    legacy_bytes = json.dumps(old_state, sort_keys=True, separators=(",", ":")).encode()
    legacy_path.write_bytes(legacy_bytes)
    backup_path = tmp_path / "private-snapshot" / "endpoint-state.json"
    backup_path.parent.mkdir(mode=0o700)
    backup_path.write_bytes(legacy_bytes)
    source_digest = hashlib.sha256(legacy_bytes).hexdigest()
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == source_digest

    inbox = _catalog_inbox()
    in_process = InProcessSourceInbox(inbox)
    migrated_root = tmp_path / "new-reader"
    endpoint_root = migrated_root / endpoint["endpoint_id"].replace(":", "-")
    cursor_path = endpoint_root / "cursor.json"
    _save_cursor(cursor_path, "100", "100")

    handoff = SourceEventHandoff(endpoint_root / "handoff", in_process)
    assert json.loads(cursor_path.read_text()) == {"initialized": True, "anchor": "100", "position": "100"}
    accepted_events = []
    for pending_item in old_state["pending"]:
        source_event = envelope(
            endpoint,
            pending_item,
            datetime(2026, 9, 24, 7, 1, tzinfo=timezone.utc),
            "synthetic-parser-v1",
        )
        handoff.stage(source_event)
        receipt = handoff.flush(limit=1)
        assert len(receipt) == 1 and receipt[0]["duplicate"] is False
        accepted_events.append((source_event, receipt[0]))
        # Each imported queue item advances only after its inbox receipt.
        _save_cursor(cursor_path, pending_item["provider_event_id"], pending_item["provider_event_id"])
    assert json.loads(cursor_path.read_text()) == {"initialized": True, "anchor": "102", "position": "102"}
    old_state["pending"] = []
    legacy_path.write_text(json.dumps(old_state, sort_keys=True, separators=(",", ":")))

    delivery_path = tmp_path / "delivery" / "operations.sqlite3"
    delivery = DeliveryStore(delivery_path, tmp_path / "delivery-media")
    effects: list[str] = []

    def deliver(item: dict[str, object]) -> None:
        work_key = str(item["work_key"])
        event = item["envelope"]
        assert isinstance(event, dict)
        operation_key = f"source:{work_key}"
        intent = OperationIntent(
            key=operation_key,
            kind="thread_message_create",
            ordering_key=f"source:{event['provider_event_id']}",
            target={"thread_id": "123456789012345678"},
            payload={
                "content": f"Synthetic event {event['provider_event_id']}",
                "allowed_mentions": {"parse": []},
            },
        )
        if delivery.get_by_key(operation_key) is None:
            delivery.accept(intent)
        claimed = delivery.claim_next()
        assert claimed is not None and claimed.key == operation_key
        if event["provider_event_id"] == "101":
            status = "delivered"
            receipt = {"message_id": "987654321098765432", "thread_id": "123456789012345678"}
            delivery.finish(operation_key, status, receipt=receipt)
        else:
            status = "ambiguous"
            delivery.finish(operation_key, status)
        effects.append(operation_key)

    runtime = PipelineRuntime(in_process, {"company_news": deliver})
    first = runtime.run_once()
    assert len(first) == 2 and all(item["status"] == "done" for item in first)
    work_keys = [receipt["work_keys"][0] for _event, receipt in accepted_events]
    operation_keys = [f"source:{work_key}" for work_key in work_keys]
    original_receipt = delivery.get_by_key(operation_keys[0]).receipt
    assert delivery.get_by_key(operation_keys[0]).status == "delivered"
    assert delivery.get_by_key(operation_keys[1]).status == "ambiguous"
    assert effects == operation_keys
    delivery.db.close()

    # Roll back only the source reader. Keep accepted inbox work and receipts.
    legacy_path.write_bytes(backup_path.read_bytes())
    restored_legacy = json.loads(legacy_path.read_text())
    replayed = []
    for pending_item, (source_event, accepted) in zip(restored_legacy["pending"], accepted_events):
        replayed_event = envelope(
            endpoint,
            pending_item,
            datetime(2026, 9, 24, 7, 1, tzinfo=timezone.utc),
            "synthetic-parser-v1",
        )
        handoff.stage(replayed_event)
        replay_receipt = handoff.flush(limit=1)
        assert replay_receipt[0]["duplicate"] is True
        assert replay_receipt[0]["event_key"] == accepted["event_key"]
        assert inbox.inspect(accepted["event_key"])["work"][0]["status"] == "done"
        replayed.append(replay_receipt[0]["event_key"])
    assert replayed == [accepted["event_key"] for _event, accepted in accepted_events]
    assert runtime.run_once() == []

    reopened_delivery = DeliveryStore(delivery_path, tmp_path / "delivery-media")
    restored_receipt = reopened_delivery.get_by_key(operation_keys[0])
    assert restored_receipt is not None
    assert restored_receipt.status == "delivered"
    assert restored_receipt.receipt == original_receipt
    uncertain = reopened_delivery.get_by_key(operation_keys[1])
    assert uncertain is not None and uncertain.status == "ambiguous" and uncertain.receipt is None
    assert effects == operation_keys
    reopened_delivery.db.close()
