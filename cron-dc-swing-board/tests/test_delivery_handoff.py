from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHARED_BIN = ROOT / "lib-bursawatch-discord-delivery" / "bin"
if str(SHARED_BIN) not in sys.path:
    sys.path.insert(0, str(SHARED_BIN))

from bursawatch_discord_delivery.handoff import APPLY_ENVIRONMENT_VARIABLE, HandoffError, apply_handoff, plan_handoff
from bursawatch_discord_delivery.models import OperationIntent, OperationReceipt

import delivery_handoff
from store import BoardStore


NOW = datetime.fromisoformat("2026-09-21T10:00:00+07:00")


class ReadOnlyDelivery:
    def __init__(self):
        self.queries = []
        self.adopted = []

    def query(self, query):
        self.queries.append(query)
        assert query.kind == "forum_channel_read"
        return {"available_tags": [{"id": "1550000000000000008", "name": "Primary plan"}]}

    def adopt_completed(self, intent, receipt):
        self.adopted.append(("completed", intent, dict(receipt)))
        return OperationReceipt(
            id=f"adopted-{len(self.adopted)}", key=intent.key, digest=intent.digest,
            status="delivered", receipt=dict(receipt),
        )

    def adopt_pending(self, intent, *, preflight=None):
        self.adopted.append(("pending", intent, preflight))
        return OperationReceipt(
            id=f"adopted-{len(self.adopted)}", key=intent.key, digest=intent.digest,
            status="pending_reconciliation", receipt=None,
        )


def _fixture_state(tmp_path):
    state_path = tmp_path / "board.sqlite3"
    chart = tmp_path / "chart.png"
    chart.write_bytes(b"persisted chart bytes")
    store = BoardStore(state_path)
    episode = store.create_episode("SCMA", "primary", "SCMA", NOW)
    create = store.enqueue_outbox(
        "create_thread", episode.id,
        {"name": "SCMA", "content": "private card body", "tag_names": ["Primary plan"],
         "chart": str(chart)},
        "event:board:create", NOW,
    )
    claim = store.claim_due_outbox(NOW)
    store.complete_outbox(
        create.id, claim.claim_token,
        {"thread_id": "1550000000000000001", "starter_message_id": "1550000000000000001"}, NOW,
    )
    reply = store.enqueue_outbox(
        "post_source_reply", episode.id,
        {"content": "private reply body", "media": None},
        "event:board:reply", NOW,
    )
    claim = store.claim_due_outbox(NOW)
    store.complete_outbox(reply.id, claim.claim_token, {"message_id": "1550000000000000002"}, NOW)
    pending = store.enqueue_outbox(
        "post_history_reply", episode.id,
        {"content": "private pending reply", "media": None, "nonce_value": "history:old"},
        "event:board:history", NOW,
    )
    pending_payload = dict(pending.payload)
    pending_payload["create_snapshot"] = {
        "after_id": "1550000000000000000",
        "started_at": "2026-09-21T03:00:00+00:00",
        "bot_id": "1550000000000000009",
        "content": "private pending reply",
        "filename": None,
        "operation_key": "event:board:history",
    }
    with sqlite3.connect(state_path) as connection:
        connection.execute(
            "UPDATE outbox SET payload_json = ? WHERE id = ?",
            (json.dumps(pending_payload, sort_keys=True), pending.id),
        )
    store.enqueue_heartbeat(
        "1505162000420835388", "private heartbeat text", "scheduled-heartbeat:v1:initial:r1", NOW
    )
    return store, chart


def _filesystem_bytes(path):
    return {
        suffix: Path(f"{path}{suffix}").read_bytes()
        for suffix in ("", "-wal", "-shm")
        if Path(f"{path}{suffix}").exists()
    }


def _logical_state(path):
    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            for table in ("episodes", "outbox", "channel_outbox")
        }


