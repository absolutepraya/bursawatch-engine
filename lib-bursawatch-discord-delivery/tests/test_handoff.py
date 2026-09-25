import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

import pytest

from bursawatch_discord_delivery.client import DeliveryClientError
from bursawatch_discord_delivery.handoff import (
    APPLY_ENVIRONMENT_VARIABLE,
    HandoffError,
    HandoffItem,
    HandoffSnapshot,
    apply_handoff,
    plan_handoff,
    read_handoff_plan,
    require_apply_authorization,
)
from bursawatch_discord_delivery.models import Attachment, OperationIntent, OperationReceipt


def operation(key, content, *, preflight=None, attachment=None):
    return OperationIntent(
        key=key,
        kind="channel_message_create",
        ordering_key="channel:123",
        target={"channel_id": "123"},
        payload={"content": content},
        attachments=(() if attachment is None else (attachment,)),
        reconcile_before_first_create=preflight is not None,
    )


@dataclass
class FakeAdapter:
    source_path: Path
    plan_path: Path
    items: list[HandoffItem]

    def __post_init__(self):
        self.acknowledged = {}
        self.ack_order = []
        self.fail_ack_key = None
        self.fail_ack_once = False
        self.persist_acknowledgments = False

    def build_handoff_snapshot(self):
        raw = self.source_path.read_bytes()
        stable_source = b"\n".join(
            line for line in raw.split(b"\n") if not line.startswith(b"ACK:")
        )
        current = [
            HandoffItem(
                item.operation,
                receipt=item.receipt,
                preflight=item.preflight,
                acknowledged=item.operation.key in self.acknowledged,
            )
            for item in self.items
        ]
        # The source fingerprint intentionally excludes the separate handoff ack ledger.
        return HandoffSnapshot(backup_bytes=raw, source_hash_bytes=stable_source, items=tuple(current))

    def acknowledge(self, receipt):
        self.acknowledged[receipt.key] = receipt.digest
        self.ack_order.append(receipt.key)
        if self.persist_acknowledgments:
            with self.source_path.open("ab") as source:
                source.write(f"\nACK:{receipt.key}:{receipt.digest}".encode())
        if self.fail_ack_once and receipt.key == self.fail_ack_key:
            self.fail_ack_once = False
            raise OSError("simulated crash after owner acceptance")


class FakeOwner:
    def __init__(self, adapter=None, fail_after_accept_key=None):
        self.adapter = adapter
        self.fail_after_accept_key = fail_after_accept_key
        self.failed = False
        self.calls = []
        self.accepted = {}
        self.acknowledgments_seen_before_acceptance = []

    def _adopt(self, mode, operation, receipt=None, preflight=None):
        self.acknowledgments_seen_before_acceptance.append(set(self.adapter.acknowledged))
        self.calls.append((mode, operation.key, receipt, preflight))
        previous = self.accepted.get(operation.key)
        if previous is not None and previous.digest != operation.digest:
            raise AssertionError("the fake owner saw a changed digest for an accepted key")
        if previous is None:
            status = "delivered" if receipt is not None else "pending_reconciliation"
            previous = OperationReceipt(
                id=f"owner-{len(self.accepted) + 1}",
                key=operation.key,
                digest=operation.digest,
                status=status,
                receipt=dict(receipt) if receipt is not None else None,
            )
            self.accepted[operation.key] = previous
        if operation.key == self.fail_after_accept_key and not self.failed:
            self.failed = True
            raise DeliveryClientError("response_lost")
        return previous

    def adopt_completed(self, operation, receipt):
        return self._adopt("completed", operation, receipt=receipt)

    def adopt_pending(self, operation, *, preflight=None):
        return self._adopt("pending", operation, preflight=preflight)


def make_adapter(tmp_path, items):
    source = tmp_path / "legacy-state.bin"
    source.write_bytes(b"private legacy sender state\x00\xff")
    return FakeAdapter(source, tmp_path / "handoff-plan.json", items)


