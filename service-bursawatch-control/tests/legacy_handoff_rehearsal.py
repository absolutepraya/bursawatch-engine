from __future__ import annotations

from pathlib import Path
from typing import Callable

from bursawatch_discord_delivery.handoff import HandoffAdapter, apply_handoff, plan_handoff, read_handoff_plan
from bursawatch_discord_delivery.models import OperationReceipt


class SyntheticDeliveryOwner:
    """Idempotent in-memory Delivery Owner for local handoff rehearsals."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[str, OperationReceipt]] = {}
        self.new_pending_acceptances: list[str] = []

    def _accept(self, operation, *, receipt, completed: bool) -> OperationReceipt:
        prior = self.records.get(operation.key)
        if prior is not None:
            digest, saved = prior
            assert digest == operation.digest
            return saved
        if completed:
            status = "delivered"
            result_receipt = dict(receipt)
        else:
            status = "pending_reconciliation"
            result_receipt = None
            self.new_pending_acceptances.append(operation.key)
        result = OperationReceipt(
            id=f"synthetic-{len(self.records) + 1}",
            key=operation.key,
            digest=operation.digest,
            status=status,
            receipt=result_receipt,
        )
        self.records[operation.key] = (operation.digest, result)
        return result

    def adopt_completed(self, operation, receipt):
        return self._accept(operation, receipt=receipt, completed=True)

    def adopt_pending(self, operation, *, preflight=None):
        del preflight
        return self._accept(operation, receipt=None, completed=False)

    def query(self, query):
        del query
        return {"available_tags": [{"id": "1550000000000000008", "name": "Primary plan"}]}


class AcknowledgmentObserver:
    """Assert that source acknowledgment follows durable fake-owner acceptance."""

    def __init__(self, adapter: HandoffAdapter, owner: SyntheticDeliveryOwner) -> None:
        self.adapter = adapter
        self.owner = owner

    @property
    def plan_path(self) -> Path:
        return self.adapter.plan_path

    def build_handoff_snapshot(self):
        return self.adapter.build_handoff_snapshot()

    def acknowledge(self, receipt: OperationReceipt) -> None:
        assert receipt.key in self.owner.records
        assert self.owner.records[receipt.key][0] == receipt.digest
        self.adapter.acknowledge(receipt)


def rehearse_legacy_handoff(
    adapter: HandoffAdapter,
    owner: SyntheticDeliveryOwner,
    *,
    restore_source: Callable[[], None],
) -> tuple[tuple[str, str], ...]:
    """Plan, apply, roll back source state, and retry without duplicate effects."""
    plan = (
        read_handoff_plan(adapter.plan_path)
        if adapter.plan_path.exists()
        else plan_handoff(adapter, plan_path=adapter.plan_path)
    )
    snapshot = adapter.build_handoff_snapshot()
    identities = tuple((item.operation.key, item.operation.digest) for item in snapshot.items)
    assert plan.operation_count == len(identities)
    assert len(set(identities)) == len(identities)

    initial_effects = tuple(
        item.operation.key for item in snapshot.items if item.receipt is None
    )
    observing = AcknowledgmentObserver(adapter, owner)
    first = apply_handoff(adapter.plan_path, observing, owner)
    assert first.acknowledged_count == len(snapshot.items)
    assert tuple(owner.new_pending_acceptances) == initial_effects

    # Model restoring the pre-cutover owner state. The fake Delivery Owner keeps
    # its ledger, as production rollback must not erase accepted operations.
    restore_source()
    ack_path = getattr(adapter, "ack_path", None)
    if isinstance(ack_path, Path):
        ack_path.unlink(missing_ok=True)
    retry_snapshot = adapter.build_handoff_snapshot()
    assert tuple((item.operation.key, item.operation.digest) for item in retry_snapshot.items) == identities

    second = apply_handoff(adapter.plan_path, observing, owner)
    assert second.acknowledged_count == len(snapshot.items)
    assert tuple(owner.new_pending_acceptances) == initial_effects
    assert tuple(owner.records) == tuple(key for key, _digest in identities)
    return identities
