"""Observe one immutable operation through the shared delivery adapter."""

from __future__ import annotations

from dataclasses import asdict
import math
from typing import Protocol

from .client import DeliveryClientError, NON_TERMINAL_STATUSES
from .models import OperationIntent, OperationReceipt, ValidationError


DELIVERY_RECEIPT_WAIT_SECONDS = 10


class DeliveryAdapter(Protocol):
    def status(self, operation_key: str) -> OperationReceipt | None: ...
    def submit(self, operation: OperationIntent) -> OperationReceipt: ...
    def wait(self, operation_key: str, timeout_seconds: float) -> OperationReceipt: ...


def _matching_receipt(receipt: OperationReceipt, operation: OperationIntent) -> OperationReceipt:
    try:
        if not isinstance(receipt, OperationReceipt):
            raise ValidationError("invalid operation response")
        return OperationReceipt.from_json(asdict(receipt), operation)
    except (ValidationError, TypeError):
        raise DeliveryClientError("invalid_response") from None


def observe_operation(
    delivery: DeliveryAdapter,
    operation: OperationIntent,
    *,
    timeout_seconds: float = DELIVERY_RECEIPT_WAIT_SECONDS,
) -> OperationReceipt:
    """Look up, submit if absent, and observe the same operation without retrying writes.

    Return the latest matching receipt, including pending or terminal failure states.
    The timeout retains ``wait`` semantics: it bounds polling after wait's initial
    status read, not the initial lookup, submission, or total elapsed time. Callers
    retain scheduling, durable retries, and policy for advancing dependent work.
    """
    if not isinstance(operation, OperationIntent):
        raise DeliveryClientError("invalid_operation")
    if (not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds < 0):
        raise DeliveryClientError("invalid_timeout")
    receipt = delivery.status(operation.key)
    if receipt is None:
        receipt = delivery.submit(operation)
    receipt = _matching_receipt(receipt, operation)
    if receipt.status in NON_TERMINAL_STATUSES:
        receipt = _matching_receipt(delivery.wait(operation.key, timeout_seconds), operation)
    return receipt
