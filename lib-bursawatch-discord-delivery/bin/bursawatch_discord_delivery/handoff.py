"""Crash-safe, payload-free plans for owner-specific sender-state handoffs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .client import DeliveryClient, DeliveryClientError
from .models import (
    OperationIntent,
    OperationReceipt,
    ValidationError,
    validate_preflight,
    validate_receipt,
)


APPLY_ENVIRONMENT_VARIABLE = "BURSAWATCH_DISCORD_HANDOFF_ALLOW_APPLY"
PLAN_VERSION = 1
_PLAN_FIELDS = frozenset({
    "schema_version",
    "source_sha256",
    "backup_sha256",
    "operation_count",
    "completed_count",
    "pending_count",
    "unknown_outcome_count",
    "operation_key_sha256",
    "payload_sha256",
    "operation_kinds",
    "targets",
    "receipts",
    "preflight",
})


class HandoffError(RuntimeError):
    """A sanitized handoff validation, backup, or acceptance failure."""


class HandoffAdapter(Protocol):
    """The package adapter owns decoding and durable source acknowledgments.

    `source_hash_bytes` must be a deterministic representation of the source
    delivery state that stays stable when this protocol writes only handoff
    acknowledgments. `backup_bytes` is the exact private pre-migration backup.
    """

    plan_path: Path

    def build_handoff_snapshot(self) -> "HandoffSnapshot": ...

    def acknowledge(self, receipt: OperationReceipt) -> None: ...


@dataclass(frozen=True)
class HandoffItem:
    operation: OperationIntent
    receipt: Mapping[str, str] | None = None
    preflight: Mapping[str, Any] | None = None
    acknowledged: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.operation, OperationIntent):
            raise HandoffError("invalid handoff operation")
        if type(self.acknowledged) is not bool:
            raise HandoffError("invalid handoff acknowledgment state")
        if self.receipt is not None:
            try:
                validated = validate_receipt(
                    self.receipt, str(self.operation.kind), self.operation.target
                )
            except (ValidationError, TypeError):
                raise HandoffError("invalid known handoff receipt") from None
            object.__setattr__(self, "receipt", validated)
            if self.preflight is not None:
                raise HandoffError("completed handoff item cannot carry preflight metadata")
        if self.preflight is not None:
            try:
                object.__setattr__(
                    self,
                    "preflight",
                    validate_preflight(self.preflight, str(self.operation.kind)),
                )
            except ValidationError:
                raise HandoffError("invalid handoff preflight metadata") from None


@dataclass(frozen=True)
class HandoffSnapshot:
    backup_bytes: bytes
    source_hash_bytes: bytes
    items: tuple[HandoffItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.backup_bytes, bytes) or not isinstance(self.source_hash_bytes, bytes):
            raise HandoffError("invalid handoff source snapshot")
        if not isinstance(self.items, (tuple, list)) or any(
            not isinstance(item, HandoffItem) for item in self.items
        ):
            raise HandoffError("invalid handoff operation snapshot")
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class HandoffPlan:
    source_sha256: str
    backup_sha256: str
    operation_count: int
    completed_count: int
    pending_count: int
    unknown_outcome_count: int
    operation_key_sha256: tuple[str, ...]
    payload_sha256: tuple[str, ...]
    operation_kinds: tuple[str, ...]
    targets: tuple[dict[str, str], ...]
    receipts: tuple[dict[str, str] | None, ...]
    preflight: tuple[dict[str, Any] | None, ...]
    plan_path: Path | None = field(default=None, compare=False, repr=False)

    def as_dict(self) -> dict[str, Any]:
        """Return the private, deterministic plan document without local paths."""
        return {
            "schema_version": PLAN_VERSION,
            "source_sha256": self.source_sha256,
            "backup_sha256": self.backup_sha256,
            "operation_count": self.operation_count,
            "completed_count": self.completed_count,
            "pending_count": self.pending_count,
            "unknown_outcome_count": self.unknown_outcome_count,
            "operation_key_sha256": list(self.operation_key_sha256),
            "payload_sha256": list(self.payload_sha256),
            "operation_kinds": list(self.operation_kinds),
            "targets": [dict(target) for target in self.targets],
            "receipts": [dict(receipt) if receipt is not None else None for receipt in self.receipts],
            "preflight": [dict(value) if value is not None else None for value in self.preflight],
        }


@dataclass(frozen=True)
class HandoffResult:
    acknowledged_count: int
    skipped_count: int
    backup_path: Path


def hash_source_bytes(source: bytes) -> str:
    """Return the SHA-256 digest of a captured source-state snapshot."""
    if not isinstance(source, bytes):
        raise HandoffError("invalid handoff source snapshot")
    return hashlib.sha256(source).hexdigest()


def hash_source_file(path: Path) -> str:
    """Hash one regular source file without including its path in the result."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("source is not a regular file")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            shutil.copyfileobj(source, _HashingWriter(digest))
        return digest.hexdigest()
    except (OSError, ValueError):
        raise HandoffError("cannot hash handoff source state") from None