def test_plan_is_read_only_payload_free_and_preserves_ids_and_create_snapshot(tmp_path):
    store, chart = _fixture_state(tmp_path)
    before_state = _logical_state(store.path)
    owner = ReadOnlyDelivery()
    plan_path = tmp_path / "handoff.json"
    adapter = delivery_handoff.SwingBoardHandoffAdapter(
        store.path, plan_path, media_root=tmp_path, delivery_client=owner
    )

    plan = plan_handoff(adapter, plan_path=plan_path)
    snapshot = adapter.build_handoff_snapshot()

    assert _logical_state(store.path) == before_state
    assert len(snapshot.items) == 4
    completed_thread, completed_reply, pending_reply, pending_heartbeat = snapshot.items
    assert completed_thread.receipt == {
        "thread_id": "1550000000000000001", "message_id": "1550000000000000001"
    }
    assert completed_thread.operation.attachments[0].data == chart.read_bytes()
    assert completed_reply.receipt == {"message_id": "1550000000000000002"}
    assert pending_reply.operation.reconcile_before_first_create is True
    assert pending_reply.preflight == {
        "boundary_observed": True, "boundary": "1550000000000000000"
    }
    assert pending_reply.operation.legacy_nonce == delivery_handoff.stable_nonce("event:board:history")
    assert pending_heartbeat.operation.kind == "channel_message_create"
    assert pending_heartbeat.operation.reconcile_before_first_create is True
    assert pending_heartbeat.operation.legacy_nonce == delivery_handoff.stable_nonce(
        "scheduled-heartbeat:v1:initial:r1"
    )
    assert plan.operation_count == 4
    assert plan.completed_count == 2 and plan.pending_count == 2
    serialized_plan = plan_path.read_text()
    assert "private card body" not in serialized_plan
    assert "private reply body" not in serialized_plan
    assert "private pending reply" not in serialized_plan
    assert "private heartbeat text" not in serialized_plan
    assert str(chart) not in serialized_plan
    assert "chart.png" not in serialized_plan
    assert owner.queries and all(query.kind == "forum_channel_read" for query in owner.queries)


def test_apply_requires_both_gates_and_resume_keeps_source_ids(tmp_path):
    store, _chart = _fixture_state(tmp_path)
    owner = ReadOnlyDelivery()
    plan_path = tmp_path / "handoff.json"
    adapter = delivery_handoff.SwingBoardHandoffAdapter(
        store.path, plan_path, media_root=tmp_path, delivery_client=owner
    )
    plan_handoff(adapter, plan_path=plan_path)

    with pytest.raises(HandoffError, match="explicit environment gate"):
        delivery_handoff.apply_swing_board_handoff(
            plan_path, adapter, owner, apply=True,
            environment={APPLY_ENVIRONMENT_VARIABLE: "0"},
        )

    result = delivery_handoff.apply_swing_board_handoff(
        plan_path, adapter, owner, apply=True,
        environment={APPLY_ENVIRONMENT_VARIABLE: "1"},
    )
    assert result.acknowledged_count == 4
    assert result.skipped_count == 0
    assert os.stat(result.backup_path).st_mode & 0o777 == 0o600
    assert store.active_episode("SCMA").thread_id == "1550000000000000001"
    assert store.active_episode("SCMA").starter_message_id == "1550000000000000001"
    assert [item[0] for item in owner.adopted] == [
        "completed", "completed", "pending", "pending"
    ]

    restarted_adapter = delivery_handoff.SwingBoardHandoffAdapter(
        store.path, plan_path, media_root=tmp_path, delivery_client=owner
    )
    resumed = apply_handoff(plan_path, restarted_adapter, owner)
    assert resumed.acknowledged_count == 0
    assert resumed.skipped_count == 4
    assert len(owner.adopted) == 4


def test_plan_rejects_create_snapshot_that_does_not_match_persisted_payload(tmp_path):
    store, _chart = _fixture_state(tmp_path)
    with sqlite3.connect(store.path) as connection:
        row = connection.execute(
            "SELECT id, payload_json FROM outbox WHERE dedupe_key = 'event:board:history'"
        ).fetchone()
        payload = json.loads(row[1])
        payload["content"] = "changed"
        connection.execute(
            "UPDATE outbox SET payload_json = ? WHERE id = ?",
            (json.dumps(payload, sort_keys=True), row[0]),
        )
    owner = ReadOnlyDelivery()
    adapter = delivery_handoff.SwingBoardHandoffAdapter(
        store.path, tmp_path / "handoff.json", media_root=tmp_path, delivery_client=owner
    )

    with pytest.raises(HandoffError, match="snapshot does not match"):
        adapter.build_handoff_snapshot()


def test_synthetic_rollback_retry_reuses_board_operation_keys(tmp_path):
    support = str(ROOT / "service-bursawatch-control" / "tests")
    if support not in sys.path:
        sys.path.insert(0, support)
    from legacy_handoff_rehearsal import SyntheticDeliveryOwner, rehearse_legacy_handoff

    store, _chart = _fixture_state(tmp_path)
    owner = SyntheticDeliveryOwner()
    adapter = delivery_handoff.SwingBoardHandoffAdapter(
        store.path, tmp_path / "board-handoff.json", media_root=tmp_path, delivery_client=owner
    )

    identities = rehearse_legacy_handoff(adapter, owner, restore_source=lambda: None)

    assert len(identities) == 4
