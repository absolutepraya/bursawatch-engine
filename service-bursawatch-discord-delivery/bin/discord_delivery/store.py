"""SQLite operation ledger and private, service-owned attachment staging."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterator, Mapping

from .models import (
    Attachment,
    OperationIntent,
    OperationRecord,
    ValidationError,
    validate_preflight,
    validate_receipt,
    DIGEST,
    parse_attempt_deadline,
    serialize_attempt_deadline,
)


class OperationKeyConflict(ValueError):
    pass


class OperationStateConflict(ValueError):
    pass


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("state directory may not be a symlink")
    os.chmod(path, 0o700)


class DeliveryStore:
    def __init__(self, database_path: Path, media_root: Path):
        self.database_path = Path(database_path)
        self.media_root = Path(media_root)
        _private_dir(self.database_path.parent)
        _private_dir(self.media_root)
        if self.database_path.is_symlink():
            raise ValueError("database may not be a symlink")
        fd = os.open(self.database_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.database_path, 0o600)
        self.db = sqlite3.connect(self.database_path, isolation_level=None, timeout=30, check_same_thread=False)
        self._write_lock = threading.RLock()
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS discord_operations (
                id TEXT PRIMARY KEY,
                operation_key TEXT NOT NULL UNIQUE,
                payload_digest TEXT NOT NULL,
                kind TEXT NOT NULL,
                ordering_key TEXT NOT NULL,
                target_json TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                attachments_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN
                    ('pending','pending_reconciliation','retrying','delivering','delivered','rejected','blocked','ambiguous')),
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                error_category TEXT,
                receipt_json TEXT,
                create_recovery_json TEXT,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE INDEX IF NOT EXISTS discord_operations_order ON discord_operations(ordering_key, created_at);
            CREATE INDEX IF NOT EXISTS discord_operations_status ON discord_operations(status, created_at);
        """)
        # Additive migration preserves old rows, status CHECK, receipts and media.
        # Serialize schema checks with other openers so repeated startup is safe.
        with self._transaction():
            columns = {row["name"] for row in self.db.execute("PRAGMA table_info(discord_operations)")}
            if "attempt_deadline" not in columns:
                self.db.execute("ALTER TABLE discord_operations ADD COLUMN attempt_deadline TEXT")
            if "uncertain_attempt" not in columns:
                self.db.execute("ALTER TABLE discord_operations ADD COLUMN uncertain_attempt INTEGER NOT NULL DEFAULT 0")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(self.database_path) + suffix)
            if sidecar.exists():
                os.chmod(sidecar, 0o600)

    @contextlib.contextmanager
    def worker_lock(self) -> Iterator[None]:
        """Only one delivery worker may hold this advisory lock at a time."""
        lock_path = self.database_path.parent / "discord-delivery-worker.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.chmod(lock_path, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @contextlib.contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._write_lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            else:
                self.db.execute("COMMIT")

    def _record(self, row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(
            id=row["id"], key=row["operation_key"], digest=row["payload_digest"],
            kind=row["kind"], ordering_key=row["ordering_key"],
            target=json.loads(row["target_json"]), status=row["status"],
            receipt=json.loads(row["receipt_json"]) if row["receipt_json"] else None,
            attempt_count=row["attempt_count"], error_category=row["error_category"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            attempt_deadline=parse_attempt_deadline(row["attempt_deadline"]),
            uncertain_attempt=bool(row["uncertain_attempt"]),
        )

    def get_by_key(self, key: str) -> OperationRecord | None:
        row = self.db.execute("SELECT * FROM discord_operations WHERE operation_key=?", (key,)).fetchone()
        return self._record(row) if row else None

    def load_intent(self, key: str) -> OperationIntent:
        row = self.db.execute("SELECT * FROM discord_operations WHERE operation_key=?", (key,)).fetchone()
        if row is None:
            raise OperationStateConflict("operation not found")
        attachments = []
        for item in json.loads(row["attachments_json"]):
            path = self.media_root / item["relative_path"]
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise OperationStateConflict("staged attachment changed")
            attachments.append(Attachment(item["filename"], item["mime_type"], data))
        recovery = json.loads(row["create_recovery_json"] or "{}")
        intent = OperationIntent(row["operation_key"], row["kind"], row["ordering_key"],
                                 json.loads(row["target_json"]), json.loads(row["payload_json"]),
                                 tuple(attachments), recovery.get("reconcile_before_first_create", False),
                                 recovery.get("legacy_nonce"), parse_attempt_deadline(row["attempt_deadline"]))
        if intent.digest != row["payload_digest"]:
            raise OperationStateConflict("stored operation changed")
        return intent

    def stored_attachments(self, key: str) -> list[dict[str, str]]:
        row = self.db.execute("SELECT attachments_json FROM discord_operations WHERE operation_key=?", (key,)).fetchone()
        if row is None:
            raise OperationStateConflict("operation not found")
        return json.loads(row[0])

    def create_snapshot(self, key: str) -> dict[str, Any]:
        row = self.db.execute("SELECT create_recovery_json FROM discord_operations WHERE operation_key=?", (key,)).fetchone()
        if row is None:
            raise OperationStateConflict("operation not found")
        return json.loads(row[0] or "{}")

    def save_create_snapshot(self, key: str, snapshot: Mapping[str, Any]) -> None:
        with self._transaction():
            current = self.get_by_key(key)
            if current is None or current.status != "delivering" or not current.kind.endswith("_create"):
                raise OperationStateConflict("operation is not a claimed create")
            self.db.execute("UPDATE discord_operations SET create_recovery_json=? WHERE operation_key=?",
                            (json.dumps(snapshot, sort_keys=True), key))

    def set_uncertain_attempt(self, key: str, uncertain: bool) -> None:
        """Retain uncertainty independently of retries and create snapshots."""
        with self._transaction():
            current = self.get_by_key(key)
            if current is None or current.status != "delivering":
                raise OperationStateConflict("operation is not delivering")
            self.db.execute("UPDATE discord_operations SET uncertain_attempt=? WHERE operation_key=?",
                            (int(uncertain), key))

    def _stage(self, operation_id: str, intent: OperationIntent) -> list[dict[str, str]]:
        metadata = []
        created = []
        try:
            for index, attachment in enumerate(intent.attachments):
                relative = f"{operation_id}/{index:02d}-{attachment.filename}"
                destination = self.media_root / relative
                _private_dir(destination.parent)
                temporary = destination.with_name(destination.name + ".tmp-" + uuid.uuid4().hex)
                fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(attachment.data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, destination)
                    created.append(destination)
                finally:
                    temporary.unlink(missing_ok=True)
                metadata.append({"filename": attachment.filename, "mime_type": attachment.mime_type,
                                 "sha256": hashlib.sha256(attachment.data).hexdigest(),
                                 "relative_path": relative})
            if metadata:
                dir_fd = os.open(self.media_root / operation_id, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        return metadata

    def _insert(
        self,
        intent: OperationIntent,
        status: str,
        receipt: Mapping[str, str] | None = None,
        recovery_metadata: Mapping[str, Any] | None = None,
    ) -> OperationRecord:
        with self._transaction():
            existing = self.get_by_key(intent.key)
            if existing:
                if existing.digest != intent.digest:
                    raise OperationKeyConflict("operation key already has a different payload")
                if receipt is not None and (existing.status != "delivered" or existing.receipt != dict(receipt)):
                    raise OperationStateConflict("existing completed receipt differs")
                if recovery_metadata is not None and existing.status in {"pending_reconciliation", "ambiguous"}:
                    current = self.create_snapshot(intent.key)
                    current_hint = (validate_preflight({
                        "boundary_observed": current.get("boundary_observed"),
                        "boundary": current.get("boundary"),
                    }, str(intent.kind)) if current.get("boundary_observed") is True else None)
                    incoming_hint = validate_preflight({
                        "boundary_observed": recovery_metadata.get("boundary_observed"),
                        "boundary": recovery_metadata.get("boundary"),
                    }, str(intent.kind))
                    if current_hint != incoming_hint:
                        raise OperationStateConflict("existing preflight boundary differs")
                return existing
            operation_id = uuid.uuid4().hex
            staged = self._stage(operation_id, intent)
            recovery = {
                "reconcile_before_first_create": intent.reconcile_before_first_create,
                "legacy_nonce": intent.legacy_nonce,
            }
            if recovery_metadata is not None:
                recovery.update(recovery_metadata)
            try:
                self.db.execute("""INSERT INTO discord_operations
                    (id,operation_key,payload_digest,kind,ordering_key,target_json,payload_json,
                     attachments_json,status,receipt_json,create_recovery_json,attempt_deadline)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    operation_id, intent.key, intent.digest, intent.kind, intent.ordering_key,
                    json.dumps(intent.target, sort_keys=True), json.dumps(intent.payload, sort_keys=True),
                    json.dumps(staged, sort_keys=True), status,
                    json.dumps(receipt, sort_keys=True) if receipt else None,
                    json.dumps(recovery, sort_keys=True),
                    serialize_attempt_deadline(intent.attempt_deadline) if intent.attempt_deadline is not None else None,
                ))
            except BaseException:
                for attachment in staged:
                    (self.media_root / attachment["relative_path"]).unlink(missing_ok=True)
                raise
            return self.get_by_key(intent.key)

    def accept(self, intent: OperationIntent) -> OperationRecord:
        return self._insert(intent, "pending_reconciliation" if intent.reconcile_before_first_create else "pending")

    def adopt_completed(self, intent: OperationIntent, receipt: Mapping[str, str]) -> OperationRecord:
        return self._insert(intent, "delivered", validate_receipt(receipt, intent.kind, intent.target))

    def adopt_pending(
        self,
        intent: OperationIntent,
        *,
        preflight: Mapping[str, Any] | None = None,
    ) -> OperationRecord:
        if not intent.reconcile_before_first_create:
            raise ValidationError("pending imports require reconciliation")
        validated = validate_preflight(preflight, str(intent.kind))
        return self._insert(intent, "pending_reconciliation", recovery_metadata=validated)

    def retry_blocked(self, operation_key: str, expected_digest: str) -> OperationRecord:
        if not isinstance(expected_digest, str) or not DIGEST.fullmatch(expected_digest):
            raise ValidationError("invalid expected digest")
        with self._transaction():
            existing = self.get_by_key(operation_key)
            if not existing or existing.digest != expected_digest or existing.status != "blocked":
                raise OperationStateConflict("blocked operation and digest must match")
            recovery = self.create_snapshot(operation_key)
            status = ("pending_reconciliation" if existing.kind.endswith("_create") and
                      (recovery.get("reconciliation_required") or existing.uncertain_attempt) else "retrying")
            self.db.execute("""UPDATE discord_operations SET status=?, error_category=NULL,
                next_attempt_at=NULL, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE operation_key=?""", (status, operation_key))
            return self.get_by_key(operation_key)

    def list_summaries(self, limit: int = 50, offset: int = 0) -> list[OperationRecord]:
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValidationError("invalid pagination")
        return [self._record(row) for row in self.db.execute(
            "SELECT * FROM discord_operations ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (limit, offset))]

    def counts(self) -> dict[str, int]:
        values = dict(self.db.execute("SELECT status,count(*) FROM discord_operations GROUP BY status").fetchall())
        return {"pending": sum(values.get(s, 0) for s in ("pending", "pending_reconciliation", "retrying", "delivering")),
                "blocked": values.get("blocked", 0), "ambiguous": values.get("ambiguous", 0)}

    def recover_interrupted(self) -> dict[str, int]:
        """Call at worker startup, under worker_lock, before claim_next.

        An interrupted create may have reached Discord without a receipt. It must
        be read back and reconciled before another create can be sent. Other
        mutation kinds re-enter the retry queue, but deadline-bound mutations
        retain uncertainty so expiry cannot incorrectly imply a safe rejection.
        """
        with self._transaction():
            creates = self.db.execute("""UPDATE discord_operations
                SET status='pending_reconciliation', next_attempt_at=NULL,
                    uncertain_attempt=CASE WHEN attempt_deadline IS NOT NULL THEN 1 ELSE uncertain_attempt END,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE status='delivering' AND kind LIKE '%_create'""").rowcount
            mutations = self.db.execute("""UPDATE discord_operations
                SET status='pending', next_attempt_at=NULL,
                    uncertain_attempt=CASE WHEN attempt_deadline IS NOT NULL THEN 1 ELSE uncertain_attempt END,
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE status='delivering' AND kind NOT LIKE '%_create'""").rowcount
            return {"pending_reconciliation": creates, "pending": mutations}

    def claim_next(self, now: str | None = None) -> OperationRecord | None:
        """Claim the earliest ready operation whose ordering chain is unblocked."""
        with self._transaction():
            row = self.db.execute("""SELECT d.* FROM discord_operations d WHERE d.status IN ('pending','retrying')
                AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?)
                AND NOT EXISTS (SELECT 1 FROM discord_operations earlier WHERE earlier.ordering_key=d.ordering_key
                    AND (earlier.created_at<d.created_at OR (earlier.created_at=d.created_at AND earlier.rowid<d.rowid))
                    AND earlier.status NOT IN ('delivered','rejected'))
                ORDER BY d.created_at,d.rowid LIMIT 1""", (now or self.db.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0],)).fetchone()
            if not row:
                return None
            self.db.execute("""UPDATE discord_operations SET status='delivering',attempt_count=attempt_count+1,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""", (row["id"],))
            return self.get_by_key(row["operation_key"])

    def claim_reconciliation(self, now: str | None = None) -> OperationRecord | None:
        with self._transaction():
            row = self.db.execute("""SELECT d.* FROM discord_operations d
                WHERE d.status='pending_reconciliation'
                AND (d.next_attempt_at IS NULL OR d.next_attempt_at <= ?)
                AND NOT EXISTS (SELECT 1 FROM discord_operations earlier WHERE earlier.ordering_key=d.ordering_key
                    AND (earlier.created_at<d.created_at OR (earlier.created_at=d.created_at AND earlier.rowid<d.rowid))
                    AND earlier.status NOT IN ('delivered','rejected'))
                ORDER BY d.created_at,d.rowid LIMIT 1""", (now or self.db.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now')").fetchone()[0],)).fetchone()
            if row is None:
                return None
            self.db.execute("""UPDATE discord_operations SET status='delivering',attempt_count=attempt_count+1,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?""", (row["id"],))
            return self.get_by_key(row["operation_key"])

    def finish(self, operation_key: str, status: str, *, receipt: Mapping[str, str] | None = None,
               error_category: str | None = None, create_recovery: Mapping[str, str] | None = None,
               next_attempt_at: str | None = None) -> OperationRecord:
        if status not in {"pending", "pending_reconciliation", "retrying", "delivered", "rejected", "blocked", "ambiguous"}:
            raise ValidationError("invalid completion status")
        if error_category is not None and (not isinstance(error_category, str) or not error_category.isidentifier() or len(error_category) > 64):
            raise ValidationError("invalid error category")
        with self._transaction():
            current = self.get_by_key(operation_key)
            if current is None or current.status != "delivering":
                raise OperationStateConflict("operation is not delivering")
            if status == "delivered":
                receipt = validate_receipt(receipt, current.kind, current.target)
            self.db.execute("""UPDATE discord_operations SET status=?,receipt_json=?,error_category=?,
                create_recovery_json=COALESCE(?,create_recovery_json),next_attempt_at=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
                WHERE operation_key=? AND status='delivering'""", (
                status, json.dumps(receipt) if receipt else None, error_category,
                json.dumps(create_recovery) if create_recovery else None, next_attempt_at, operation_key))
            if self.db.execute("SELECT changes()").fetchone()[0] != 1:
                raise OperationStateConflict("operation is not delivering")
            return self.get_by_key(operation_key)
