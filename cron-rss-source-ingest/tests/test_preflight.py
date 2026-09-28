from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cron-rss-source-ingest" / "bin" / "preflight.py"
LANES = ("stockbit_commentary", "unboxing", "unboxing_ipo", "ai_reports_stockbit")
NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
PRIVATE_SOURCE_TEXT = "private source text must never be reported"


def _article(guid: str, published_at: datetime, *, media_present: bool = False) -> dict[str, object]:
    return {
        "guid": guid,
        "published_at": published_at.isoformat(),
        "media_present": media_present,
    }


def _bundle(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    bundle = tmp_path / "operator-bundle"
    bundle.mkdir()
    feeds = {}
    lane_pages = {}
    for index, lane in enumerate(LANES):
        boundary_guid = f"cursor-{lane}"
        boundary_time = NOW.isoformat()
        feeds[lane] = {
            "cursor": {"published_at": boundary_time, "guid": boundary_guid},
            "etag": f'"legacy-{index}"',
            "last_modified": None,
        }
        lane_pages[lane] = {
            "status": 200,
            "etag": None if index == 0 else f'"page-{index}"',
            "last_modified": None if index % 2 == 0 else "Mon, 28 Sep 2026 08:00:00 GMT",
            "items": [
                _article(f"newer-{lane}", NOW + timedelta(minutes=2)),
                _article(boundary_guid, NOW),
                _article(f"older-{lane}", NOW - timedelta(minutes=2)),
            ],
        }
    state = {
        "version": 2,
        "feeds": feeds,
        "articles": {
            "stockbit:unboxing:queued": {
                "article": {
                    "lane": "unboxing",
                    "lane_label": "Unboxing",
                    "guid": "queued",
                    "url": "https://snips.stockbit.com/queued",
                    "source_title": "Private title marker",
                    "source_text": PRIVATE_SOURCE_TEXT,
                    "published_at": NOW.isoformat(),
                    "media_url": None,
                },
                "phase": "awaiting_agent",
                "enqueued_at": NOW.isoformat(),
                "agent_lease_until": None,
                "analysis": None,
                "rendered": None,
                "retry": {"attempts": 0, "next_attempt_at": None, "last_error": None},
            }
        },
    }
    pages = {"version": 1, "catalog_revision": 4, "lanes": lane_pages}
    (bundle / "stockbit-state.json").write_text(json.dumps(state, separators=(",", ":")))
    (bundle / "rss-pages.json").write_text(json.dumps(pages, separators=(",", ":")))
    return bundle, pages


def _run(bundle: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(bundle)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def _save_pages(bundle: Path, pages: dict[str, object]) -> None:
    (bundle / "rss-pages.json").write_text(json.dumps(pages, separators=(",", ":")))


def test_preflight_reports_four_media_bearing_previews_without_state_writes_or_source_text(tmp_path):
    bundle, _pages = _bundle(tmp_path)
    pages_path = bundle / "rss-pages.json"
    pages = json.loads(pages_path.read_text())
    for page in pages["lanes"].values():
        for item in page["items"]:
            item["media_present"] = True
    _save_pages(bundle, pages)
    original_state = (bundle / "stockbit-state.json").read_bytes()
    original_pages = pages_path.read_bytes()

    result = _run(bundle)

    assert result.returncode == 0
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["aggregate"] == {"status": "ready", "passed": 4, "required": 4, "reason": "all_lanes_previewed"}
    assert [lane["lane"] for lane in report["lanes"]] == list(LANES)
    assert {lane["status"] for lane in report["lanes"]} == {"preview"}
    assert all(lane["cursor_advanced"] is False for lane in report["lanes"])
    assert report["lanes"][0]["http_validators"] == {"etag": None, "last_modified": None}
    assert report["lanes"][0]["legacy_http_validators"] == {"etag": '"legacy-0"', "last_modified": None}
    assert report["lanes"][1]["http_validators"] == {"etag": '"page-1"', "last_modified": "Mon, 28 Sep 2026 08:00:00 GMT"}
    identity = [[(NOW + timedelta(minutes=2)).isoformat(), f"newer-{LANES[0]}"], [NOW.isoformat(), f"cursor-{LANES[0]}"], [(NOW - timedelta(minutes=2)).isoformat(), f"older-{LANES[0]}"]]
    expected_digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert report["lanes"][0]["feed_page_sha256"] == expected_digest
    assert PRIVATE_SOURCE_TEXT not in result.stdout
    assert "Private title marker" not in result.stdout
    assert (bundle / "stockbit-state.json").read_bytes() == original_state
    assert pages_path.read_bytes() == original_pages
    assert not (bundle / ".rss-preflight-state").exists()


@pytest.mark.parametrize("lane_change,missing,extra", [("missing", 1, 0), ("extra", 0, 1)])
def test_preflight_blocks_a_missing_or_extra_page_lane(tmp_path, lane_change, missing, extra):
    bundle, pages = _bundle(tmp_path)
    lanes = pages["lanes"]
    assert isinstance(lanes, dict)
    if lane_change == "missing":
        lanes.pop(LANES[-1])
    else:
        lanes["unexpected_lane"] = dict(lanes[LANES[0]])
    _save_pages(bundle, pages)

    result = _run(bundle)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["aggregate"]["status"] == "blocked"
    assert report["aggregate"]["reason"] == "lane_set_mismatch"
    assert report["aggregate"]["missing_lane_count"] == missing
    assert report["aggregate"]["extra_lane_count"] == extra
    assert report["lanes"][-1]["status"] == ("blocked" if missing else "preview")


@pytest.mark.parametrize("boundary_case,reason", [
    ("missing", "Stockbit legacy cursor GUID is absent or ambiguous in the bounded page"),
    ("duplicate", "Stockbit bounded page contains duplicate GUIDs"),
    ("mismatched", "Stockbit legacy cursor GUID publication timestamp differs from the bounded page"),
])
def test_preflight_reports_unproven_lane_boundary(tmp_path, boundary_case, reason):
    bundle, pages = _bundle(tmp_path)
    lanes = pages["lanes"]
    assert isinstance(lanes, dict)
    page = lanes[LANES[0]]
    assert isinstance(page, dict)
    items = page["items"]
    assert isinstance(items, list)
    if boundary_case == "missing":
        items.pop(1)
    elif boundary_case == "duplicate":
        items.insert(1, dict(items[1]))
    else:
        items[1]["published_at"] = (NOW - timedelta(minutes=1)).isoformat()
    _save_pages(bundle, pages)

    result = _run(bundle)

    assert result.returncode == 1
    lane_report = json.loads(result.stdout)["lanes"][0]
    assert lane_report["status"] == "blocked"
    assert lane_report["reason"] == reason
    assert "guid" not in lane_report
    assert "published_at" not in lane_report


@pytest.mark.parametrize("page_case,reason", [
    ("too_many", "Stockbit cursor preview requires a fresh page response of at most 20 items from the selected lane"),
    ("unordered", "Stockbit bounded page is not ordered by the legacy publication cursor"),
])
def test_preflight_blocks_invalid_page_size_or_order(tmp_path, page_case, reason):
    bundle, pages = _bundle(tmp_path)
    lanes = pages["lanes"]
    assert isinstance(lanes, dict)
    page = lanes[LANES[0]]
    assert isinstance(page, dict)
    items = page["items"]
    assert isinstance(items, list)
    if page_case == "too_many":
        items.extend(_article(f"extra-{index}", NOW - timedelta(minutes=index + 10)) for index in range(18))
    else:
        items.reverse()
    _save_pages(bundle, pages)

    result = _run(bundle)

    assert result.returncode == 1
    lane_report = json.loads(result.stdout)["lanes"][0]
    assert lane_report["status"] == "blocked"
    assert lane_report["reason"] == reason


def test_preflight_treats_304_as_empty_without_cursor_advance_and_preserves_validators(tmp_path):
    bundle, pages = _bundle(tmp_path)
    lanes = pages["lanes"]
    assert isinstance(lanes, dict)
    lanes[LANES[0]] = {"status": 304, "etag": '"unchanged"', "last_modified": None, "items": []}
    _save_pages(bundle, pages)

    result = _run(bundle)

    assert result.returncode == 1
    lane_report = json.loads(result.stdout)["lanes"][0]
    assert lane_report["status"] == "blocked"
    assert lane_report["poll_status"] == "empty"
    assert lane_report["cursor_advanced"] is False
    assert lane_report["http_validators"] == {"etag": '"unchanged"', "last_modified": None}
    assert lane_report["legacy_http_validators"] == {"etag": '"legacy-0"', "last_modified": None}


@pytest.mark.parametrize("field,value", [
    ("source_text", PRIVATE_SOURCE_TEXT),
    ("media_url", "https://cdn.example.test/private-thumbnail.jpg?token=hidden"),
])
def test_preflight_rejects_source_text_or_media_url_fields_without_echoing_them(tmp_path, field, value):
    bundle, pages = _bundle(tmp_path)
    lanes = pages["lanes"]
    assert isinstance(lanes, dict)
    page = lanes[LANES[0]]
    assert isinstance(page, dict)
    items = page["items"]
    assert isinstance(items, list)
    items[0][field] = value
    _save_pages(bundle, pages)

    result = _run(bundle)

    assert result.returncode == 1
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["lanes"][0]["reason"] == "page_item_shape_invalid"
    assert value not in result.stdout
    assert value not in result.stderr


@pytest.mark.parametrize("state_change,missing,extra", [("missing", 1, 0), ("extra", 0, 1)])
def test_preflight_requires_exact_legacy_state_lanes(tmp_path, state_change, missing, extra):
    bundle, _pages = _bundle(tmp_path)
    state_path = bundle / "stockbit-state.json"
    state = json.loads(state_path.read_text())
    if state_change == "missing":
        state["feeds"].pop(LANES[-1])
    else:
        state["feeds"]["unexpected_lane"] = dict(state["feeds"][LANES[0]])
    state_path.write_text(json.dumps(state, separators=(",", ":")))

    result = _run(bundle)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["aggregate"]["status"] == "blocked"
    assert report["aggregate"]["reason"] == "legacy_lane_set_mismatch"
    assert report["aggregate"]["missing_lane_count"] == missing
    assert report["aggregate"]["extra_lane_count"] == extra
    assert {lane["reason"] for lane in report["lanes"]} == {"legacy_lane_set_mismatch"}
