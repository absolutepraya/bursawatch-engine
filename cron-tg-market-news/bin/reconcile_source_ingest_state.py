"""Preview and apply a validated merge of source-ingest Market News state."""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any

import delivery as market_delivery
import state as owner_state
from news_source_work import candidate_keys, provenance


PLAN_VERSION = 2
RECEIPT_KEY = owner_state._SOURCE_INGEST_RECONCILIATION_KEY
_PLAN_FIELDS = frozenset(
    {
        "version",
        "source_state_path",
        "canonical_state_path",
        "source_state_sha256",
        "canonical_state_sha256",
        "delivery_resolution_sha256",
        "source_candidate_count",
        "source_provenance_count",
        "new_candidate_count",
        "overlap_count",
        "phase_difference_count",
        "provenance_added_count",
        "source_status_event_count",
        "new_status_event_count",
        "overlap_status_event_count",
        "status_event_phase_difference_count",
        "status_event_provenance_added_count",
        "canonical_pending_delivery_count",
        "canonical_pending_delivery_confirmed_count",
        "canonical_pending_delivery_not_found_count",
        "active_candidate_abandonment_count",
        "created_at",
        "plan_sha256",
    }
)
_REPORT_FIELDS = (
    "source_candidate_count",
    "source_provenance_count",
    "new_candidate_count",
    "overlap_count",
    "phase_difference_count",
    "provenance_added_count",
    "source_status_event_count",
    "new_status_event_count",
    "overlap_status_event_count",
    "status_event_phase_difference_count",
    "status_event_provenance_added_count",
    "canonical_pending_delivery_count",
    "canonical_pending_delivery_confirmed_count",
    "canonical_pending_delivery_not_found_count",
    "active_candidate_abandonment_count",
)
_FORWARD_ONLY_ABANDON_REASON = (
    "pre-cutover Market News work intentionally skipped at the forward-only source-ingest boundary"
)
_IMMUTABLE_PROVENANCE_FIELDS = (
    "candidate_key",
    "event_key",
    "version",
    "content_hash",
    "source_url",
    "enabled_capabilities",
    "work_keys",
)
_STATUS_EVENT_IDENTITY_FIELDS = (
    "source_message_id",
    "source_url",
    "effective_date",
    "uma",
    "suspend_in",
    "suspend_out",
    "fca_in",
    "fca_out",
    "channel_id",
    "content",
)
_STATUS_EVENT_PROVENANCE_FIELDS = ("source_event_key", "config_revision")
_SOURCE_STATS_FIELDS = frozenset(
    {"immediate_delivery_contract_v1", "news_source_work", "stock_status_events"}
)
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _absolute_path(path: str | os.PathLike[str]) -> Path:
    expanded = Path(path).expanduser()
    return Path(os.path.abspath(expanded))