class _HashingWriter:
    def __init__(self, digest: Any) -> None:
        self.digest = digest

    def write(self, data: bytes) -> int:
        self.digest.update(data)
        return len(data)


def operation_key_digest(operation_key: str) -> str:
    if not isinstance(operation_key, str):
        raise HandoffError("invalid operation key")
    return hashlib.sha256(operation_key.encode("utf-8")).hexdigest()


def handoff_summary(source_digest: str, operations: list[OperationIntent]) -> dict[str, Any]:
    """Build a payload-free summary suitable for a local plan file."""
    if len(source_digest) != 64 or any(character not in "0123456789abcdef" for character in source_digest):
        raise HandoffError("invalid source digest")
    return {
        "source_sha256": source_digest,
        "operation_count": len(operations),
        "operation_key_sha256": [operation_key_digest(operation.key) for operation in operations],
        "payload_sha256": [operation.digest for operation in operations],
    }


def write_private_backup(source: bytes, backup_path: Path) -> None:
    """Create a mode-0600 backup without replacing an existing backup."""
    if not isinstance(source, bytes):
        raise HandoffError("invalid backup source")
    try:
        backup_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(backup_path.parent, 0o700)
        descriptor = os.open(
            os.fspath(backup_path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as target:
            target.write(source)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(backup_path, 0o600)
    except FileExistsError:
        raise HandoffError("handoff backup already exists") from None
    except OSError:
        raise HandoffError("cannot create private handoff backup") from None


def require_apply_authorization(
    *,
    apply: bool,
    environment: Mapping[str, str] | None = None,
) -> None:
    """Require both the explicit CLI flag and the handoff environment gate."""
    values = os.environ if environment is None else environment
    if not apply or values.get(APPLY_ENVIRONMENT_VARIABLE) != "1":
        raise HandoffError("handoff apply requires --apply and the explicit environment gate")


def _snapshot(adapter: HandoffAdapter) -> HandoffSnapshot:
    try:
        builder = getattr(adapter, "build_handoff_snapshot")
        snapshot = builder()
    except Exception:
        raise HandoffError("cannot read handoff source state") from None
    if not isinstance(snapshot, HandoffSnapshot):
        raise HandoffError("invalid handoff source snapshot")
    seen: set[str] = set()
    for item in snapshot.items:
        if item.operation.key in seen:
            raise HandoffError("duplicate handoff operation identity")
        seen.add(item.operation.key)
        if item.receipt is None:
            if not item.operation.kind.endswith("_create") or not item.operation.reconcile_before_first_create:
                raise HandoffError("pending handoff operation requires pre-create reconciliation")
    return snapshot


def _plan_for_snapshot(snapshot: HandoffSnapshot, plan_path: Path | None = None) -> HandoffPlan:
    operations = [item.operation for item in snapshot.items]
    summary = handoff_summary(hash_source_bytes(snapshot.source_hash_bytes), operations)
    receipts = tuple(dict(item.receipt) if item.receipt is not None else None for item in snapshot.items)
    preflight = tuple(dict(item.preflight) if item.preflight is not None else None for item in snapshot.items)
    completed_count = sum(receipt is not None for receipt in receipts)
    pending_count = len(receipts) - completed_count
    return HandoffPlan(
        source_sha256=summary["source_sha256"],
        backup_sha256=hash_source_bytes(snapshot.backup_bytes),
        operation_count=len(operations),
        completed_count=completed_count,
        pending_count=pending_count,
        unknown_outcome_count=pending_count,
        operation_key_sha256=tuple(summary["operation_key_sha256"]),
        payload_sha256=tuple(summary["payload_sha256"]),
        operation_kinds=tuple(str(item.operation.kind) for item in snapshot.items),
        targets=tuple(dict(item.operation.target) for item in snapshot.items),
        receipts=receipts,
        preflight=preflight,
        plan_path=plan_path,
    )


def _write_private_plan(plan: HandoffPlan, path: Path) -> None:
    document = json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(
            os.fspath(path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as target:
            target.write(document)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(path, 0o600)
    except FileExistsError:
        raise HandoffError("handoff plan already exists") from None
    except OSError:
        raise HandoffError("cannot write private handoff plan") from None


def plan_handoff(adapter: HandoffAdapter, *, plan_path: Path | None = None) -> HandoffPlan:
    """Write a deterministic private plan without changing producer state."""
    snapshot = _snapshot(adapter)
    configured_path = plan_path if plan_path is not None else getattr(adapter, "plan_path", None)
    if configured_path is None:
        raise HandoffError("handoff adapter has no plan destination")
    destination = Path(configured_path)
    plan = _plan_for_snapshot(snapshot, destination)
    _write_private_plan(plan, destination)
    return plan


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_loaded_plan(data: Any, path: Path) -> HandoffPlan:
    if (not isinstance(data, dict) or set(data) != _PLAN_FIELDS or
            type(data.get("schema_version")) is not int or data["schema_version"] != PLAN_VERSION):
        raise HandoffError("invalid handoff plan")
    counts = ("operation_count", "completed_count", "pending_count", "unknown_outcome_count")
    if any(type(data.get(name)) is not int or data[name] < 0 for name in counts):
        raise HandoffError("invalid handoff plan counts")
    count = data["operation_count"]
    arrays = (
        "operation_key_sha256", "payload_sha256", "operation_kinds", "targets", "receipts", "preflight",
    )
    if any(not isinstance(data.get(name), list) or len(data[name]) != count for name in arrays):
        raise HandoffError("invalid handoff plan items")
    if not _is_digest(data.get("source_sha256")) or not _is_digest(data.get("backup_sha256")):
        raise HandoffError("invalid handoff plan digest")
    if any(not _is_digest(value) for value in data["operation_key_sha256"] + data["payload_sha256"]):
        raise HandoffError("invalid handoff plan digest")
    if any(not isinstance(value, str) or not value for value in data["operation_kinds"]):
        raise HandoffError("invalid handoff plan operation kind")
    targets: list[dict[str, str]] = []
    for target in data["targets"]:
        if (not isinstance(target, dict) or not target or
                any(not isinstance(key, str) or not isinstance(value, str) or not value.isdigit()
                    for key, value in target.items())):
            raise HandoffError("invalid handoff plan destination")
        targets.append(dict(target))
    completed = 0
    receipts: list[dict[str, str] | None] = []
    preflight: list[dict[str, Any] | None] = []
    for value in data["receipts"]:
        if value is None:
            receipts.append(None)
            continue
        if (not isinstance(value, dict) or not value or
                any(not isinstance(key, str) or not isinstance(item, str) or not item.isdigit()
                    for key, item in value.items())):
            raise HandoffError("invalid handoff plan receipt")
        completed += 1
        receipts.append(dict(value))
    for value in data["preflight"]:
        if value is None:
            preflight.append(None)
            continue
        try:
            normalized = validate_preflight(value)
        except ValidationError:
            raise HandoffError("invalid handoff plan preflight") from None
        preflight.append(normalized)
    pending = count - completed
    if (data["completed_count"] != completed or data["pending_count"] != pending or
            data["unknown_outcome_count"] != pending):
        raise HandoffError("inconsistent handoff plan counts")
    return HandoffPlan(
        source_sha256=data["source_sha256"],
        backup_sha256=data["backup_sha256"],
        operation_count=count,
        completed_count=completed,
        pending_count=pending,
        unknown_outcome_count=pending,
        operation_key_sha256=tuple(data["operation_key_sha256"]),
        payload_sha256=tuple(data["payload_sha256"]),
        operation_kinds=tuple(data["operation_kinds"]),
        targets=tuple(targets),
        receipts=tuple(receipts),
        preflight=tuple(preflight),
        plan_path=path,
    )


def read_handoff_plan(path: Path) -> HandoffPlan:
    """Load a mode-0600 plan while keeping its filesystem path out of JSON."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise ValueError("handoff plan is not a private regular file")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise HandoffError("cannot read private handoff plan") from None
    return _validate_loaded_plan(data, path)


def _backup_path(plan: HandoffPlan) -> Path:
    if plan.plan_path is None:
        raise HandoffError("handoff plan has no private file path")
    return Path(os.fspath(plan.plan_path) + ".source-backup")


def _ensure_private_backup(plan: HandoffPlan, snapshot: HandoffSnapshot) -> Path:
    path = _backup_path(plan)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if any(item.acknowledged for item in snapshot.items):
            raise HandoffError("acknowledged handoff has no source backup") from None
        if hash_source_bytes(snapshot.backup_bytes) != plan.backup_sha256:
            raise HandoffError("handoff backup source changed")
        write_private_backup(snapshot.backup_bytes, path)
        return path
    except OSError:
        raise HandoffError("cannot inspect private handoff backup") from None
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise HandoffError("existing handoff backup is not private")
    if hash_source_file(path) != plan.backup_sha256:
        raise HandoffError("existing handoff backup does not match plan")
    return path


def _verify_snapshot(plan: HandoffPlan, snapshot: HandoffSnapshot) -> None:
    current = _plan_for_snapshot(snapshot)
    if current.as_dict() == plan.as_dict():
        return
    original = plan.as_dict()
    recaptured = current.as_dict()
    original.pop("backup_sha256")
    recaptured.pop("backup_sha256")
    if any(item.acknowledged for item in snapshot.items) and recaptured == original:
        # Source owners may persist acknowledgments beside legacy records. The
        # stable source fingerprint and every operation must still match; the
        # original backup is checked separately before resuming.
        return
    raise HandoffError("handoff source state changed after planning")


def apply_handoff(
    plan: HandoffPlan | Path,
    adapter: HandoffAdapter,
    client: DeliveryClient,
) -> HandoffResult:
    """Import in source order and acknowledge each item after owner acceptance.

    The plan contains only digests and receipts. Applying always re-reads the
    adapter snapshot, checks the original hash, and obtains payloads/media from
    that adapter again. A failed acknowledgment is retried with the same
    operation key, relying on the owner's durable idempotency contract.
    """
    if isinstance(plan, Path):
        selected_plan = read_handoff_plan(plan)
    elif isinstance(plan, HandoffPlan):
        selected_plan = plan
    else:
        raise HandoffError("invalid handoff plan")
    if selected_plan.plan_path is None:
        raise HandoffError("handoff plan has no private file path")
    snapshot = _snapshot(adapter)
    _verify_snapshot(selected_plan, snapshot)
    backup_path = _ensure_private_backup(selected_plan, snapshot)
    acknowledged = 0
    skipped = 0
    for item in snapshot.items:
        if item.acknowledged:
            skipped += 1
            continue
        try:
            accepted = import_handoff_item(
                client,
                item.operation,
                receipt=item.receipt,
                preflight=item.preflight,
                acknowledge=adapter.acknowledge,
            )
        except HandoffError:
            raise
        except Exception:
            raise HandoffError("cannot record source handoff acknowledgment") from None
        acknowledged += 1
    return HandoffResult(acknowledged, skipped, backup_path)


def import_handoff_item(
    client: DeliveryClient,
    operation: OperationIntent,
    *,
    receipt: Mapping[str, str] | None,
    preflight: Mapping[str, Any] | None = None,
    acknowledge: Callable[[OperationReceipt], None],
) -> OperationReceipt:
    """Import one item and acknowledge its source only after durable acceptance."""
    try:
        if receipt is not None:
            if preflight is not None:
                raise HandoffError("completed handoff item cannot carry preflight metadata")
            accepted = client.adopt_completed(operation, receipt)
            if accepted.receipt != dict(receipt):
                raise HandoffError("delivery service receipt did not match handoff item")
        else:
            validated = validate_preflight(preflight, str(operation.kind))
            accepted = client.adopt_pending(operation, preflight=validated)
    except HandoffError:
        raise
    except (DeliveryClientError, ValidationError, TypeError):
        raise HandoffError("delivery service did not acknowledge handoff item") from None
    if not isinstance(accepted, OperationReceipt):
        raise HandoffError("delivery service returned an invalid handoff acknowledgment")
    if accepted.key != operation.key or accepted.digest != operation.digest:
        raise HandoffError("delivery service acknowledgment did not match handoff item")
    try:
        acknowledge(accepted)
    except Exception:
        raise HandoffError("cannot record source handoff acknowledgment") from None
    return accepted
