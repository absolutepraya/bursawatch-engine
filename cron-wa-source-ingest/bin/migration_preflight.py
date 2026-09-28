"""Reconcile one operator-supplied WhatsApp migration metadata bundle.

This checker only reads its input document. It does not discover or open queue,
archive, watcher, media, Delivery Owner, database, Discord, WhatsApp, or Hermes
state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any

SCHEMA_VERSION = 3
BRI_PROFILE_ID = "bri-danareksa-sekuritas"
BRI_CHANNEL_JID = "120363419226413141@newsletter"
WA_DELIVERY_NAMESPACE = "bursawatch-wa-channel-watch"
MAX_METADATA_BYTES = 10 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FILENAME_RE = re.compile(r"^[0-9a-f]{64}\.json$")
_QUEUE_MEDIA_TYPES = {
    "image": {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"},
    "video": {"video/mp4", "video/quicktime", "video/webm"},
}
_INVENTORIES = ("queue", "archive", "watcher_outbox", "delivery_receipts")
_MANIFEST_FIELDS = {"snapshot_id", "capture_boundary", "record_count", "canonical_sha256", "records"}
_RECEIPT_MANIFEST_FIELDS = _MANIFEST_FIELDS | {"operation_namespace"}
_OUTBOX_MANIFEST_FIELDS = _MANIFEST_FIELDS | {
    "legacy_cursor", "source_state_sha256", "delivery_plan",
}
_OUTBOX_PHASES = {"pending", "awaiting_agent", "ready", "filtered", "delivered"}
_MEDIA_DELIVERY_PHASES = {
    "pending", "delivered", "not_requested", "not_applicable", "partial", "unavailable",
}
_BOARD_PHASES = {None, "pending", "accepted", "not_eligible"}
_BOARD_LINK_PHASES = {None, "pending", "patched"}
_DELIVERY_STATUSES = {
    "pending", "pending_reconciliation", "retrying", "delivering", "delivered",
    "rejected", "blocked", "ambiguous",
}
_DELIVERY_KINDS = {"channel_message_create", "channel_message_edit"}
_PLAN_FIELDS = {
    "schema_version", "source_sha256", "operation_count", "operation_key_sha256",
    "payload_sha256", "operation_kinds",
}


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"{label} has an invalid sanitized metadata shape")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise ValueError(f"{label} must be a list")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if type(value) is not str:
        raise ValueError(f"{label} must be an ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{label} must be an ISO timestamp") from error
    if result.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return result.astimezone(timezone.utc)


def _event_key(value: Any, channel_jid: str, label: str) -> str:
    if (
        type(value) is not str or len(value) > 512
        or not value.startswith(f"{channel_jid}:") or not value[len(channel_jid) + 1 :]
    ):
        raise ValueError(f"{label} is not a BRI WhatsApp event identity")
    return value


def _sha256(value: Any, label: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _media_descriptors(value: Any, label: str) -> list[dict[str, Any]]:
    result = []
    indexes: set[int] = set()
    for index, raw in enumerate(_array(value, label)):
        media = _object(raw, {"index", "kind", "mime"}, f"{label}[{index}]")
        if type(media["index"]) is not int or media["index"] < 0 or media["index"] in indexes:
            raise ValueError(f"{label} has an invalid media index")
        if type(media["kind"]) is not str or media["kind"] not in _QUEUE_MEDIA_TYPES:
            raise ValueError(f"{label} has an unsupported media kind")
        if media["mime"] is not None and type(media["mime"]) is not str:
            raise ValueError(f"{label} has an invalid MIME value")
        indexes.add(media["index"])
        result.append({"index": media["index"], "kind": media["kind"], "mime": media["mime"]})
    return sorted(result, key=lambda row: row["index"])


def _archive_media(value: Any, label: str) -> list[dict[str, Any]]:
    result = []
    indexes: set[int] = set()
    keys = {"index", "kind", "mime", "capture_status", "sha256", "bytes", "integrity_verified"}
    for index, raw in enumerate(_array(value, label)):
        media = _object(raw, keys, f"{label}[{index}]")
        if type(media["index"]) is not int or media["index"] < 0 or media["index"] in indexes:
            raise ValueError(f"{label} has an invalid media index")
        if type(media["kind"]) is not str or media["kind"] not in _QUEUE_MEDIA_TYPES:
            raise ValueError(f"{label} has an unsupported media kind")
        if media["mime"] is not None and type(media["mime"]) is not str:
            raise ValueError(f"{label} has an invalid MIME value")
        if type(media["capture_status"]) is not str or media["capture_status"] not in {"not_captured", "captured", "unavailable"}:
            raise ValueError(f"{label} has an invalid capture status")
        if type(media["integrity_verified"]) is not bool:
            raise ValueError(f"{label} integrity status must be boolean")
        digest = media["sha256"]
        size = media["bytes"]
        if media["capture_status"] == "captured":
            if type(digest) is not str or not _SHA256_RE.fullmatch(digest):
                raise ValueError(f"{label} captured media checksum is invalid")
            if type(size) is not int or size < 1 or media["integrity_verified"] is not True:
                raise ValueError(f"{label} captured media integrity is unverified")
        elif digest is not None or size is not None:
            raise ValueError(f"{label} uncaptured media must not contain object metadata")
        indexes.add(media["index"])
        result.append({
            "index": media["index"], "kind": media["kind"], "mime": media["mime"],
            "capture_status": media["capture_status"], "sha256": digest,
            "bytes": size, "integrity_verified": media["integrity_verified"],
        })
    return sorted(result, key=lambda row: row["index"])


def _position(row: dict[str, Any]) -> tuple[int, str]:
    return row["mtime_ns"], row["filename"]


def _supported_media_mime(kind: str, mime: Any) -> bool:
    if type(mime) is not str:
        return False
    normalized = mime.casefold()
    if normalized == "image/jpg":
        normalized = "image/jpeg"
    return normalized in _QUEUE_MEDIA_TYPES[kind]


def _inventory_payload(name: str, inventory: dict[str, Any]) -> dict[str, Any]:
    records = inventory["records"]
    if name == "queue":
        records = sorted(records, key=lambda row: (row["mtime_ns"], row["filename"]))
    elif name in {"archive", "watcher_outbox"}:
        records = sorted(records, key=lambda row: row["event_key"])
    else:
        records = sorted(records, key=lambda row: row["operation_key_sha256"])
    payload = {
        "snapshot_id": inventory["snapshot_id"],
        "capture_boundary": inventory["capture_boundary"],
        "records": records,
    }
    if name == "delivery_receipts":
        payload["operation_namespace"] = inventory["operation_namespace"]
    if name == "watcher_outbox":
        payload.update({
            "legacy_cursor": inventory["legacy_cursor"],
            "source_state_sha256": inventory["source_state_sha256"],
            "delivery_plan": inventory["delivery_plan"],
        })
    return payload


def plan_migration_preflight(metadata: Any) -> dict[str, Any]:
    """Compare supplied inventories and return a read-only, evidence-scoped report.

    Counts and digests validate the supplied bundle. They cannot prove that its
    exporter captured every source record or captured all sources atomically.
    """
    root = _object(metadata, {
        "schema_version", "profile_id", "channel_jid", "snapshot", "inventories",
    }, "metadata")
    if type(root["schema_version"]) is not int or root["schema_version"] != SCHEMA_VERSION:
        raise ValueError("metadata schema version is unsupported")
    if root["profile_id"] != BRI_PROFILE_ID or root["channel_jid"] != BRI_CHANNEL_JID:
        raise ValueError("preflight metadata is restricted to the reviewed BRI profile")

    snapshot = _object(root["snapshot"], {"id", "capture_boundary"}, "snapshot")
    snapshot_id = snapshot["id"]
    if type(snapshot_id) is not str or not 1 <= len(snapshot_id) <= 128:
        raise ValueError("snapshot.id is invalid")
    snapshot_boundary = _timestamp(snapshot["capture_boundary"], "snapshot.capture_boundary")
    inventories_value = _object(root["inventories"], set(_INVENTORIES), "inventories")

    blockers: set[str] = {
        "inventory_completeness_unproven",
        "snapshot_freshness_unproven",
    }
    inventory_values: dict[str, dict[str, Any]] = {}
    manifest_report: dict[str, dict[str, Any]] = {}
    snapshot_id_mismatches = 0
    capture_boundary_mismatches = 0
    record_count_mismatches = 0
    digest_mismatches = 0

    for name in _INVENTORIES:
        fields = (
            _OUTBOX_MANIFEST_FIELDS if name == "watcher_outbox"
            else _RECEIPT_MANIFEST_FIELDS if name == "delivery_receipts"
            else _MANIFEST_FIELDS
        )
        item = _object(inventories_value[name], fields, f"inventories.{name}")
        item_id = item["snapshot_id"]
        if type(item_id) is not str or not 1 <= len(item_id) <= 128:
            raise ValueError(f"inventories.{name}.snapshot_id is invalid")
        boundary = _timestamp(item["capture_boundary"], f"inventories.{name}.capture_boundary")
        if type(item["record_count"]) is not int or item["record_count"] < 0:
            raise ValueError(f"inventories.{name}.record_count is invalid")
        declared_digest = _sha256(item["canonical_sha256"], f"inventories.{name}.canonical_sha256")
        records = _array(item["records"], f"inventories.{name}.records")
        if item_id != snapshot_id:
            snapshot_id_mismatches += 1
            blockers.add("inventory_snapshot_identity_mismatch")
        if boundary != snapshot_boundary:
            capture_boundary_mismatches += 1
            blockers.add("inventory_capture_boundary_mismatch")
        if item["record_count"] != len(records):
            record_count_mismatches += 1
            blockers.add(f"{name}_record_count_mismatch")
        inventory_values[name] = dict(item)
        inventory_values[name]["_parsed_boundary"] = boundary
        inventory_values[name]["_declared_digest"] = declared_digest

    receipt_namespace = inventory_values["delivery_receipts"]["operation_namespace"]
    if receipt_namespace != WA_DELIVERY_NAMESPACE:
        raise ValueError("delivery receipt inventory is not scoped to the WhatsApp watcher namespace")

    legacy = _object(
        inventory_values["watcher_outbox"]["legacy_cursor"],
        {"published_at", "event_key"},
        "inventories.watcher_outbox.legacy_cursor",
    )
    legacy_key = _event_key(legacy["event_key"], BRI_CHANNEL_JID, "legacy_cursor.event_key")
    legacy_timestamp = _timestamp(legacy["published_at"], "legacy_cursor.published_at")
    source_state_sha = _sha256(
        inventory_values["watcher_outbox"]["source_state_sha256"],
        "inventories.watcher_outbox.source_state_sha256",
    )
    plan_raw = _object(
        inventory_values["watcher_outbox"]["delivery_plan"],
        _PLAN_FIELDS,
        "inventories.watcher_outbox.delivery_plan",
    )
    if type(plan_raw["schema_version"]) is not int or plan_raw["schema_version"] != 1:
        raise ValueError("watcher delivery plan schema version is unsupported")
    plan_source_sha = _sha256(plan_raw["source_sha256"], "delivery_plan.source_sha256")
    if type(plan_raw["operation_count"]) is not int or plan_raw["operation_count"] < 0:
        raise ValueError("delivery_plan.operation_count is invalid")
    operation_keys = [
        _sha256(value, f"delivery_plan.operation_key_sha256[{index}]")
        for index, value in enumerate(_array(plan_raw["operation_key_sha256"], "delivery_plan.operation_key_sha256"))
    ]
    payload_digests = [
        _sha256(value, f"delivery_plan.payload_sha256[{index}]")
        for index, value in enumerate(_array(plan_raw["payload_sha256"], "delivery_plan.payload_sha256"))
    ]
    operation_kinds = _array(plan_raw["operation_kinds"], "delivery_plan.operation_kinds")
    if any(type(kind) is not str or kind not in _DELIVERY_KINDS for kind in operation_kinds):
        raise ValueError("delivery plan contains an unsupported operation kind")
    delivery_plan = {
        "schema_version": plan_raw["schema_version"],
        "source_sha256": plan_source_sha,
        "operation_count": plan_raw["operation_count"],
        "operation_key_sha256": operation_keys,
        "payload_sha256": payload_digests,
        "operation_kinds": operation_kinds,
    }
    if plan_source_sha != source_state_sha:
        blockers.add("delivery_plan_watcher_source_mismatch")
    plan_lengths_match = (
        plan_raw["operation_count"] == len(operation_keys) == len(payload_digests) == len(operation_kinds)
    )
    if not plan_lengths_match:
        blockers.add("watcher_delivery_plan_count_mismatch")
    if len(operation_keys) != len(set(operation_keys)):
        blockers.add("duplicate_expected_delivery_operation")
    inventory_values["watcher_outbox"]["legacy_cursor"] = dict(legacy)
    inventory_values["watcher_outbox"]["source_state_sha256"] = source_state_sha
    inventory_values["watcher_outbox"]["delivery_plan"] = delivery_plan

    queue_rows: list[dict[str, Any]] = []
    queue_by_key: dict[str, dict[str, Any]] = {}
    duplicate_queue_keys: set[str] = set()
    queue_keys = {
        "event_key", "published_at", "mtime_ns", "filename", "media",
        "exact_technical_review_marker",
    }
    for index, raw in enumerate(inventory_values["queue"]["records"]):
        row = _object(raw, queue_keys, f"queue.records[{index}]")
        key = _event_key(row["event_key"], BRI_CHANNEL_JID, f"queue.records[{index}].event_key")
        published_at = _timestamp(row["published_at"], f"queue.records[{index}].published_at")
        if type(row["mtime_ns"]) is not int or not 0 <= row["mtime_ns"] < 10**20:
            raise ValueError(f"queue.records[{index}].mtime_ns is invalid")
        filename = row["filename"]
        if type(filename) is not str or not _FILENAME_RE.fullmatch(filename):
            raise ValueError(f"queue.records[{index}].filename is invalid")
        expected_filename = f"{hashlib.sha256(key.encode('utf-8')).hexdigest()}.json"
        if filename != expected_filename:
            blockers.add("queue_filename_identity_mismatch")
        marker = row["exact_technical_review_marker"]
        if type(marker) is not bool:
            raise ValueError(f"queue.records[{index}].exact_technical_review_marker must be boolean")
        parsed = {
            "event_key": key, "published_at": published_at,
            "mtime_ns": row["mtime_ns"], "filename": filename,
            "media": _media_descriptors(row["media"], f"queue.records[{index}].media"),
            "exact_technical_review_marker": marker,
        }
        if key in queue_by_key:
            duplicate_queue_keys.add(key)
        queue_by_key[key] = parsed
        queue_rows.append(parsed)
    if duplicate_queue_keys:
        blockers.add("duplicate_queue_event_identity")
    queue_positions = [_position(row) for row in queue_rows]
    if len(queue_positions) != len(set(queue_positions)):
        blockers.add("duplicate_queue_arrival_position")

    archive_rows: list[dict[str, Any]] = []
    archive_by_key: dict[str, dict[str, Any]] = {}
    duplicate_archive_keys: set[str] = set()
    archive_keys = {"event_key", "published_at", "record_checksum_verified", "media"}
    for index, raw in enumerate(inventory_values["archive"]["records"]):
        row = _object(raw, archive_keys, f"archive.records[{index}]")
        key = _event_key(row["event_key"], BRI_CHANNEL_JID, f"archive.records[{index}].event_key")
        published_at = _timestamp(row["published_at"], f"archive.records[{index}].published_at")
        if type(row["record_checksum_verified"]) is not bool:
            raise ValueError(f"archive.records[{index}].record_checksum_verified must be boolean")
        parsed = {
            "event_key": key, "published_at": published_at,
            "record_checksum_verified": row["record_checksum_verified"],
            "media": _archive_media(row["media"], f"archive.records[{index}].media"),
        }
        if key in archive_by_key:
            duplicate_archive_keys.add(key)
        archive_by_key[key] = parsed
        archive_rows.append(parsed)
    if duplicate_archive_keys:
        blockers.add("duplicate_archive_event_identity")
    if any(not row["record_checksum_verified"] for row in archive_rows):
        blockers.add("archive_record_integrity_unverified")

    outbox_rows: list[dict[str, Any]] = []
    outbox_by_key: dict[str, dict[str, Any]] = {}
    duplicate_outbox_keys: set[str] = set()
    outbox_phase_counts: dict[str, int] = {phase: 0 for phase in sorted(_OUTBOX_PHASES)}
    outbox_media_counts: dict[str, int] = {phase: 0 for phase in sorted(_MEDIA_DELIVERY_PHASES)}
    outbox_board_counts: dict[str, int] = {"unset": 0, **{str(phase): 0 for phase in sorted(_BOARD_PHASES - {None})}}
    board_link_phase_counts = {"unset": 0, "pending": 0, "patched": 0}
    outbox_fields = {
        "event_key", "profile_id", "routable", "agent_phase", "media_delivery_status",
        "board_phase", "board_link_phase", "text_message_count",
    }
    for index, raw in enumerate(inventory_values["watcher_outbox"]["records"]):
        row = _object(raw, outbox_fields, f"watcher_outbox.records[{index}]")
        key = _event_key(row["event_key"], BRI_CHANNEL_JID, f"watcher_outbox.records[{index}].event_key")
        if row["profile_id"] != BRI_PROFILE_ID:
            blockers.add("watcher_outbox_contains_non_bri_profile")
        if (
            type(row["routable"]) is not bool or type(row["agent_phase"]) is not str
            or row["agent_phase"] not in _OUTBOX_PHASES
        ):
            raise ValueError(f"watcher_outbox.records[{index}] state metadata is invalid")
        if type(row["media_delivery_status"]) is not str or row["media_delivery_status"] not in _MEDIA_DELIVERY_PHASES:
            raise ValueError(f"watcher_outbox.records[{index}] media status is invalid")
        if (
            (row["board_phase"] is not None and type(row["board_phase"]) is not str)
            or row["board_phase"] not in _BOARD_PHASES
            or (row["board_link_phase"] is not None and type(row["board_link_phase"]) is not str)
            or row["board_link_phase"] not in _BOARD_LINK_PHASES
        ):
            raise ValueError(f"watcher_outbox.records[{index}] Board metadata is invalid")
        if type(row["text_message_count"]) is not int or row["text_message_count"] < 0:
            raise ValueError(f"watcher_outbox.records[{index}] text message count is invalid")
        parsed = dict(row)
        outbox_phase_counts[row["agent_phase"]] += 1
        outbox_media_counts[row["media_delivery_status"]] += 1
        outbox_board_counts[str(row["board_phase"]) if row["board_phase"] is not None else "unset"] += 1
        board_link_phase_counts[str(row["board_link_phase"]) if row["board_link_phase"] is not None else "unset"] += 1
        if key in outbox_by_key:
            duplicate_outbox_keys.add(key)
        outbox_by_key[key] = parsed
        outbox_rows.append(parsed)
    if duplicate_outbox_keys:
        blockers.add("duplicate_watcher_outbox_event")

    for name in _INVENTORIES:
        inventory = inventory_values[name]
        payload = _inventory_payload(name, inventory)
        actual_digest = _canonical_digest(payload)
        digest_matches = actual_digest == inventory["_declared_digest"]
        if not digest_matches:
            digest_mismatches += 1
            blockers.add(f"{name}_canonical_digest_mismatch")
        manifest_report[name] = {
            "snapshot_id_matches": inventory["snapshot_id"] == snapshot_id,
            "capture_boundary_matches": inventory["_parsed_boundary"] == snapshot_boundary,
            "declared_record_count": inventory["record_count"],
            "observed_record_count": len(inventory["records"]),
            "record_count_matches": inventory["record_count"] == len(inventory["records"]),
            "canonical_digest_matches": digest_matches,
        }
    if record_count_mismatches:
        blockers.add("inventory_record_count_mismatch")

    queue_key_set = set(queue_by_key)
    archive_key_set = set(archive_by_key)
    queue_only = queue_key_set - archive_key_set
    archive_only = archive_key_set - queue_key_set
    if queue_only or archive_only:
        blockers.add("queue_archive_identity_mismatch")

    media_report = {
        "queue_descriptors": sum(len(row["media"]) for row in queue_rows),
        "archive_descriptors": sum(len(row["media"]) for row in archive_rows),
        "matched_descriptors": 0,
        "captured_verified": 0,
        "unavailable_or_uncaptured": 0,
        "technical_review_events": 0,
        "technical_review_image_eligible": 0,
    }
    for key in queue_key_set & archive_key_set:
        queue_row = queue_by_key[key]
        archive_row = archive_by_key[key]
        if queue_row["published_at"] != archive_row["published_at"]:
            blockers.add("queue_archive_published_at_mismatch")
        queue_media = queue_row["media"]
        archive_media = archive_row["media"]
        queue_shape = [(row["index"], row["kind"], row["mime"]) for row in queue_media]
        archive_shape = [(row["index"], row["kind"], row["mime"]) for row in archive_media]
        if queue_shape != archive_shape:
            blockers.add("queue_archive_media_manifest_mismatch")
            continue
        media_report["matched_descriptors"] += len(queue_media)
        for item in archive_media:
            if item["capture_status"] == "captured" and item["integrity_verified"]:
                media_report["captured_verified"] += 1
            else:
                media_report["unavailable_or_uncaptured"] += 1
        if queue_row["exact_technical_review_marker"]:
            media_report["technical_review_events"] += 1
            captured_images = [
                item for item in archive_media
                if item["kind"] == "image" and item["capture_status"] == "captured"
                and item["integrity_verified"]
            ]
            if len(captured_images) == 1 and _supported_media_mime("image", captured_images[0]["mime"]):
                media_report["technical_review_image_eligible"] += 1
            else:
                blockers.add("technical_review_requires_one_verified_archived_image")

    legacy_order_rows = sorted(queue_rows, key=lambda row: (row["published_at"], row["event_key"]))
    arrival_order_rows = sorted(queue_rows, key=_position)
    legacy_order = [row["event_key"] for row in legacy_order_rows]
    arrival_order = [row["event_key"] for row in arrival_order_rows]
    orders_match = bool(queue_rows) and legacy_order == arrival_order
    if queue_rows and not orders_match:
        blockers.add("queue_arrival_order_differs_from_legacy_cursor_order")
    anchor = queue_by_key.get(legacy_key)
    anchor_matches = anchor is not None and anchor["published_at"] == legacy_timestamp
    if not anchor_matches:
        blockers.add("legacy_cursor_anchor_not_found")

    supplied_legacy_tail_media_blocked = 0
    if orders_match and anchor_matches:
        tail_start = legacy_order.index(legacy_key) + 1
        for key in legacy_order[tail_start:]:
            queue_row = queue_by_key[key]
            archive_row = archive_by_key.get(key)
            if archive_row is None:
                supplied_legacy_tail_media_blocked += 1
                blockers.add("post_cursor_event_archive_missing")
                continue
            archived_by_index = {item["index"]: item for item in archive_row["media"]}
            event_media_blocked = False
            for descriptor in queue_row["media"]:
                archived = archived_by_index.get(descriptor["index"])
                if (
                    archived is None or archived["capture_status"] != "captured"
                    or not archived["integrity_verified"]
                    or not _supported_media_mime(descriptor["kind"], descriptor["mime"])
                ):
                    event_media_blocked = True
            if queue_row["exact_technical_review_marker"]:
                archived_images = [
                    item for item in archive_row["media"]
                    if item["kind"] == "image" and item["capture_status"] == "captured"
                    and item["integrity_verified"]
                ]
                if len(archived_images) != 1 or not _supported_media_mime("image", archived_images[0]["mime"]):
                    event_media_blocked = True
                    blockers.add("technical_review_requires_one_verified_archived_image")
            if event_media_blocked:
                supplied_legacy_tail_media_blocked += 1
                blockers.add("post_cursor_media_not_durable")

    outbox_unmatched = set(outbox_by_key) - queue_key_set
    if outbox_unmatched:
        blockers.add("watcher_outbox_event_unmatched")
    active_outbox = sum(
        1 for row in outbox_rows
        if row["profile_id"] == BRI_PROFILE_ID and row["routable"]
        and row["agent_phase"] in {"pending", "awaiting_agent", "ready"}
    )
    if active_outbox:
        blockers.add("active_routable_watcher_outbox")
    if any(
        row["board_link_phase"] == "patched" and row["board_phase"] != "accepted"
        for row in outbox_rows
    ):
        blockers.add("board_link_state_inconsistent")
    expected_board_link_edit_legs = sum(
        row["text_message_count"]
        for row in outbox_rows
        if row["board_phase"] == "accepted" and row["board_link_phase"] == "patched"
    )
    patched_board_link_events = sum(
        1 for row in outbox_rows
        if row["board_phase"] == "accepted" and row["board_link_phase"] == "patched"
    )
    if any(
        row["text_message_count"] == 0
        for row in outbox_rows
        if row["board_phase"] == "accepted" and row["board_link_phase"] == "patched"
    ):
        blockers.add("board_link_message_count_missing")
    planned_board_link_edit_legs = sum(
        1 for kind in operation_kinds if kind == "channel_message_edit"
    )
    if planned_board_link_edit_legs != expected_board_link_edit_legs:
        blockers.add("board_link_edit_operation_count_mismatch")
    unresolved_board_handoffs = sum(
        1 for row in outbox_rows
        if row["board_phase"] == "pending"
        or (row["board_phase"] == "accepted" and row["board_link_phase"] != "patched")
    )
    if unresolved_board_handoffs:
        blockers.add("watcher_board_handoff_unresolved")

    expected_operations = {
        key: {"payload_sha256": payload, "kind": kind}
        for key, payload, kind in zip(operation_keys, payload_digests, operation_kinds)
    }
    receipts: list[dict[str, Any]] = []
    receipt_by_key: dict[str, dict[str, Any]] = {}
    duplicate_receipts: set[str] = set()
    unresolved_receipts: set[str] = set()
    receipt_unexpected = 0
    receipt_payload_mismatches = 0
    receipt_kind_mismatches = 0
    receipt_status_counts = {status: 0 for status in sorted(_DELIVERY_STATUSES)}
    receipt_fields = {"operation_key_sha256", "payload_sha256", "kind", "status", "receipt_present"}
    for index, raw in enumerate(inventory_values["delivery_receipts"]["records"]):
        row = _object(raw, receipt_fields, f"delivery_receipts.records[{index}]")
        operation_key_sha = _sha256(row["operation_key_sha256"], f"delivery_receipts.records[{index}].operation_key_sha256")
        payload_sha = _sha256(row["payload_sha256"], f"delivery_receipts.records[{index}].payload_sha256")
        if type(row["kind"]) is not str or row["kind"] not in _DELIVERY_KINDS:
            raise ValueError(f"delivery_receipts.records[{index}].kind is unsupported")
        if (
            type(row["status"]) is not str or row["status"] not in _DELIVERY_STATUSES
            or type(row["receipt_present"]) is not bool
        ):
            raise ValueError(f"delivery_receipts.records[{index}] receipt metadata is invalid")
        receipt_status_counts[row["status"]] += 1
        if row["status"] != "delivered" or row["receipt_present"] is not True:
            unresolved_receipts.add(operation_key_sha)
            blockers.add("delivery_receipt_unresolved")
        if operation_key_sha in receipt_by_key:
            duplicate_receipts.add(operation_key_sha)
            blockers.add("duplicate_delivery_receipt_operation")
        receipt_by_key[operation_key_sha] = {
            "operation_key_sha256": operation_key_sha,
            "payload_sha256": payload_sha,
            "kind": row["kind"], "status": row["status"],
            "receipt_present": row["receipt_present"],
        }
        receipts.append(receipt_by_key[operation_key_sha])

    for key, expected in expected_operations.items():
        row = receipt_by_key.get(key)
        if row is None:
            blockers.add("delivery_receipt_expected_leg_missing")
            continue
        if row["payload_sha256"] != expected["payload_sha256"]:
            receipt_payload_mismatches += 1
            blockers.add("delivery_receipt_payload_mismatch")
        if row["kind"] != expected["kind"]:
            receipt_kind_mismatches += 1
            blockers.add("delivery_receipt_operation_kind_mismatch")
        if row["status"] != "delivered" or row["receipt_present"] is not True:
            unresolved_receipts.add(key)
            blockers.add("delivery_receipt_unresolved")

    for key, row in receipt_by_key.items():
        if key in expected_operations:
            continue
        receipt_unexpected += 1
        blockers.add("unexpected_delivery_receipt_operation")
    if duplicate_receipts:
        blockers.add("duplicate_delivery_receipt_operation")

    bundle_integrity_valid = (
        snapshot_id_mismatches == 0 and capture_boundary_mismatches == 0
        and record_count_mismatches == 0 and digest_mismatches == 0
        and plan_lengths_match and plan_source_sha == source_state_sha
    )
    if not bundle_integrity_valid:
        blockers.add("supplied_bundle_integrity_invalid")
    expected_legs_bound = plan_lengths_match and plan_source_sha == source_state_sha
    expected_edit_operations = {
        key: expected
        for key, expected in expected_operations.items()
        if expected["kind"] == "channel_message_edit"
    }
    matched_board_link_edit_legs = sum(
        1 for key, expected in expected_edit_operations.items()
        if key in receipt_by_key
        and receipt_by_key[key]["payload_sha256"] == expected["payload_sha256"]
        and receipt_by_key[key]["kind"] == expected["kind"]
        and receipt_by_key[key]["status"] == "delivered"
        and receipt_by_key[key]["receipt_present"] is True
    )
    receipt_reconciliation_status = "unproven"
    if bundle_integrity_valid and expected_legs_bound:
        if any(blocker in blockers for blocker in (
            "delivery_receipt_expected_leg_missing", "duplicate_delivery_receipt_operation",
            "delivery_receipt_payload_mismatch", "delivery_receipt_operation_kind_mismatch",
            "delivery_receipt_unresolved", "unexpected_delivery_receipt_operation",
            "board_link_edit_operation_count_mismatch", "board_link_message_count_missing",
            "board_link_state_inconsistent",
        )):
            receipt_reconciliation_status = "blocked"
        else:
            receipt_reconciliation_status = "matched_within_supplied_bundle"

    supplied_crosswalk_consistent = bool(
        queue_rows and anchor_matches and orders_match
        and not queue_only and not archive_only
        and not duplicate_queue_keys and not duplicate_archive_keys
        and not blockers.intersection({
            "queue_filename_identity_mismatch", "duplicate_queue_arrival_position",
            "queue_archive_published_at_mismatch", "queue_archive_media_manifest_mismatch",
            "archive_record_integrity_unverified", "queue_record_count_mismatch",
            "archive_record_count_mismatch", "queue_canonical_digest_mismatch",
            "archive_canonical_digest_mismatch",
        })
    )

    observed_anchor_position = None
    if supplied_crosswalk_consistent and anchor is not None:
        observed_anchor_position = {
            "mtime_ns": anchor["mtime_ns"],
            "filename": anchor["filename"],
            "position": f"{anchor['mtime_ns']:020d}:{anchor['filename']}",
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "blocked",
        "readiness": "blocked",
        "apply": False,
        "cursor_written": False,
        "production_cutover_authorized": False,
        "evidence_scope": "operator_supplied_sanitized_metadata",
        "profile_id": BRI_PROFILE_ID,
        "snapshot": {
            "id": snapshot_id,
            "capture_boundary": snapshot["capture_boundary"],
            "inventory_identity_mismatches": snapshot_id_mismatches,
            "capture_boundary_mismatches": capture_boundary_mismatches,
            "inventory_completeness": "unproven",
            "freshness": "unproven",
            "bundle_integrity": "valid" if bundle_integrity_valid else "invalid",
            "inventories": manifest_report,
        },
        "cursor_crosswalk": {
            "status": "unproven",
            "supplied_records_consistent": supplied_crosswalk_consistent,
            "order_preserved_in_supplied_records": orders_match,
            "legacy_anchor_matched_in_supplied_records": anchor_matches,
            "observed_anchor_position": observed_anchor_position,
            "candidate_position": None,
            "reason": "source completeness and snapshot freshness are not attested by bundle counts or digests",
        },
        "receipt_reconciliation": {
            "status": receipt_reconciliation_status,
            "expected_leg_source": "sanitized Discord Delivery Handoff plan bound to watcher source SHA-256",
            "expected_leg_set_bound": expected_legs_bound,
            "expected_legs": len(expected_operations),
            "receipt_records": len(receipts),
            "missing_expected_legs": max(0, len(expected_operations) - len(set(receipt_by_key) & set(expected_operations))),
            "expected_board_link_edit_legs": expected_board_link_edit_legs,
            "planned_board_link_edit_legs": planned_board_link_edit_legs,
            "matched_board_link_edit_legs": matched_board_link_edit_legs,
            "duplicate_receipt_legs": len(duplicate_receipts),
            "unexpected_receipts": receipt_unexpected,
            "payload_mismatches": receipt_payload_mismatches,
            "operation_kind_mismatches": receipt_kind_mismatches,
            "unresolved_receipts": len(unresolved_receipts),
            "patched_board_link_events": patched_board_link_events,
            "unresolved_board_handoffs": unresolved_board_handoffs,
            "statuses": receipt_status_counts,
            "inventory_completeness": "unproven",
        },
        "reconciliation": {
            "queue_archive": {
                "queue_events": len(queue_rows),
                "archive_records": len(archive_rows),
                "matched_events": len(queue_key_set & archive_key_set),
                "queue_without_archive": len(queue_only),
                "archive_without_queue": len(archive_only),
            },
            "media": {
                **media_report,
                "supplied_legacy_tail_events": max(0, len(legacy_order) - legacy_order.index(legacy_key) - 1)
                if orders_match and anchor_matches else 0,
                "supplied_legacy_tail_media_blocked": supplied_legacy_tail_media_blocked,
                "tail_basis": "supplied_legacy_order_only",
            },
            "watcher_outbox": {
                "records": len(outbox_rows),
                "matched_events": len(set(outbox_by_key) & queue_key_set),
                "unmatched_events": len(outbox_unmatched),
                "active_routable_records": active_outbox,
                "agent_phases": outbox_phase_counts,
                "media_delivery_phases": outbox_media_counts,
                "board_phases": outbox_board_counts,
                "board_link_phases": board_link_phase_counts,
            },
            "delivery_receipts": {
                "records": len(receipts),
                "matched_expected_legs": len(set(receipt_by_key) & set(expected_operations)),
                "unexpected_receipts": receipt_unexpected,
                "duplicates": len(duplicate_receipts),
                "unresolved": len(unresolved_receipts),
            },
        },
        "blockers": sorted(blockers),
    }


def _read_metadata(path: Path) -> Any:
    path = Path(path).expanduser()
    try:
        details = path.lstat()
    except OSError as error:
        raise ValueError("metadata file is unavailable") from error
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode) or details.st_size > MAX_METADATA_BYTES:
        raise ValueError("metadata file must be a bounded regular file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("metadata file is not readable JSON") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only WhatsApp migration metadata preflight")
    parser.add_argument("--metadata", required=True, type=Path, help="operator-supplied sanitized JSON metadata")
    arguments = parser.parse_args(argv)
    try:
        result = plan_migration_preflight(_read_metadata(arguments.metadata))
    except ValueError as error:
        print(json.dumps({"status": "invalid_metadata", "reason": str(error)}, separators=(",", ":")), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