def test_plan_is_deterministic_private_payload_free_and_read_only(tmp_path):
    private_media_path = tmp_path / "private-media" / "chart.png"
    attachment = Attachment("chart.png", "image/png", b"PRIVATE-IMAGE-CONTENT")
    completed = operation("old:completed", f"private payload at {private_media_path}", attachment=attachment)
    pending = operation(
        "old:pending",
        f"pending source payload at {private_media_path}",
        preflight={"boundary_observed": True, "boundary": "700"},
    )
    adapter = make_adapter(tmp_path, [
        HandoffItem(completed, receipt={"channel_id": "123", "message_id": "456"}),
        HandoffItem(pending, preflight={"boundary_observed": True, "boundary": "700"}),
    ])
    before = adapter.source_path.read_bytes()

    plan = plan_handoff(adapter)
    first_bytes = adapter.plan_path.read_bytes()
    first_data = json.loads(first_bytes)

    assert adapter.source_path.read_bytes() == before
    assert stat.S_IMODE(adapter.plan_path.stat().st_mode) == 0o600
    assert first_data["source_sha256"] == hashlib.sha256(before).hexdigest()
    assert first_data["operation_count"] == 2
    assert first_data["completed_count"] == 1
    assert first_data["pending_count"] == 1
    assert first_data["unknown_outcome_count"] == 1
    assert first_data["operation_key_sha256"] == [
        hashlib.sha256(completed.key.encode()).hexdigest(),
        hashlib.sha256(pending.key.encode()).hexdigest(),
    ]
    assert first_data["payload_sha256"] == [completed.digest, pending.digest]
    assert first_data["operation_kinds"] == ["channel_message_create", "channel_message_create"]
    assert first_data["targets"] == [{"channel_id": "123"}, {"channel_id": "123"}]
    assert first_data["receipts"] == [
        {"channel_id": "123", "message_id": "456"},
        None,
    ]
    assert first_data["preflight"] == [None, {"boundary_observed": True, "boundary": "700"}]

    serialized = first_bytes.decode()
    assert completed.key not in serialized and pending.key not in serialized
    assert "private payload" not in serialized and "pending source payload" not in serialized
    assert "PRIVATE-IMAGE-CONTENT" not in serialized
    assert str(private_media_path) not in serialized
    assert str(adapter.source_path) not in serialized

    adapter.plan_path = tmp_path / "second-plan.json"
    plan_handoff(adapter)
    assert adapter.plan_path.read_bytes() == first_bytes
    assert plan.source_sha256 == first_data["source_sha256"]


def test_plan_apply_gate_requires_flag_and_environment(tmp_path):
    assert require_apply_authorization(
        apply=True,
        environment={APPLY_ENVIRONMENT_VARIABLE: "1"},
    ) is None
    for apply, environment in (
        (False, {APPLY_ENVIRONMENT_VARIABLE: "1"}),
        (True, {}),
        (True, {APPLY_ENVIRONMENT_VARIABLE: "true"}),
    ):
        with pytest.raises(HandoffError):
            require_apply_authorization(apply=apply, environment=environment)


def test_apply_refuses_changed_source_before_backup_or_owner_calls(tmp_path):
    intent = operation("legacy:changed", "exact saved message", preflight={"boundary_observed": True, "boundary": "10"})
    adapter = make_adapter(tmp_path, [HandoffItem(intent, preflight={"boundary_observed": True, "boundary": "10"})])
    plan = plan_handoff(adapter)
    plan = read_handoff_plan(adapter.plan_path)
    adapter.source_path.write_bytes(b"source changed after planning")
    owner = FakeOwner(adapter)

    with pytest.raises(HandoffError, match="source state changed"):
        apply_handoff(plan, adapter, owner)

    assert owner.calls == []
    assert adapter.ack_order == []
    assert not Path(str(adapter.plan_path) + ".source-backup").exists()


