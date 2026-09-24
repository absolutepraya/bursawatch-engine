"""Single-owner durable delivery worker and bounded create reconciliation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from .discord_gateway import DiscordGateway, GatewayError, StoredAttachment
from .models import OperationIntent, OperationRecord
from .store import DeliveryStore, OperationStateConflict

MAX_READ_PAGES = 3
READ_PAGE_SIZE = 100


@dataclass(frozen=True)
class WorkerResult:
    status: str
    key: str | None = None


@dataclass(frozen=True)
class ReconcileResult:
    status: str
    receipt: dict[str, str] | None = None
    error_category: str | None = None
    retry_after: float | None = None


class DeliveryWorker:
    def __init__(self, store: DeliveryStore, gateway: DiscordGateway,
                 alert: Callable[[str, str], None] | None = None):
        self.store = store
        self.gateway = gateway
        self.alert = alert or (lambda key, category: logging.warning(
            "discord delivery alert operation=%s category=%s", key, category))

    @staticmethod
    def _timestamp(when: datetime) -> str:
        if when.tzinfo is None:
            raise ValueError("worker time must be timezone aware")
        return when.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _retry(self, record: OperationRecord, now: datetime, category: str,
               delay: float | None = None) -> WorkerResult:
        seconds = delay if delay is not None else min(2 ** min(record.attempt_count, 9), 300)
        self.store.finish(record.key, "retrying", error_category=category,
                          next_attempt_at=self._timestamp(now + timedelta(seconds=seconds)))
        return WorkerResult("retrying", record.key)

    def _defer_reconciliation(self, record: OperationRecord, now: datetime,
                              category: str, delay: float | None = None) -> WorkerResult:
        seconds = delay if delay is not None else min(2 ** min(record.attempt_count, 9), 300)
        self.store.finish(record.key, "pending_reconciliation", error_category=category,
                          next_attempt_at=self._timestamp(now + timedelta(seconds=seconds)))
        return WorkerResult("pending_reconciliation", record.key)

    def _after_proven_absence(self, record: OperationRecord, now: datetime) -> WorkerResult:
        snapshot = self.store.create_snapshot(record.key)
        if not snapshot.get("absence_backoff_done"):
            snapshot["absence_backoff_done"] = True
            self.store.save_create_snapshot(record.key, snapshot)
        return self._defer_reconciliation(record, now, "create_absent")

    def _ambiguous(self, record: OperationRecord, category: str) -> WorkerResult:
        self.store.finish(record.key, "ambiguous", error_category=category)
        self.alert(record.key, category)
        return WorkerResult("ambiguous", record.key)

    def _set_reconciliation_required(self, record: OperationRecord, required: bool) -> None:
        snapshot = self.store.create_snapshot(record.key)
        if snapshot.get("reconciliation_required", False) != required:
            snapshot["reconciliation_required"] = required
            self.store.save_create_snapshot(record.key, snapshot)

    def _handle_reconcile_error(self, record: OperationRecord, now: datetime,
                                result: ReconcileResult) -> WorkerResult:
        if result.error_category in {"permission", "destination_missing"}:
            self.store.finish(record.key, "blocked", error_category=result.error_category)
            self.alert(record.key, "blocked")
            return WorkerResult("blocked", record.key)
        return self._defer_reconciliation(record, now, result.error_category or "readback_unavailable",
                                          result.retry_after)

    def _snapshot(self, record: OperationRecord, intent: OperationIntent) -> dict:
        """Save exact request and read boundary before any Discord create."""
        existing = self.store.create_snapshot(record.key)
        if "request" in existing:
            return existing
        method, path, body = self.gateway.request_spec(intent)
        target = intent.target
        boundary = None
        if intent.kind in {"channel_message_create", "thread_message_create"}:
            channel = target.get("channel_id", target.get("thread_id"))
            read = self.gateway.query({"kind": "channel_messages", "channel_id": channel, "limit": 1})
            if not isinstance(read, list) or len(read) > 1:
                raise GatewayError("invalid_response")
            if read:
                boundary = read[0].get("id")
                if not isinstance(boundary, str) or not boundary.isdigit():
                    raise GatewayError("invalid_response")
        elif intent.kind == "forum_thread_create":
            read = self.gateway.query({"kind": "forum_threads", "channel_id": target["forum_id"], "limit": READ_PAGE_SIZE})
            threads = read.get("threads") if isinstance(read, dict) else read
            if not isinstance(threads, list):
                raise GatewayError("invalid_response")
            if threads:
                ids = [item.get("id") for item in threads if isinstance(item, dict)]
                if len(ids) != len(threads) or any(not isinstance(value, str) or not value.isdigit() for value in ids):
                    raise GatewayError("invalid_response")
                boundary = str(max(int(value) for value in ids))
        metadata = self.store.stored_attachments(record.key)
        exact_body = dict(body)
        if metadata:
            attachment_body = [{"id": index, "filename": item["filename"]}
                               for index, item in enumerate(metadata)]
            if "message" in exact_body:
                exact_body["message"] = {**exact_body["message"], "attachments": attachment_body}
            else:
                exact_body["attachments"] = attachment_body
        snapshot = {"reconcile_before_first_create": intent.reconcile_before_first_create,
                    "legacy_nonce": intent.legacy_nonce, "boundary_observed": True,
                    "request": {"method": method, "path": path, "body": exact_body},
                    "attachments": [{"filename": item["filename"], "mime_type": item["mime_type"],
                                     "sha256": item["sha256"]} for item in metadata],
                    "boundary": boundary, "target": dict(target), "digest": record.digest}
        self.store.save_create_snapshot(record.key, snapshot)
        return snapshot

    def _matches_message(self, item: object, snapshot: dict) -> bool:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].isdigit():
            return False
        body = snapshot["request"]["body"]
        if item.get("content") != body.get("content"):
            return False
        nonce = item.get("nonce")
        if nonce is None or str(nonce) != snapshot.get("match_nonce", body.get("nonce")):
            return False
        attachments = snapshot.get("attachments", [])
        found = item.get("attachments", [])
        return (isinstance(found, list) and
                [value.get("filename") for value in found if isinstance(value, dict)] ==
                [value["filename"] for value in attachments])

    def reconcile(self, operation: OperationRecord) -> ReconcileResult:
        if not operation.kind.endswith("_create"):
            return ReconcileResult("inconclusive")
        snapshot = self.store.create_snapshot(operation.key)
        try:
            intent = self.store.load_intent(operation.key)
        except (OperationStateConflict, OSError):
            return ReconcileResult("inconclusive")
        if "request" not in snapshot:
            method, path, body = self.gateway.request_spec(intent)
            snapshot = {
                **snapshot,
                "request": {"method": method, "path": path, "body": body},
                "attachments": [{key: item[key] for key in ("filename", "mime_type", "sha256")}
                                for item in self.store.stored_attachments(operation.key)],
                "target": dict(intent.target),
                "boundary": snapshot.get("boundary"),
                "boundary_observed": snapshot.get("boundary_observed", False),
                "match_nonce": intent.legacy_nonce or body.get("nonce"),
            }
        try:
            if operation.kind == "forum_thread_create":
                return self._reconcile_forum(intent, snapshot)
            if operation.kind == "forum_channel_create":
                # Discord has no safe guild channel history boundary for this create.
                return ReconcileResult("inconclusive")
            channel = intent.target.get("channel_id", intent.target.get("thread_id"))
            boundary = snapshot.get("boundary")
            boundary_observed = snapshot.get("boundary_observed", False)
            cursor = None
            matches: list[dict] = []
            unresolved_candidate = False
            for _ in range(MAX_READ_PAGES):
                query = {"kind": "channel_messages", "channel_id": channel, "limit": READ_PAGE_SIZE}
                if cursor is not None:
                    query["before"] = cursor
                result = self.gateway.query(query)
                if not isinstance(result, list) or len(result) > READ_PAGE_SIZE:
                    return ReconcileResult("inconclusive")
                ids = [item.get("id") for item in result if isinstance(item, dict)]
                if len(ids) != len(result) or any(not isinstance(value, str) or not value.isdigit() for value in ids):
                    return ReconcileResult("inconclusive")
                in_scope = [item for item in result if boundary is None or int(item["id"]) > int(boundary)]
                reached_boundary = boundary is not None and len(in_scope) < len(result)
                for item in in_scope:
                    if self._matches_message(item, snapshot):
                        matches.append(item)
                    elif (isinstance(item, dict) and item.get("content") == snapshot["request"]["body"].get("content")
                          and item.get("nonce") is None):
                        unresolved_candidate = True
                if len(matches) > 1:
                    return ReconcileResult("inconclusive")
                if reached_boundary or len(result) < READ_PAGE_SIZE:
                    if unresolved_candidate:
                        return ReconcileResult("inconclusive")
                    if matches:
                        return ReconcileResult("matched", {"message_id": matches[0]["id"]})
                    return ReconcileResult("not_found" if boundary_observed else "inconclusive")
                next_cursor = str(min(int(value) for value in ids))
                if cursor == next_cursor:
                    return ReconcileResult("inconclusive")
                cursor = next_cursor
            return ReconcileResult("inconclusive")
        except GatewayError as exc:
            if exc.category in {"rate_limited", "network", "timeout", "discord_unavailable",
                                "permission", "destination_missing"}:
                return ReconcileResult("inconclusive", error_category=exc.category, retry_after=exc.retry_after)
            return ReconcileResult("inconclusive")

    def _reconcile_forum(self, intent: OperationIntent, snapshot: dict) -> ReconcileResult:
        result = self.gateway.query({"kind": "forum_threads", "channel_id": intent.target["forum_id"],
                                     "limit": READ_PAGE_SIZE})
        threads = result.get("threads") if isinstance(result, dict) else result
        has_more = result.get("has_more", True) if isinstance(result, dict) else True
        if not isinstance(threads, list):
            return ReconcileResult("inconclusive")
        body = snapshot["request"]["body"]
        matches = []
        boundary = snapshot.get("boundary")
        for thread in threads:
            if not isinstance(thread, dict) or thread.get("parent_id") != intent.target["forum_id"] or thread.get("name") != body.get("name"):
                continue
            thread_id = thread.get("id")
            if not isinstance(thread_id, str) or not thread_id.isdigit():
                continue
            if boundary is not None and int(thread_id) <= int(boundary):
                continue
            starter = self.gateway.query({"kind": "thread_message_read", "thread_id": thread_id,
                                          "message_id": thread_id})
            if not isinstance(starter, dict) or starter.get("id") != thread_id:
                return ReconcileResult("inconclusive")
            wanted = [item["filename"] for item in snapshot.get("attachments", [])]
            found = starter.get("attachments", [])
            if starter.get("content") == body["message"].get("content") and (
                    isinstance(found, list) and
                    [item.get("filename") for item in found if isinstance(item, dict)] == wanted):
                matches.append({"thread_id": thread_id, "message_id": starter["id"]})
        if len(matches) == 1 and not has_more and snapshot.get("boundary_observed", False):
            return ReconcileResult("matched", matches[0])
        if len(matches) == 0 and not has_more and snapshot.get("boundary_observed", False):
            return ReconcileResult("not_found")
        return ReconcileResult("inconclusive")

    def _attachments(self, key: str) -> list[StoredAttachment]:
        return [StoredAttachment(item["filename"], item["mime_type"],
                                 self.store.media_root / item["relative_path"], item["sha256"])
                for item in self.store.stored_attachments(key)]

    def _process(self, record: OperationRecord, now: datetime, reconciling: bool) -> WorkerResult:
        sent = False
        try:
            intent = self.store.load_intent(record.key)
            if reconciling:
                self._set_reconciliation_required(record, True)
                result = self.reconcile(record)
                if result.status == "matched":
                    self.store.finish(record.key, "delivered", receipt=result.receipt)
                    return WorkerResult("delivered", record.key)
                if result.error_category:
                    return self._handle_reconcile_error(record, now, result)
                if result.status == "inconclusive":
                    return self._ambiguous(record, "reconciliation_inconclusive")
                snapshot = self.store.create_snapshot(record.key)
                if not snapshot.get("absence_backoff_done"):
                    return self._after_proven_absence(record, now)
            if intent.kind.endswith("_create"):
                self._snapshot(record, intent)
                snapshot = self.store.create_snapshot(record.key)
                if snapshot.get("absence_backoff_done") or snapshot.get("reconciliation_required"):
                    snapshot["absence_backoff_done"] = False
                    snapshot["reconciliation_required"] = False
                    self.store.save_create_snapshot(record.key, snapshot)
            sent = True
            receipt = self.gateway.execute(intent, self._attachments(record.key))
            self.store.finish(record.key, "delivered", receipt=receipt)
            return WorkerResult("delivered", record.key)
        except GatewayError as exc:
            if (sent and record.kind.endswith("_create") and
                    exc.category in {"timeout", "network", "discord_unavailable", "invalid_response"}):
                self._set_reconciliation_required(record, True)
                result = self.reconcile(record)
                if result.status == "matched":
                    self.store.finish(record.key, "delivered", receipt=result.receipt)
                    return WorkerResult("delivered", record.key)
                if result.error_category:
                    return self._handle_reconcile_error(record, now, result)
                if result.status == "not_found":
                    return self._after_proven_absence(record, now)
                return self._ambiguous(record, "create_outcome_unknown")
            if exc.category in {"rate_limited", "network", "timeout", "discord_unavailable"}:
                return self._retry(record, now, exc.category, exc.retry_after)
            status = "blocked" if exc.category in {"permission", "destination_missing"} else "rejected"
            self.store.finish(record.key, status, error_category=exc.category)
            if status == "blocked":
                self.alert(record.key, "blocked")
            return WorkerResult(status, record.key)
        except (OSError, OperationStateConflict):
            self.store.finish(record.key, "blocked", error_category="local_state_invalid")
            self.alert(record.key, "blocked")
            return WorkerResult("blocked", record.key)

    def run_once(self, now: datetime) -> WorkerResult:
        with self.store.worker_lock():
            self.store.recover_interrupted()
            record = self.store.claim_reconciliation(self._timestamp(now))
            reconciling = record is not None
            if record is None:
                record = self.store.claim_next(self._timestamp(now))
            if record is None:
                return WorkerResult("idle")
            return self._process(record, now, reconciling)
