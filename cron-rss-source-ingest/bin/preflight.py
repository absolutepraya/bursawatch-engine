"""Read-only four-lane preflight for an operator-supplied Stockbit snapshot bundle."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# The one-off preview must not create bytecode caches in the source tree.
sys.dont_write_bytecode = True

from adapter import _header_value, plan_legacy_cursor_seed
from legacy_cursor_seed import LegacySeedBlocked
from models import FeedLane
from rss import FetchResult
from source_ingest import IntakeBlocked
from config import FEEDS


_EXPECTED_LANES = ("stockbit_commentary", "unboxing", "unboxing_ipo", "ai_reports_stockbit")
_CONFIGURED_LANES = tuple(feed.lane.value for feed in FEEDS)
_LANES = _EXPECTED_LANES
_BUNDLE_VERSION = 1
_STATE_FILENAME = "stockbit-state.json"
_PAGES_FILENAME = "rss-pages.json"
_PREVIEW_ROOT_NAME = ".rss-preflight-state"
_PAGE_FIELDS = {"status", "etag", "last_modified", "items"}
_ITEM_FIELDS = {"guid", "published_at", "media_present"}


class PreflightInputError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _PageIdentity:
    lane: FeedLane
    guid: str
    published_at: datetime


def _read_json(path: Path, code: str) -> tuple[bytes, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, ValueError):
        raise PreflightInputError(code) from None
    return raw, value


def _bundle_file(root: Path, filename: str) -> Path:
    path = root / filename
    if path.is_symlink() or not path.is_file() or path.resolve().parent != root:
        raise PreflightInputError("bundle_file_invalid")
    return path


def _blocked_lane(
    lane: str,
    reason: str,
    validators: dict[str, str | None] | None = None,
    legacy_validators: dict[str, str | None] | None = None,
    *,
    poll_status: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "lane": lane,
        "status": "blocked",
        "reason": reason,
        "http_validators": validators or {"etag": None, "last_modified": None},
        "legacy_http_validators": legacy_validators or {"etag": None, "last_modified": None},
        "cursor_advanced": False,
    }
    if poll_status is not None:
        result["poll_status"] = poll_status
    return result


def _validated_validators(value: dict[str, Any]) -> tuple[dict[str, str | None], str | None]:
    validators: dict[str, str | None] = {"etag": None, "last_modified": None}
    if "etag" not in value or "last_modified" not in value:
        return validators, "http_validators_missing"
    try:
        validators["etag"] = _header_value(value["etag"], "ETag")
        validators["last_modified"] = _header_value(value["last_modified"], "Last-Modified")
    except IntakeBlocked:
        return validators, "http_validators_invalid"
    return validators, None


def _legacy_validators(record: Any) -> tuple[dict[str, str | None], str | None]:
    validators: dict[str, str | None] = {"etag": None, "last_modified": None}
    if type(record) is not dict or "etag" not in record or "last_modified" not in record:
        return validators, "legacy_http_validators_missing"
    try:
        validators["etag"] = _header_value(record["etag"], "legacy ETag")
        validators["last_modified"] = _header_value(record["last_modified"], "legacy Last-Modified")
    except IntakeBlocked:
        return validators, "legacy_http_validators_invalid"
    return validators, None


def _parse_page_items(raw_items: Any, lane: FeedLane) -> tuple[_PageIdentity, ...] | None:
    if type(raw_items) is not list:
        return None
    items: list[_PageIdentity] = []
    for raw_item in raw_items:
        if type(raw_item) is not dict or set(raw_item) != _ITEM_FIELDS:
            return None
        guid = raw_item.get("guid")
        timestamp = raw_item.get("published_at")
        media_present = raw_item.get("media_present")
        if type(guid) is not str or not guid.strip() or len(guid) > 4096 or type(timestamp) is not str or type(media_present) is not bool:
            return None
        normalized_timestamp = f"{timestamp[:-1]}+00:00" if timestamp.endswith("Z") else timestamp
        try:
            published_at = datetime.fromisoformat(normalized_timestamp)
        except ValueError:
            return None
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            return None
        items.append(_PageIdentity(lane, guid, published_at))
        # media_present is validated as a boolean but is advisory only. The
        # preflight hashes page identities and never fetches or reports URLs.
    return tuple(items)


def _plan_lane(
    lane: str,
    page_record: Any,
    legacy_state_path: Path,
    state_root: Path,
    catalog_revision: int,
    legacy_record: Any,
    legacy_lanes_valid: bool,
) -> dict[str, Any]:
    if type(page_record) is not dict or set(page_record) != _PAGE_FIELDS:
        return _blocked_lane(lane, "lane_page_invalid")
    validators, validator_error = _validated_validators(page_record)
    if validator_error is not None:
        return _blocked_lane(lane, validator_error, validators)
    legacy_validators, legacy_validator_error = _legacy_validators(legacy_record)
    if not legacy_lanes_valid:
        return _blocked_lane(lane, "legacy_lane_set_mismatch", validators, legacy_validators)
    if legacy_validator_error is not None:
        return _blocked_lane(lane, legacy_validator_error, validators, legacy_validators)

    status = page_record.get("status")
    raw_items = page_record.get("items")
    if type(status) is not int or status not in {200, 304}:
        return _blocked_lane(lane, "http_status_invalid", validators, legacy_validators)
    if status == 304:
        if type(raw_items) is not list or raw_items:
            return _blocked_lane(lane, "not_modified_page_must_be_empty", validators, legacy_validators, poll_status="empty")
        return _blocked_lane(lane, "not_modified_has_no_boundary_page", validators, legacy_validators, poll_status="empty")

    feed = next(feed for feed in FEEDS if feed.lane.value == lane)
    parsed = _parse_page_items(raw_items, feed.lane)
    if parsed is None:
        return _blocked_lane(lane, "page_item_shape_invalid", validators, legacy_validators)
    items = parsed
    endpoint = {
        "platform": "rss",
        "endpoint_id": f"rss:stockbit:{lane}",
        "publisher_id": "stockbit",
        "address": feed.url,
        "provider_id": lane,
        "catalog_revision": catalog_revision,
    }
    page = FetchResult(feed, items, validators["etag"], validators["last_modified"], False)
    try:
        plan = plan_legacy_cursor_seed(
            legacy_state_path,
            endpoint,
            catalog_revision,
            state_root=state_root,
            page=page,
        )
    except LegacySeedBlocked:
        return _blocked_lane(lane, "cursor_preview_rejected", validators, legacy_validators)
    if plan.get("status") != "preview":
        return _blocked_lane(lane, str(plan.get("reason") or "cursor_boundary_unproven"), validators, legacy_validators)
    return {
        "lane": lane,
        "status": "preview",
        "reason": None,
        "legacy_state_sha256": plan["legacy_state_sha256"],
        "catalog_revision": catalog_revision,
        "proposed_anchor": plan["proposed_anchor"],
        "boundary_timestamp": plan["boundary_timestamp"],
        "feed_page_sha256": plan["feed_page_sha256"],
        "feed_page_item_count": plan["feed_page_item_count"],
        "http_validators": validators,
        "legacy_http_validators": legacy_validators,
        "cursor_advanced": False,
    }


def _lane_set_counts(actual: set[str]) -> tuple[int, int]:
    expected = set(_LANES)
    return len(expected - actual), len(actual - expected)


def _input_failure(code: str) -> dict[str, Any]:
    lanes = [_blocked_lane(lane, code) for lane in _LANES]
    return {
        "version": _BUNDLE_VERSION,
        "lanes": lanes,
        "aggregate": {"status": "blocked", "passed": 0, "required": len(_LANES), "reason": code},
    }


def preflight_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Evaluate a local snapshot bundle without writing state or fetching feeds."""
    if len(_CONFIGURED_LANES) != 4 or set(_CONFIGURED_LANES) != set(_EXPECTED_LANES):
        raise PreflightInputError("configured_lane_set_invalid")
    root = Path(bundle_dir)
    if root.is_symlink() or not root.is_dir():
        raise PreflightInputError("bundle_directory_invalid")
    try:
        root = root.resolve(strict=True)
    except OSError:
        raise PreflightInputError("bundle_directory_invalid") from None
    preview_root = root / _PREVIEW_ROOT_NAME
    if preview_root.exists() or preview_root.is_symlink():
        raise PreflightInputError("preview_target_must_be_absent")

    state_path = _bundle_file(root, _STATE_FILENAME)
    pages_path = _bundle_file(root, _PAGES_FILENAME)
    state_raw, state = _read_json(state_path, "legacy_state_invalid")
    pages_raw, page_bundle = _read_json(pages_path, "page_bundle_invalid")
    if (
        type(state) is not dict
        or type(state.get("version")) is not int
        or state.get("version") not in {1, 2}
        or type(state.get("feeds")) is not dict
    ):
        raise PreflightInputError("legacy_state_invalid")
    if (
        type(page_bundle) is not dict
        or set(page_bundle) != {"version", "catalog_revision", "lanes"}
        or type(page_bundle.get("version")) is not int
        or page_bundle.get("version") != _BUNDLE_VERSION
        or type(page_bundle.get("catalog_revision")) is not int
        or page_bundle.get("catalog_revision") < 1
        or type(page_bundle.get("lanes")) is not dict
    ):
        raise PreflightInputError("page_bundle_invalid")

    legacy_missing, legacy_extra = _lane_set_counts(set(state["feeds"]))
    page_records = page_bundle["lanes"]
    page_missing, page_extra = _lane_set_counts(set(page_records))
    legacy_lanes_valid = legacy_missing == 0 and legacy_extra == 0
    catalog_revision = page_bundle["catalog_revision"]
    lane_reports: list[dict[str, Any]] = []
    for lane in _LANES:
        legacy_record = state["feeds"].get(lane)
        if lane not in page_records:
            lane_reports.append(
                _blocked_lane(
                    lane,
                    "lane_input_missing",
                    legacy_validators=_legacy_validators(legacy_record)[0],
                )
            )
            continue
        lane_reports.append(
            _plan_lane(
                lane,
                page_records[lane],
                state_path,
                preview_root,
                catalog_revision,
                legacy_record,
                legacy_lanes_valid,
            )
        )

    try:
        unchanged = state_path.read_bytes() == state_raw and pages_path.read_bytes() == pages_raw
    except OSError:
        unchanged = False
    if not unchanged:
        raise PreflightInputError("bundle_changed_during_preflight")

    passed = sum(lane["status"] == "preview" for lane in lane_reports)
    if legacy_missing or legacy_extra:
        aggregate_reason = "legacy_lane_set_mismatch"
    elif page_missing or page_extra:
        aggregate_reason = "lane_set_mismatch"
    elif passed != len(_LANES):
        aggregate_reason = "lane_preflight_blocked"
    else:
        aggregate_reason = "all_lanes_previewed"
    ready = aggregate_reason == "all_lanes_previewed"
    aggregate: dict[str, Any] = {
        "status": "ready" if ready else "blocked",
        "passed": passed,
        "required": len(_LANES),
        "reason": aggregate_reason,
    }
    if legacy_missing or legacy_extra:
        aggregate["missing_lane_count"] = legacy_missing
        aggregate["extra_lane_count"] = legacy_extra
    elif page_missing or page_extra:
        aggregate["missing_lane_count"] = page_missing
        aggregate["extra_lane_count"] = page_extra
    return {"version": _BUNDLE_VERSION, "lanes": lane_reports, "aggregate": aggregate}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_dir", help="operator-supplied snapshot bundle directory")
    args = parser.parse_args(argv)
    try:
        report = preflight_bundle(args.bundle_dir)
    except PreflightInputError as error:
        report = _input_failure(error.code)
        exit_code = 2
    else:
        exit_code = 0 if report["aggregate"]["status"] == "ready" else 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