def test_apply_imports_completed_receipts_and_pending_preflight_then_acknowledges(tmp_path):
    completed = operation("legacy:known", "already sent")
    pending = operation(
        "legacy:uncertain",
        "uncertain exact content",
        preflight={"boundary_observed": True, "boundary": None},
    )
    adapter = make_adapter(tmp_path, [
        HandoffItem(completed, receipt={"channel_id": "123", "message_id": "456"}),
        HandoffItem(pending, preflight={"boundary_observed": True, "boundary": None}),
    ])
    plan_handoff(adapter)
    plan = read_handoff_plan(adapter.plan_path)
    owner = FakeOwner(adapter)

    result = apply_handoff(plan, adapter, owner)

    assert [(call[0], call[1]) for call in owner.calls] == [
        ("completed", "legacy:known"),
        ("pending", "legacy:uncertain"),
    ]
    assert owner.calls[0][2] == {"channel_id": "123", "message_id": "456"}
    assert owner.calls[1][3] == {"boundary_observed": True, "boundary": None}
    assert owner.acknowledgments_seen_before_acceptance == [set(), {"legacy:known"}]
    assert adapter.ack_order == ["legacy:known", "legacy:uncertain"]
    assert adapter.acknowledged == {
        key: owner.accepted[key].digest for key in owner.accepted
    }
    assert result.acknowledged_count == 2
    assert result.skipped_count == 0
    assert result.backup_path.read_bytes() == b"private legacy sender state\x00\xff"
    assert stat.S_IMODE(result.backup_path.stat().st_mode) == 0o600


def test_apply_rejects_owner_failure_without_acknowledging_item(tmp_path):
    intent = operation("legacy:rejected", "private body", preflight={"boundary_observed": True, "boundary": "55"})
    adapter = make_adapter(tmp_path, [HandoffItem(intent, preflight={"boundary_observed": True, "boundary": "55"})])
    plan_handoff(adapter)
    owner = FakeOwner(adapter, fail_after_accept_key=intent.key)

    with pytest.raises(HandoffError, match="did not acknowledge"):
        apply_handoff(read_handoff_plan(adapter.plan_path), adapter, owner)

    assert adapter.ack_order == []
    assert owner.accepted[intent.key].digest == intent.digest


def test_apply_crash_resumes_at_first_unacknowledged_key_idempotently(tmp_path):
    items = [
        HandoffItem(operation("legacy:first", "one", preflight={"boundary_observed": True, "boundary": "1"}),
                    preflight={"boundary_observed": True, "boundary": "1"}),
        HandoffItem(operation("legacy:second", "two", preflight={"boundary_observed": True, "boundary": "2"}),
                    preflight={"boundary_observed": True, "boundary": "2"}),
        HandoffItem(operation("legacy:third", "three", preflight={"boundary_observed": True, "boundary": "3"}),
                    preflight={"boundary_observed": True, "boundary": "3"}),
    ]
    adapter = make_adapter(tmp_path, items)
    adapter.persist_acknowledgments = True
    plan_handoff(adapter)
    plan = read_handoff_plan(adapter.plan_path)
    owner = FakeOwner(adapter, fail_after_accept_key="legacy:second")

    with pytest.raises(HandoffError):
        apply_handoff(plan, adapter, owner)
    assert adapter.ack_order == ["legacy:first"]
    assert [call[1] for call in owner.calls] == ["legacy:first", "legacy:second"]

    result = apply_handoff(plan, adapter, owner)

    assert [call[1] for call in owner.calls] == [
        "legacy:first", "legacy:second", "legacy:second", "legacy:third",
    ]
    assert set(owner.accepted) == {"legacy:first", "legacy:second", "legacy:third"}
    assert adapter.ack_order == ["legacy:first", "legacy:second", "legacy:third"]
    assert result.acknowledged_count == 2
    assert result.skipped_count == 1


def test_apply_imports_pending_create_without_hint_for_conservative_reconciliation(tmp_path):
    intent = operation("legacy:no-boundary", "unknown prior create", preflight={"boundary_observed": True, "boundary": "9"})
    adapter = make_adapter(tmp_path, [HandoffItem(intent)])
    plan_handoff(adapter)
    owner = FakeOwner(adapter)

    result = apply_handoff(read_handoff_plan(adapter.plan_path), adapter, owner)

    assert len(owner.calls) == 1
    assert owner.calls[0][0:2] == ("pending", intent.key)
    assert owner.calls[0][3] is None
    assert adapter.ack_order == [intent.key]
    assert result.acknowledged_count == 1
