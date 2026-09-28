#!/usr/bin/env python3
"""Plan or atomically seed the new Stockbit RSS source state from snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest", "lib-bursawatch-pipeline-runtime"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
owner = ROOT / "cron-stockbit-snips" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin"
if str(owner) not in sys.path:
    sys.path.insert(0, str(owner))

import config
import discord
import state as owner_state
from preflight import PreflightInputError, preflight_bundle


_FILES = (
    "stockbit-state.json",
    "rss-pages.json",
    "delivery-receipts.json",
    "migration-context.json",
)
_LANES = tuple(feed.lane.value for feed in config.FEEDS)
_PLAN_VERSION = 1
_APPLY_ENV = "BURSAWATCH_RSS_HANDOFF_ALLOW_APPLY"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_NAME = "bursawatch-rss-source-ingest"
_LEGACY_JOB_ID = "0c6b17e4c944"
_MAX_SNAPSHOT_AGE = timedelta(minutes=15)


class HandoffInputError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bundle(root_value: str | Path) -> tuple[Path, dict[str, bytes], dict[str, Any]]:
    root = Path(root_value)
    if root.is_symlink() or not root.is_dir():
        raise HandoffInputError("snapshot_bundle_invalid")
    try:
        root = root.resolve(strict=True)
        children = {child.name for child in root.iterdir()}
    except OSError:
        raise HandoffInputError("snapshot_bundle_invalid") from None
    if children != set(_FILES):
        raise HandoffInputError("snapshot_bundle_file_set_invalid")
    raw_files: dict[str, bytes] = {}
    values: dict[str, Any] = {}
    for name in _FILES:
        path = root / name
        try:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or path.resolve(strict=True).parent != root:
                raise ValueError("invalid snapshot file")
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise HandoffInputError("snapshot_file_invalid") from None
        raw_files[name] = raw
        values[name] = value
    try:
        after = {name: (root / name).read_bytes() for name in _FILES}
    except OSError:
        raise HandoffInputError("snapshot_changed_during_read") from None
    if after != raw_files:
        raise HandoffInputError("snapshot_changed_during_read")
    return root, raw_files, values


def _bundle_digest(raw_files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in _FILES:
        raw = raw_files[name]
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _context(context: Any, catalog_revision: Any) -> tuple[datetime, int]:
    required = {
        "version", "snapshot_taken_at", "watch_config_revision", "source_catalog_revision",
        "legacy_job_id", "legacy_reader_paused", "legacy_inflight_runs",
    }
    if type(context) is not dict or set(context) != required:
        raise HandoffInputError("migration_context_invalid")
    if type(context["version"]) is not int or context["version"] != 1:
        raise HandoffInputError("migration_context_invalid")
    if type(context["watch_config_revision"]) is not int or context["watch_config_revision"] < 1:
        raise HandoffInputError("watch_config_revision_invalid")
    if type(context["source_catalog_revision"]) is not int or context["source_catalog_revision"] < 1 or context["source_catalog_revision"] != catalog_revision:
        raise HandoffInputError("source_catalog_revision_mismatch")
    if context["legacy_job_id"] != _LEGACY_JOB_ID or context["legacy_reader_paused"] is not True:
        raise HandoffInputError("legacy_reader_not_paused")
    if type(context["legacy_inflight_runs"]) is not int or context["legacy_inflight_runs"] != 0:
        raise HandoffInputError("legacy_reader_inflight")
    timestamp = context["snapshot_taken_at"]
    if type(timestamp) is not str:
        raise HandoffInputError("snapshot_timestamp_invalid")
    try:
        normalized = timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        observed = datetime.fromisoformat(normalized)
    except ValueError:
        raise HandoffInputError("snapshot_timestamp_invalid") from None
    now = datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise HandoffInputError("snapshot_timestamp_invalid")
    observed_utc = observed.astimezone(timezone.utc)
    if observed_utc > now:
        raise HandoffInputError("snapshot_timestamp_invalid")
    if now - observed_utc > _MAX_SNAPSHOT_AGE:
        raise HandoffInputError("snapshot_stale")
    return observed_utc, context["watch_config_revision"]


def _article_audit(state_path: Path, watch_revision: int, snapshot_at: datetime, receipts_value: Any) -> dict[str, Any]:
    try:
        owner = owner_state.load_state(state_path, config.FEEDS)
    except Exception:
        raise HandoffInputError("stockbit_owner_state_invalid") from None
    articles = owner.get("articles")
    if type(articles) is not dict:
        raise HandoffInputError("stockbit_owner_state_invalid")

    phases: dict[str, int] = {}
    revisions: dict[str, int] = {}
    active_leases = 0
    invalid_frozen = 0
    expected_receipts: dict[str, dict[str, Any]] = {}
    receipt_state_mismatch = False
    now = datetime.now(timezone.utc)

    for key, record in articles.items():
        if type(key) is not str or type(record) is not dict:
            raise HandoffInputError("stockbit_owner_state_invalid")
        phase = record.get("phase")
        if type(phase) is not str:
            raise HandoffInputError("stockbit_owner_state_invalid")
        phases[phase] = phases.get(phase, 0) + 1

        lease_value = record.get("agent_lease_until")
        if type(lease_value) is str:
            try:
                lease_until = datetime.fromisoformat(lease_value.replace("Z", "+00:00"))
            except ValueError:
                raise HandoffInputError("stockbit_owner_state_invalid") from None
            if lease_until.tzinfo is None or lease_until.utcoffset() is None:
                raise HandoffInputError("stockbit_owner_state_invalid")
            if lease_until.astimezone(timezone.utc) > now:
                active_leases += 1

        if phase in {"awaiting_agent", "pending_delivery", "delivered"}:
            snapshot = record.get("config_snapshot")
            if not owner_state._valid_config_snapshot(snapshot):
                invalid_frozen += 1
                continue
            revision = snapshot["revision"]
            revisions[str(revision)] = revisions.get(str(revision), 0) + 1
            if revision > watch_revision:
                invalid_frozen += 1
            source_work = record.get("source_work")
            if source_work is not None and (
                type(source_work) is not dict
                or type(source_work.get("event_key")) is not str
                or type(source_work.get("catalog_revision")) is not int
            ):
                invalid_frozen += 1

        if phase not in {"pending_delivery", "delivered"}:
            continue
        snapshot = record.get("config_snapshot")
        analysis = record.get("analysis")
        rendered = record.get("rendered")
        if not owner_state._valid_config_snapshot(snapshot) or type(analysis) is not dict or type(rendered) is not str or not rendered:
            receipt_state_mismatch = True
            continue
        route = analysis.get("route")
        if route == "id_stocks_news":
            channel = snapshot["id_stocks_news_channel_id"]
        elif route == "macro_news":
            channel = snapshot["macro_news_channel_id"]
        else:
            receipt_state_mismatch = True
            continue
        try:
            operation, _nonce = discord._operation(rendered, channel, key, "news")
        except (TypeError, ValueError):
            receipt_state_mismatch = True
            continue
        receipt = record.get("delivery") if phase == "delivered" else None
        expected_receipts[hashlib.sha256(operation.key.encode("utf-8")).hexdigest()] = {
            "digest": operation.digest,
            "status": "delivered" if phase == "delivered" else "pending",
            "receipt": (
                {"channel_id": receipt.get("channel_id"), "message_id": receipt.get("message_id")}
                if type(receipt) is dict else None
            ),
        }
        if phase == "delivered" and (
            type(receipt) is not dict
            or receipt.get("channel_id") != channel
            or type(receipt.get("message_id")) is not str
            or not receipt["message_id"].isdigit()
        ):
            receipt_state_mismatch = True

    actual_receipts: dict[str, dict[str, Any]] = {}
    if type(receipts_value) is not dict or set(receipts_value) != {"version", "receipts"} or type(receipts_value.get("version")) is not int or receipts_value.get("version") != 1 or type(receipts_value.get("receipts")) is not list:
        raise HandoffInputError("delivery_receipt_inventory_invalid")
    for item in receipts_value["receipts"]:
        if type(item) is not dict or set(item) != {"operation_key_sha256", "digest", "status", "receipt"}:
            raise HandoffInputError("delivery_receipt_inventory_invalid")
        key_hash, digest, status, receipt = (item.get("operation_key_sha256"), item.get("digest"), item.get("status"), item.get("receipt"))
        if type(key_hash) is not str or not _DIGEST_RE.fullmatch(key_hash) or type(digest) is not str or not _DIGEST_RE.fullmatch(digest) or type(status) is not str:
            raise HandoffInputError("delivery_receipt_inventory_invalid")
        if receipt is not None and (
            type(receipt) is not dict
            or set(receipt) != {"channel_id", "message_id"}
            or type(receipt.get("channel_id")) is not str
            or type(receipt.get("message_id")) is not str
            or not receipt["channel_id"].isdigit()
            or not receipt["message_id"].isdigit()
        ):
            raise HandoffInputError("delivery_receipt_inventory_invalid")
        if key_hash in actual_receipts:
            raise HandoffInputError("delivery_receipt_inventory_invalid")
        actual_receipts[key_hash] = {"digest": digest, "status": status, "receipt": receipt}

    for key_hash, expected in expected_receipts.items():
        actual = actual_receipts.get(key_hash)
        if actual != expected:
            receipt_state_mismatch = True
    if set(actual_receipts) != set(expected_receipts):
        receipt_state_mismatch = True

    pending = phases.get("awaiting_agent", 0) + phases.get("pending_delivery", 0)
    return {
        "article_phase_counts": dict(sorted(phases.items())),
        "frozen_config_revisions": dict(sorted(revisions.items(), key=lambda item: int(item[0]))),
        "active_agent_leases": active_leases,
        "legacy_owner_work_pending": pending,
        "invalid_frozen_config_count": invalid_frozen,
        "delivery_receipt_count": len(actual_receipts),
        "delivery_receipts_reconciled": not receipt_state_mismatch,
        "snapshot_taken_at": snapshot_at.isoformat(),
        "watch_config_revision": watch_revision,
    }


def _plan_body(bundle_value: str | Path, state_root_value: str | Path) -> dict[str, Any]:
    root, raw_files, values = _read_bundle(bundle_value)
    target = Path(state_root_value).expanduser()
    if not target.is_absolute() or target.name != _TARGET_NAME:
        raise HandoffInputError("rss_state_root_invalid")
    try:
        parent = target.parent.resolve(strict=True)
        if not parent.is_dir() or target.exists() or target.is_symlink():
            raise HandoffInputError("rss_state_root_must_be_absent")
    except OSError:
        raise HandoffInputError("rss_state_root_parent_invalid") from None
    target = parent / target.name

    page_bundle = values["rss-pages.json"]
    if type(page_bundle) is not dict:
        raise HandoffInputError("page_bundle_invalid")
    snapshot_at, watch_revision = _context(values["migration-context.json"], page_bundle.get("catalog_revision"))
    try:
        preflight = preflight_bundle(root)
    except PreflightInputError as error:
        raise HandoffInputError(error.code) from None
    article_audit = _article_audit(root / "stockbit-state.json", watch_revision, snapshot_at, values["delivery-receipts.json"])
    lanes = preflight["lanes"]
    lane_ready = preflight["aggregate"]["status"] == "ready"
    if not lane_ready:
        reason = "lane_preflight_blocked"
    elif article_audit["legacy_owner_work_pending"]:
        reason = "legacy_owner_work_pending"
    elif article_audit["active_agent_leases"]:
        reason = "stockbit_agent_lease_active"
    elif article_audit["invalid_frozen_config_count"]:
        reason = "frozen_config_snapshot_invalid"
    elif not article_audit["delivery_receipts_reconciled"]:
        reason = "delivery_receipt_inventory_mismatch"
    else:
        reason = "all_lanes_and_owner_state_reconciled"
    ready = reason == "all_lanes_and_owner_state_reconciled"
    file_hashes = {name: _digest(raw_files[name]) for name in _FILES}
    body: dict[str, Any] = {
        "version": _PLAN_VERSION,
        "bundle_sha256": _bundle_digest(raw_files),
        "snapshot_files_sha256": file_hashes,
        "state_root": str(target),
        "catalog_revision": page_bundle["catalog_revision"],
        "snapshot": {
            "stockbit_state_sha256": file_hashes["stockbit-state.json"],
            "rss_pages_sha256": file_hashes["rss-pages.json"],
            "delivery_receipts_sha256": file_hashes["delivery-receipts.json"],
            "migration_context_sha256": file_hashes["migration-context.json"],
            **article_audit,
        },
        "lanes": lanes,
        "aggregate": {
            "status": "ready" if ready else "blocked",
            "required_lanes": len(_LANES),
            "passed_lanes": sum(item.get("status") == "preview" for item in lanes),
            "reason": reason,
        },
    }
    body["plan_sha256"] = _digest(_canonical(body))
    try:
        after = {name: (root / name).read_bytes() for name in _FILES}
    except OSError:
        raise HandoffInputError("snapshot_changed_during_plan") from None
    if after != raw_files:
        raise HandoffInputError("snapshot_changed_during_plan")
    return body


def _write_file(path: Path, value: Any) -> None:
    raw = _canonical(value) + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _durable_tree(root: Path) -> None:
    for directory, _subdirs, _files in os.walk(root, topdown=False):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _seed_documents(plan: dict[str, Any], raw_files: dict[str, bytes], values: dict[str, Any]) -> dict[str, Any]:
    state_raw = raw_files["stockbit-state.json"]
    migration_context = values["migration-context.json"]
    documents: dict[str, Any] = {
        "catalog-revision.json": {"revision": plan["catalog_revision"]},
        "watch-config-revision.json": {"revision": migration_context["watch_config_revision"]},
    }
    lane_rows = []
    for lane_result in plan["lanes"]:
        lane = lane_result["lane"]
        feed = next(feed for feed in config.FEEDS if feed.lane.value == lane)
        endpoint_id = f"rss:stockbit:{lane}"
        endpoint = {
            "platform": "rss",
            "endpoint_id": endpoint_id,
            "publisher_id": "stockbit",
            "address": feed.url,
            "provider_id": lane,
        }
        cursor_dir = f"{endpoint_id.replace(':', '-')}"
        seed = {
            "legacy_state_sha256": _digest(state_raw),
            "endpoint": endpoint,
            "catalog_revision": plan["catalog_revision"],
            "proposed_anchor": lane_result["proposed_anchor"],
            "cursor_shape": "generic",
            "boundary_timestamp": lane_result["boundary_timestamp"],
        }
        documents[f"{cursor_dir}/cursor.json"] = {
            "initialized": True,
            "anchor": lane_result["proposed_anchor"],
            "position": None,
            "boundary_published_at": lane_result["boundary_timestamp"],
            "legacy_seed": seed,
        }
        documents[f"{cursor_dir}/http-validators.json"] = {
            "version": 1,
            **lane_result["http_validators"],
        }
        lane_rows.append({
            "lane": lane,
            "endpoint_id": endpoint_id,
            "cursor_anchor_sha256": lane_result["proposed_anchor"],
            "boundary_published_at": lane_result["boundary_timestamp"],
            "legacy_seed": seed,
            "feed_page_sha256": lane_result["feed_page_sha256"],
            "feed_page_item_count": lane_result["feed_page_item_count"],
            "legacy_http_validators": lane_result["legacy_http_validators"],
            "http_validators": lane_result["http_validators"],
        })
    receipt = {
        "version": 1,
        "snapshot_bundle_sha256": plan["bundle_sha256"],
        "snapshot_files_sha256": plan["snapshot_files_sha256"],
        "catalog_revision": plan["catalog_revision"],
        "watch_config_revision": migration_context["watch_config_revision"],
        "lane_count": len(lane_rows),
        "lanes": lane_rows,
        "stockbit_owner_audit": plan["snapshot"],
    }
    documents["legacy-cutover-receipt.json"] = receipt
    return documents


def _apply(bundle_value: str | Path, state_root_value: str | Path, expected: str) -> dict[str, Any]:
    if os.environ.get(_APPLY_ENV) != "1":
        raise HandoffInputError("apply authorization requires explicit environment gate")
    if type(expected) is not str or not _DIGEST_RE.fullmatch(expected):
        raise HandoffInputError("expected plan digest invalid")
    plan = _plan_body(bundle_value, state_root_value)
    if plan["plan_sha256"] != expected:
        raise HandoffInputError("snapshot or plan changed after planning")
    if plan["aggregate"]["status"] != "ready":
        raise HandoffInputError(plan["aggregate"]["reason"])
    root, raw_files, values = _read_bundle(bundle_value)
    if _bundle_digest(raw_files) != plan["bundle_sha256"]:
        raise HandoffInputError("snapshot or plan changed after planning")
    target = Path(plan["state_root"])
    parent = target.parent
    if target.exists() or target.is_symlink():
        raise HandoffInputError("rss_state_root_must_be_absent")
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.handoff-", dir=parent))
    os.chmod(stage, 0o700)
    try:
        for relative, value in _seed_documents(plan, raw_files, values).items():
            destination = stage / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _write_file(destination, value)
        _durable_tree(stage)
        # The target is required absent and this package is the only writer
        # until the reviewed scheduler retarget. Rename publishes the complete
        # sibling tree in one filesystem operation.
        if target.exists() or target.is_symlink():
            raise HandoffInputError("rss_state_root_must_be_absent")
        os.rename(stage, target)
        parent_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        "outcome": "applied",
        "state_root": str(target),
        "plan_sha256": plan["plan_sha256"],
        "lane_count": len(_LANES),
        "written_file_count": len(_seed_documents(plan, raw_files, values)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--expected-plan-sha256")
    args = parser.parse_args(argv)
    try:
        if args.plan:
            result = _plan_body(args.bundle_dir, args.state_root)
            exit_code = 0 if result["aggregate"]["status"] == "ready" else 1
        else:
            result = _apply(args.bundle_dir, args.state_root, args.expected_plan_sha256)
            exit_code = 0
    except HandoffInputError as error:
        result = {"aggregate": {"status": "blocked", "reason": error.code}}
        exit_code = 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