def _state_file(path: str | os.PathLike[str], label: str) -> tuple[Path, bytes, dict[str, Any]]:
    supplied = Path(path).expanduser()
    try:
        metadata = supplied.lstat()
    except OSError as error:
        raise owner_state.StateBlockedError(f"{label} is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise owner_state.StateBlockedError(f"{label} must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise owner_state.StateBlockedError(f"{label} permissions must be 0600")
    resolved = supplied.resolve(strict=True)
    try:
        raw = resolved.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            parse_constant=owner_state._reject_nonfinite_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise owner_state.StateBlockedError(f"{label} is not valid owner state JSON") from error
    owner_state._validate_state(value)
    if not isinstance(value, dict):
        raise owner_state.StateBlockedError(f"{label} must contain an object")
    return resolved, raw, value


def _plan_path(path: str | os.PathLike[str], source: Path, canonical: Path) -> Path:
    plan = _absolute_path(path)
    source_root = source.parent.resolve(strict=True)
    canonical_root = canonical.parent.resolve(strict=True)
    resolved_plan = plan.resolve(strict=False)
    if any(
        candidate.is_relative_to(root)
        for candidate in (plan, resolved_plan)
        for root in (source_root, canonical_root)
    ):
        raise owner_state.StateBlockedError("plan file must be outside both state directories")
    try:
        metadata = plan.lstat()
    except FileNotFoundError:
        return plan
    except OSError as error:
        raise owner_state.StateBlockedError("plan file cannot be inspected") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise owner_state.StateBlockedError("plan file must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise owner_state.StateBlockedError("plan file permissions must be 0600")
    return plan


def _validate_source_candidates(source: dict[str, Any]) -> tuple[set[str], dict[str, Any]]:
    candidate_map = source.get("candidates")
    stats = source.get("stats")
    origins = stats.get("news_source_work") if isinstance(stats, dict) else None
    if not isinstance(candidate_map, dict) or not isinstance(origins, dict) or not origins:
        raise owner_state.StateBlockedError("source state has no News source-work candidates")
    source_keys = candidate_keys(source)
    if source_keys != set(candidate_map) or source_keys != set(origins):
        raise owner_state.StateBlockedError(
            "every source candidate must have exactly one valid source-work provenance record"
        )
    validated: dict[str, Any] = {}
    for key in source_keys:
        origin = provenance(source, key)
        if origin is None:
            raise owner_state.StateBlockedError("source candidate provenance is missing")
        validated[key] = origin
    return source_keys, validated


def _validate_source_state_scope(source: dict[str, Any]) -> dict[str, Any]:
    stats = source["stats"]
    assert isinstance(stats, dict)
    if set(stats) - _SOURCE_STATS_FIELDS:
        raise owner_state.StateBlockedError(
            "source state has owner ledgers outside the approved candidate and status merge"
        )
    marker = stats.get("immediate_delivery_contract_v1")
    if (
        not isinstance(marker, dict)
        or set(marker) != {"complete"}
        or marker.get("complete") is not True
    ):
        raise owner_state.StateBlockedError(
            "source immediate-delivery migration marker is not the expected completed default"
        )
    if source["dedupe"] or source["digest_windows"]:
        raise owner_state.StateBlockedError(
            "source state has dedupe or digest history outside the approved merge"
        )
    if source["providers"] != owner_state.empty_state()["providers"]:
        raise owner_state.StateBlockedError(
            "source state has provider cursor data outside the approved merge"
        )
    if any(
        source[field] is not None
        for field in ("last_poll_success", "last_delivery_success", "last_heartbeat_hour", "last_error_notice")
    ):
        raise owner_state.StateBlockedError(
            "source state has top-level runtime history outside the approved merge"
        )
    canonical_events = stats.get("stock_status_events", {})
    if not isinstance(canonical_events, dict):
        raise owner_state.StateBlockedError("source stock-status event ledger is malformed")
    return canonical_events


def _validate_canonical_migration_marker(canonical: dict[str, Any]) -> None:
    stats = canonical["stats"]
    assert isinstance(stats, dict)
    marker = stats.get("immediate_delivery_contract_v1")
    if not isinstance(marker, dict) or marker.get("complete") is not True:
        raise owner_state.StateBlockedError(
            "canonical immediate-delivery migration marker is not complete"
        )


def _delivery_resolution_digest(resolutions: dict[str, dict[str, Any]]) -> str:
    return _sha256(
        _json_bytes(
            [
                {"candidate_key": key, **resolutions[key]}
                for key in sorted(resolutions)
            ]
        )
    )


def _pending_candidate_operation(
    candidate_key: str, payload: dict[str, Any]
) -> tuple[
    market_delivery.OperationIntent,
    dict[str, Any] | None,
    market_delivery.OperationReceipt | None,
]:
    content = payload.get("content")
    channel_id = payload.get("channel_id")
    if not isinstance(content, str) or not isinstance(channel_id, str):
        raise owner_state.StateBlockedError(
            "canonical pending candidate has incomplete delivery payload"
        )
    try:
        operation = market_delivery._channel_message_operation(
            content, channel_id, f"{candidate_key}:text"
        )
    except (TypeError, ValueError):
        raise owner_state.StateBlockedError(
            "canonical pending candidate delivery payload is invalid"
        ) from None

    handoff = payload.get("delivery_handoff")
    if handoff is not None and (
        not isinstance(handoff, dict)
        or set(handoff) != {"state", "operation_key", "receipt"}
        or handoff.get("state") not in {"unknown", "accepted"}
        or handoff.get("operation_key") != operation.key
        or handoff.get("state") == "unknown" and handoff.get("receipt") is not None
    ):
        raise owner_state.StateBlockedError(
            "canonical pending candidate handoff is inconsistent with its payload"
        )
    required_keys = payload.get("required_operation_keys")
    if required_keys is not None and required_keys != [operation.key]:
        raise owner_state.StateBlockedError(
            "canonical pending candidate operation manifest conflicts with its payload"
        )

    saved_receipt = None
    if isinstance(handoff, dict) and handoff.get("state") == "accepted":
        saved = handoff.get("receipt")
        try:
            saved_receipt = market_delivery.OperationReceipt.from_json(saved, operation)
        except (TypeError, ValueError):
            legacy_nonce = payload.get("nonce")
            if not isinstance(legacy_nonce, str):
                legacy_nonce = None
            try:
                legacy_operation = market_delivery._channel_message_operation(
                    content,
                    channel_id,
                    f"{candidate_key}:text",
                    reconcile_before_first_create=True,
                    legacy_nonce=legacy_nonce,
                )
                saved_receipt = market_delivery.OperationReceipt.from_json(
                    saved, legacy_operation
                )
            except (TypeError, ValueError):
                raise owner_state.StateBlockedError(
                    "canonical pending candidate saved receipt conflicts with its payload"
                ) from None
            operation = legacy_operation
    return operation, handoff, saved_receipt


def _confirmed_local_message_ids(
    payload: dict[str, Any],
    saved_receipt: market_delivery.OperationReceipt | None,
    channel_id: str,
) -> set[str]:
    message_ids: set[str] = set()
    text_id = payload.get("text_discord_id")
    if text_id is not None:
        if not isinstance(text_id, str) or not text_id.isdigit():
            raise owner_state.StateBlockedError(
                "canonical pending candidate has an invalid confirmed Discord message ID"
            )
        message_ids.add(text_id)

    if saved_receipt is not None and saved_receipt.status == "delivered":
        try:
            saved_message_id = market_delivery._delivered_message_id(
                saved_receipt, channel_id
            )
        except market_delivery.DeliveryClientError:
            raise owner_state.StateBlockedError(
                "canonical pending candidate saved delivered receipt is invalid"
            ) from None
        if saved_message_id is None:
            raise owner_state.StateBlockedError(
                "canonical pending candidate saved delivered receipt has no message ID"
            )
        message_ids.add(saved_message_id)
    return message_ids


def _observe_canonical_pending_deliveries(
    canonical: dict[str, Any], delivery_client: object | None = None
) -> dict[str, dict[str, Any]]:
    """Read and validate Delivery Owner outcomes without submitting or waiting."""
    candidates = canonical.get("candidates")
    stats = canonical.get("stats")
    if not isinstance(candidates, dict) or not isinstance(stats, dict):
        raise owner_state.StateBlockedError("canonical state has no validated candidate ledger")
    pending_keys = sorted(
        key
        for key, record in candidates.items()
        if isinstance(record, dict) and record.get("phase") == "pending_delivery"
    )
    if not pending_keys:
        return {}

    payloads = stats.get("delivery_payloads", {})
    if not isinstance(payloads, dict):
        raise owner_state.StateBlockedError("canonical delivery payload ledger is malformed")
    try:
        client = delivery_client or market_delivery.delivery_client_from_environment()
    except Exception:
        raise owner_state.StateBlockedError(
            "Delivery Owner status client is unavailable for pending candidates"
        ) from None

    resolutions: dict[str, dict[str, Any]] = {}
    for candidate_key in pending_keys:
        payload = payloads.get(candidate_key)
        expected_operation = None
        handoff = None
        confirmed_message_ids: set[str] = set()
        if payload is not None:
            if not isinstance(payload, dict):
                raise owner_state.StateBlockedError(
                    "canonical pending candidate has malformed delivery payload"
                )
            channel_id = payload.get("channel_id")
            if not isinstance(channel_id, str):
                raise owner_state.StateBlockedError(
                    "canonical pending candidate has incomplete delivery payload"
                )
            expected_operation, handoff, saved_receipt = _pending_candidate_operation(
                candidate_key, payload
            )
            confirmed_message_ids = _confirmed_local_message_ids(
                payload, saved_receipt, channel_id
            )
            operation_key = expected_operation.key
        else:
            operation_key = market_delivery._operation_key(candidate_key, "text")

        try:
            receipt = client.status(operation_key)  # type: ignore[attr-defined]
        except Exception:
            raise owner_state.StateBlockedError(
                "Delivery Owner status could not be confirmed for a pending candidate"
            ) from None

        if receipt is None:
            if (
                isinstance(handoff, dict) and handoff.get("state") == "accepted"
            ) or (
                isinstance(payload, dict) and payload.get("text_discord_id") is not None
            ):
                raise owner_state.StateBlockedError(
                    "Delivery Owner has no operation for a locally accepted pending candidate"
                )
            resolutions[candidate_key] = {
                "operation_key": operation_key,
                "status": "not_found",
                "digest": None,
                "receipt": None,
            }
            continue

        if expected_operation is None:
            raise owner_state.StateBlockedError(
                "Delivery Owner has an operation but the candidate payload is unavailable"
            )
        if receipt.key != operation_key or receipt.digest != expected_operation.digest:
            raise owner_state.StateBlockedError(
                "Delivery Owner operation conflicts with the canonical candidate payload"
            )
        if receipt.status != "delivered":
            raise owner_state.StateBlockedError(
                "Delivery Owner operation is not terminally delivered for a pending candidate"
            )
        try:
            message_id = market_delivery._delivered_message_id(
                receipt, expected_operation.target["channel_id"]
            )
        except market_delivery.DeliveryClientError:
            raise owner_state.StateBlockedError(
                "Delivery Owner delivered receipt has a conflicting destination"
            ) from None
        if message_id is None or not isinstance(receipt.receipt, dict):
            raise owner_state.StateBlockedError(
                "Delivery Owner delivered receipt is incomplete for a pending candidate"
            )
        if confirmed_message_ids and confirmed_message_ids != {message_id}:
            raise owner_state.StateBlockedError(
                "confirmed Discord message ID conflicts with Delivery Owner receipt"
            )
        resolutions[candidate_key] = {
            "operation_key": operation_key,
            "status": "delivered",
            "digest": receipt.digest,
            "receipt": {
                "id": receipt.id,
                "key": receipt.key,
                "digest": receipt.digest,
                "status": receipt.status,
                "receipt": dict(receipt.receipt),
            },
        }
    return resolutions


def merge_states(
    source: dict[str, Any],
    canonical: dict[str, Any],
    *,
    canonical_delivery_resolutions: dict[str, dict[str, Any]] | None = None,
    allow_forward_only_abandoned_pending_overlap: bool = False,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Return a merged copy and aggregate counts without changing either input."""
    owner_state._validate_state(source)
    owner_state._validate_state(canonical)
    source_status_events = _validate_source_state_scope(source)
    _validate_canonical_migration_marker(canonical)
    source_keys, source_origins = _validate_source_candidates(source)
    candidate_keys(canonical)
    source_candidates = source["candidates"]
    canonical_candidates = canonical["candidates"]
    assert isinstance(source_candidates, dict) and isinstance(canonical_candidates, dict)
    canonical_candidate_keys = set(canonical_candidates)
    pending_delivery_keys = {
        key
        for key, record in canonical_candidates.items()
        if record["phase"] == "pending_delivery"
    }
    resolutions = canonical_delivery_resolutions or {}
    if set(resolutions) != pending_delivery_keys:
        raise owner_state.StateBlockedError(
            "canonical pending candidate deliveries require complete Delivery Owner verification"
        )
    delivery_payloads = canonical.get("stats", {}).get("delivery_payloads", {})
    if not isinstance(delivery_payloads, dict):
        raise owner_state.StateBlockedError("canonical delivery payload ledger is malformed")
    for key in sorted(pending_delivery_keys):
        resolution = resolutions[key]
        if not isinstance(resolution, dict) or set(resolution) != {
            "operation_key", "status", "digest", "receipt"
        }:
            raise owner_state.StateBlockedError("Delivery Owner resolution record is malformed")
        payload = delivery_payloads.get(key)
        if resolution["status"] == "not_found":
            if resolution["digest"] is not None or resolution["receipt"] is not None:
                raise owner_state.StateBlockedError("not-found Delivery Owner resolution has receipt data")
            handoff = payload.get("delivery_handoff") if isinstance(payload, dict) else None
            if (
                isinstance(handoff, dict) and handoff.get("state") == "accepted"
            ) or (
                isinstance(payload, dict) and payload.get("text_discord_id") is not None
            ):
                raise owner_state.StateBlockedError(
                    "Delivery Owner has no operation for a locally accepted pending candidate"
                )
            continue
        if resolution["status"] != "delivered" or not isinstance(payload, dict):
            raise owner_state.StateBlockedError(
                "pending candidate delivery is not safely resolved by the Delivery Owner"
            )
        channel_id = payload.get("channel_id")
        receipt = resolution["receipt"]
        if not isinstance(channel_id, str) or not isinstance(receipt, dict):
            raise owner_state.StateBlockedError("delivered candidate resolution is incomplete")
        try:
            expected, _handoff, saved_receipt = _pending_candidate_operation(
                key, payload
            )
            message_id = market_delivery._delivered_message_id(
                market_delivery.OperationReceipt.from_json(receipt, expected), channel_id
            )
        except (TypeError, ValueError, market_delivery.DeliveryClientError):
            raise owner_state.StateBlockedError(
                "delivered candidate resolution receipt is invalid"
            ) from None
        confirmed_message_ids = _confirmed_local_message_ids(
            payload, saved_receipt, channel_id
        )
        if (
            expected.key != resolution["operation_key"]
            or expected.digest != resolution["digest"]
            or message_id is None
            or confirmed_message_ids and confirmed_message_ids != {message_id}
        ):
            raise owner_state.StateBlockedError(
                "delivered candidate resolution conflicts with its canonical payload"
            )

    canonical_stats = canonical["stats"]
    assert isinstance(canonical_stats, dict)
    canonical_origins = canonical_stats.get("news_source_work", {})
    if not isinstance(canonical_origins, dict):
        raise owner_state.StateBlockedError("canonical News source-work provenance is malformed")

    merged = deepcopy(canonical)
    merged_stats = merged["stats"]
    merged_candidates = merged["candidates"]
    assert isinstance(merged_stats, dict) and isinstance(merged_candidates, dict)
    merged_origins = merged_stats.setdefault("news_source_work", {})
    if not isinstance(merged_origins, dict):
        raise owner_state.StateBlockedError("canonical News source-work provenance is malformed")

    new_candidate_count = 0
    overlap_count = 0
    phase_difference_count = 0
    provenance_added_count = 0
    for key in sorted(source_keys):
        source_record = source_candidates[key]
        source_origin = source_origins[key]
        if key in canonical_candidate_keys:
            canonical_record = canonical_candidates[key]
            if (
                source_record["phase"] == "pending_delivery"
                and canonical_record["phase"] != "delivered"
                and key not in resolutions
                and not (
                    allow_forward_only_abandoned_pending_overlap
                    and canonical_record["phase"] == "abandoned"
                )
            ):
                raise owner_state.StateBlockedError(
                    f"source candidate {key} has an unresolved delivery outcome"
                )
            if source_record["candidate"] != canonical_record["candidate"]:
                raise owner_state.StateBlockedError(
                    f"candidate payload conflicts for shared key {key}"
                )
            overlap_count += 1
            if source_record["phase"] != canonical_record["phase"]:
                phase_difference_count += 1
        else:
            if source_record["phase"] == "pending_delivery":
                raise owner_state.StateBlockedError(
                    f"source-only candidate {key} has an unresolved delivery outcome"
                )
            merged_candidates[key] = deepcopy(source_record)
            new_candidate_count += 1

        existing_origin = provenance(canonical, key)
        if existing_origin is None:
            merged_origins[key] = deepcopy(source_origin)
            provenance_added_count += 1
        elif any(
            existing_origin[field] != source_origin[field]
            for field in _IMMUTABLE_PROVENANCE_FIELDS
        ):
            raise owner_state.StateBlockedError(
                f"source-work provenance conflicts for shared key {key}"
            )

    merged_delivery_payloads = merged_stats.get("delivery_payloads", {})
    if not isinstance(merged_delivery_payloads, dict):
        raise owner_state.StateBlockedError("canonical delivery payload ledger is malformed")
    for key, resolution in resolutions.items():
        if resolution["status"] != "delivered":
            continue
        payload = merged_delivery_payloads[key]
        assert isinstance(payload, dict)
        receipt = resolution["receipt"]
        assert isinstance(receipt, dict)
        receipt_body = receipt.get("receipt")
        assert isinstance(receipt_body, dict)
        payload["delivery_handoff"] = {
            "state": "accepted",
            "operation_key": resolution["operation_key"],
            "receipt": deepcopy(receipt),
        }
        payload["text_discord_id"] = receipt_body["message_id"]

    canonical_status_events = canonical_stats.get("stock_status_events", {})
    if not isinstance(canonical_status_events, dict):
        raise owner_state.StateBlockedError("canonical stock-status event ledger is malformed")
    if any(event["phase"] == "pending_delivery" for event in canonical_status_events.values()):
        raise owner_state.StateBlockedError(
            "canonical stock-status delivery is unresolved; verify its Delivery Owner operation before reconciliation"
        )
    merged_status_events = (
        merged_stats.setdefault("stock_status_events", {})
        if source_status_events
        else merged_stats.get("stock_status_events", {})
    )
    if not isinstance(merged_status_events, dict):
        raise owner_state.StateBlockedError("canonical stock-status event ledger is malformed")
    new_status_event_count = 0
    overlap_status_event_count = 0
    status_event_phase_difference_count = 0
    status_event_provenance_added_count = 0
    for key, source_event in sorted(source_status_events.items()):
        canonical_event = canonical_status_events.get(key)
        if canonical_event is None:
            if source_event["phase"] == "pending_delivery":
                raise owner_state.StateBlockedError(
                    f"source-only stock-status event {key} has an unresolved delivery outcome"
                )
            merged_status_events[key] = deepcopy(source_event)
            new_status_event_count += 1
            continue
        if (
            source_event["phase"] == "pending_delivery"
            and canonical_event["phase"] != "delivered"
        ):
            raise owner_state.StateBlockedError(
                f"stock-status event {key} has an unresolved delivery outcome"
            )
        if any(
            source_event.get(field) != canonical_event.get(field)
            for field in _STATUS_EVENT_IDENTITY_FIELDS
        ):
            raise owner_state.StateBlockedError(
                f"stock-status event identity or payload conflicts for shared key {key}"
            )
        if (
            source_event.get("rejection_code") is not None
            and canonical_event.get("rejection_code") is not None
            and source_event["rejection_code"] != canonical_event["rejection_code"]
        ):
            raise owner_state.StateBlockedError(
                f"stock-status rejection outcome conflicts for shared key {key}"
            )
        overlap_status_event_count += 1
        if source_event["phase"] != canonical_event["phase"]:
            status_event_phase_difference_count += 1
        merged_event = merged_status_events[key]
        provenance_added = False
        for field in _STATUS_EVENT_PROVENANCE_FIELDS:
            source_value = source_event.get(field)
            canonical_value = canonical_event.get(field)
            if source_value is None:
                continue
            if canonical_value is not None and canonical_value != source_value:
                raise owner_state.StateBlockedError(
                    f"stock-status source provenance conflicts for shared key {key}"
                )
            if canonical_value is None:
                merged_event[field] = source_value
                provenance_added = True
        if provenance_added:
            status_event_provenance_added_count += 1

    report = {
        "source_candidate_count": len(source_keys),
        "source_provenance_count": len(source_origins),
        "new_candidate_count": new_candidate_count,
        "overlap_count": overlap_count,
        "phase_difference_count": phase_difference_count,
        "provenance_added_count": provenance_added_count,
        "source_status_event_count": len(source_status_events),
        "new_status_event_count": new_status_event_count,
        "overlap_status_event_count": overlap_status_event_count,
        "status_event_phase_difference_count": status_event_phase_difference_count,
        "status_event_provenance_added_count": status_event_provenance_added_count,
        "canonical_pending_delivery_count": len(pending_delivery_keys),
        "canonical_pending_delivery_confirmed_count": sum(
            1 for resolution in resolutions.values() if resolution["status"] == "delivered"
        ),
        "canonical_pending_delivery_not_found_count": sum(
            1 for resolution in resolutions.values() if resolution["status"] == "not_found"
        ),
        "active_candidate_abandonment_count": sum(
            1
            for record in merged_candidates.values()
            if record["phase"] not in owner_state._TERMINAL_PHASES
        ),
    }
    owner_state._validate_state(merged)
    return merged, report


def _plan_digest(plan: dict[str, Any]) -> str:
    return _sha256(_json_bytes({key: value for key, value in plan.items() if key != "plan_sha256"}))


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        parent_metadata = path.parent.lstat()
    except OSError as error:
        raise owner_state.StateBlockedError("plan directory is unavailable") from error
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise owner_state.StateBlockedError("plan directory must be a real directory")
    if stat.S_IMODE(parent_metadata.st_mode) & 0o077:
        raise owner_state.StateBlockedError("plan directory permissions must exclude group and other")
    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(_json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        owner_state._fsync_directory(path.parent)
    except OSError as error:
        raise owner_state.StateBlockedError("unable to write private plan") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def preview(
    source_state_path: str | os.PathLike[str],
    canonical_state_path: str | os.PathLike[str],
    plan_file: str | os.PathLike[str],
    *,
    delivery_client: object | None = None,
) -> dict[str, Any]:
    source_path, source_raw, source_state = _state_file(source_state_path, "source state")
    canonical_path, canonical_raw, canonical_state = _state_file(
        canonical_state_path, "canonical state"
    )
    if source_path == canonical_path:
        raise owner_state.StateBlockedError("source and canonical state paths must differ")
    plan_path = _plan_path(plan_file, source_path, canonical_path)
    resolutions = _observe_canonical_pending_deliveries(canonical_state, delivery_client)
    resolution_digest = _delivery_resolution_digest(resolutions)
    merged, report = merge_states(
        source_state,
        canonical_state,
        canonical_delivery_resolutions=resolutions,
    )
    del merged
    plan: dict[str, Any] = {
        "version": PLAN_VERSION,
        "source_state_path": str(source_path),
        "canonical_state_path": str(canonical_path),
        "source_state_sha256": _sha256(source_raw),
        "canonical_state_sha256": _sha256(canonical_raw),
        "delivery_resolution_sha256": resolution_digest,
        **report,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    plan["plan_sha256"] = _plan_digest(plan)
    _write_private_json(plan_path, plan)
    return plan


def _load_plan(plan_file: str | os.PathLike[str]) -> tuple[Path, dict[str, Any]]:
    plan_path = _absolute_path(plan_file)
    try:
        metadata = plan_path.lstat()
    except OSError as error:
        raise owner_state.StateBlockedError("plan file is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise owner_state.StateBlockedError("plan file must be a regular non-symlink file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise owner_state.StateBlockedError("plan file permissions must be 0600")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise owner_state.StateBlockedError("plan file is not valid JSON") from error
    if not isinstance(plan, dict) or set(plan) != _PLAN_FIELDS:
        raise owner_state.StateBlockedError("plan file has an unsupported schema")
    if plan.get("version") != PLAN_VERSION or type(plan.get("version")) is not int:
        raise owner_state.StateBlockedError("plan version is unsupported")
    for field in (
        "source_state_sha256",
        "canonical_state_sha256",
        "delivery_resolution_sha256",
        "plan_sha256",
    ):
        if not isinstance(plan.get(field), str) or not _HEX.fullmatch(plan[field]):
            raise owner_state.StateBlockedError(f"plan {field} is invalid")
    for field in _REPORT_FIELDS:
        if type(plan.get(field)) is not int or plan[field] < 0:
            raise owner_state.StateBlockedError(f"plan {field} is invalid")
    if (
        plan["source_candidate_count"] != plan["source_provenance_count"]
        or plan["source_candidate_count"] != plan["new_candidate_count"] + plan["overlap_count"]
        or plan["phase_difference_count"] > plan["overlap_count"]
        or plan["provenance_added_count"] > plan["source_provenance_count"]
        or plan["source_status_event_count"]
        != plan["new_status_event_count"] + plan["overlap_status_event_count"]
        or plan["status_event_phase_difference_count"] > plan["overlap_status_event_count"]
        or plan["status_event_provenance_added_count"] > plan["overlap_status_event_count"]
        or plan["canonical_pending_delivery_count"]
        != plan["canonical_pending_delivery_confirmed_count"]
        + plan["canonical_pending_delivery_not_found_count"]
    ):
        raise owner_state.StateBlockedError("plan counts are inconsistent")
    for field in ("source_state_path", "canonical_state_path", "created_at"):
        if not isinstance(plan.get(field), str) or not plan[field]:
            raise owner_state.StateBlockedError(f"plan {field} is invalid")
    try:
        created_at = datetime.fromisoformat(plan["created_at"])
    except ValueError as error:
        raise owner_state.StateBlockedError("plan created_at is invalid") from error
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise owner_state.StateBlockedError("plan created_at must be timezone-aware")
    if _plan_digest(plan) != plan["plan_sha256"]:
        raise owner_state.StateBlockedError("plan digest does not match its contents")
    source_path = _absolute_path(plan["source_state_path"])
    canonical_path = _absolute_path(plan["canonical_state_path"])
    if source_path == canonical_path:
        raise owner_state.StateBlockedError("plan state paths must differ")
    _plan_path(plan_path, source_path, canonical_path)
    return plan_path, plan


def _report_matches_plan(report: dict[str, int], plan: dict[str, Any]) -> bool:
    return all(report[field] == plan[field] for field in _REPORT_FIELDS)


def _receipt_matches_plan(
    receipt: object, plan: dict[str, Any]
) -> bool:
    if not isinstance(receipt, dict):
        return False
    return (
        receipt.get("plan_sha256") == plan["plan_sha256"]
        and receipt.get("source_state_sha256") == plan["source_state_sha256"]
        and receipt.get("canonical_base_sha256") == plan["canonical_state_sha256"]
        and receipt.get("delivery_resolution_sha256")
        == plan["delivery_resolution_sha256"]
        and all(receipt.get(field) == plan[field] for field in _REPORT_FIELDS)
    )


def apply(
    plan_file: str | os.PathLike[str], *, delivery_client: object | None = None
) -> dict[str, Any]:
    plan_path, plan = _load_plan(plan_file)
    source_path = Path(plan["source_state_path"])
    canonical_path = Path(plan["canonical_state_path"])

    with ExitStack() as locks:
        for path in sorted((source_path, canonical_path), key=str):
            locks.enter_context(owner_state.run_lock(path))

        actual_source_path, source_raw, source_state = _state_file(source_path, "source state")
        actual_canonical_path, canonical_raw, canonical_state = _state_file(
            canonical_path, "canonical state"
        )
        if actual_source_path != source_path or actual_canonical_path != canonical_path:
            raise owner_state.StateBlockedError("state path changed since preview")
        if _sha256(source_raw) != plan["source_state_sha256"]:
            raise owner_state.StateBlockedError("source state changed since preview")

        canonical_stats = canonical_state["stats"]
        assert isinstance(canonical_stats, dict)
        receipt = canonical_stats.get(RECEIPT_KEY)
        if receipt is not None:
            if not _receipt_matches_plan(receipt, plan):
                raise owner_state.StateBlockedError(
                    "a different source-ingest reconciliation receipt already exists"
                )
            # A matching receipt proves this plan already abandoned active
            # candidates, while the immutable source file may retain their
            # earlier pending phase. Permit that overlap only for this retry.
            _, report = merge_states(
                source_state,
                canonical_state,
                allow_forward_only_abandoned_pending_overlap=True,
            )
            if (
                report["new_candidate_count"] != 0
                or report["provenance_added_count"] != 0
                or report["new_status_event_count"] != 0
                or report["status_event_provenance_added_count"] != 0
                or report["active_candidate_abandonment_count"] != 0
            ):
                raise owner_state.StateBlockedError(
                    "reconciliation receipt exists but source candidate or status-event data is incomplete"
                )
            return {"status": "already_applied", **{field: plan[field] for field in _REPORT_FIELDS}}

        if _sha256(canonical_raw) != plan["canonical_state_sha256"]:
            raise owner_state.StateBlockedError("canonical state changed since preview")

        resolutions = _observe_canonical_pending_deliveries(
            canonical_state, delivery_client
        )
        if _delivery_resolution_digest(resolutions) != plan["delivery_resolution_sha256"]:
            raise owner_state.StateBlockedError(
                "Delivery Owner outcomes changed since preview"
            )
        merged, report = merge_states(
            source_state,
            canonical_state,
            canonical_delivery_resolutions=resolutions,
        )
        if not _report_matches_plan(report, plan):
            raise owner_state.StateBlockedError("merge result changed since preview")
        abandoned = owner_state.abandon_active_candidates(
            merged, _FORWARD_ONLY_ABANDON_REASON
        )
        if abandoned != report["active_candidate_abandonment_count"]:
            raise owner_state.StateBlockedError(
                "active candidate count changed during forward-only reconciliation"
            )
        merged_stats = merged["stats"]
        assert isinstance(merged_stats, dict)
        merged_stats[RECEIPT_KEY] = {
            "version": 1,
            "plan_sha256": plan["plan_sha256"],
            "source_state_sha256": plan["source_state_sha256"],
            "canonical_base_sha256": plan["canonical_state_sha256"],
            "delivery_resolution_sha256": plan["delivery_resolution_sha256"],
            **report,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
        owner_state._validate_state(merged)
        owner_state.save_state(merged, canonical_path, migrate=False)
        persisted = owner_state.load_state(canonical_path, migrate=False)
        if persisted != merged:
            raise owner_state.StateBlockedError("saved canonical state differs from the merge plan")
        return {"status": "applied", **report}


def _default_source_path() -> Path:
    return Path.home() / ".agents" / "skills" / "bursawatch-tg-market-news" / "state.json"


def _default_canonical_path() -> Path:
    return Path.home() / ".hermes" / "state" / "idx-market-news.json"


def _default_plan_path() -> Path:
    return Path.home() / ".hermes" / "maintenance-plans" / "market-news-state-reconciliation.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview_parser = subparsers.add_parser("preview")
    preview_parser.add_argument("--source-state", type=Path, default=_default_source_path())
    preview_parser.add_argument("--canonical-state", type=Path, default=_default_canonical_path())
    preview_parser.add_argument("--plan-file", type=Path, default=_default_plan_path())
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--plan-file", type=Path, default=_default_plan_path())
    args = parser.parse_args(argv)
    try:
        result = (
            preview(args.source_state, args.canonical_state, args.plan_file)
            if args.command == "preview"
            else apply(args.plan_file)
        )
    except (OSError, ValueError, owner_state.StateBlockedError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, separators=(",", ":")), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
