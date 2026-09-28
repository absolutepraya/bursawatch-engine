from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from datetime import datetime, timezone

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cron-rss-source-ingest" / "bin" / "handoff.py"
sys.path.insert(0, str(ROOT / "cron-stockbit-snips" / "bin"))
import discord as stockbit_discord
LANES = ("stockbit_commentary", "unboxing", "unboxing_ipo", "ai_reports_stockbit")
NOW = "2026-09-28T04:00:00+00:00"
PRIVATE_SOURCE_TEXT = "private source text must not appear in migration output"
SNAPSHOT_CONFIG = {
    "revision": 1,
    "additional_prompt_instruction": "",
    "id_stocks_news_channel_id": "1525102508714889257",
    "macro_news_channel_id": "1531655369884045382",
}


def _bundle(root: Path, *, pending: bool = False, delivered: bool = False) -> tuple[Path, Path]:
    bundle = root / "operator-bundle"
    bundle.mkdir()
    feeds: dict[str, object] = {}
    lanes: dict[str, object] = {}
    for index, lane in enumerate(LANES):
        guid = f"legacy-guid-{lane}"
        feeds[lane] = {
            "cursor": {"published_at": NOW, "guid": guid},
            "etag": f'"old-{index}"',
            "last_modified": None,
            "last_poll_success": NOW,
            "last_error": None,
            "enabled": True,
        }
        lanes[lane] = {
            "status": 200,
            "etag": None if index == 0 else f'"page-{index}"',
            "last_modified": None if index % 2 == 0 else "Mon, 28 Sep 2026 04:00:00 GMT",
            "items": [
                {"guid": f"newer-{lane}", "published_at": "2026-09-28T04:02:00+00:00", "media_present": False},
                {"guid": guid, "published_at": NOW, "media_present": False},
                {"guid": f"older-{lane}", "published_at": "2026-09-28T03:58:00+00:00", "media_present": False},
            ],
        }
    articles: dict[str, object] = {}
    receipts: list[dict[str, object]] = []
    if delivered:
        key = "stockbit:unboxing:delivered-guid"
        rendered = "Previously accepted Stockbit message"
        channel = SNAPSHOT_CONFIG["macro_news_channel_id"]
        operation, _nonce = stockbit_discord._operation(rendered, channel, key, "news")
        articles[key] = {
            "article": {
                "lane": "unboxing", "lane_label": "Unboxing", "guid": "delivered-guid",
                "url": "https://snips.stockbit.com/delivered", "source_title": "Private title",
                "source_text": PRIVATE_SOURCE_TEXT, "published_at": NOW, "media_url": None,
            },
            "phase": "delivered",
            "enqueued_at": NOW,
            "agent_lease_until": None,
            "analysis": {"route": "macro_news"},
            "rendered": rendered,
            "delivery": {"channel_id": channel, "message_id": "123456789012345678", "delivered_at": NOW},
            "retry": {"attempts": 0, "next_attempt_at": None, "last_error": None},
            "config_snapshot": SNAPSHOT_CONFIG,
        }
        receipts.append({
            "operation_key_sha256": hashlib.sha256(operation.key.encode()).hexdigest(),
            "digest": operation.digest,
            "status": "delivered",
            "receipt": {"channel_id": channel, "message_id": "123456789012345678"},
        })
    state: dict[str, object] = {
        "version": 2,
        "feeds": feeds,
        "articles": articles,
    }
    if pending:
        state["articles"] = {
            "stockbit:unboxing:queued": {
                "article": {
                    "lane": "unboxing", "lane_label": "Unboxing", "guid": "queued",
                    "url": "https://snips.stockbit.com/queued", "source_title": "Private title",
                    "source_text": PRIVATE_SOURCE_TEXT, "published_at": NOW, "media_url": None,
                },
                "phase": "awaiting_agent",
                "enqueued_at": NOW,
                "agent_lease_until": None,
                "analysis": None,
                "rendered": None,
                "retry": {"attempts": 0, "next_attempt_at": None, "last_error": None},
                "config_snapshot": SNAPSHOT_CONFIG,
            }
        }
    pages = {"version": 1, "catalog_revision": 4, "lanes": lanes}
    _write(bundle / "stockbit-state.json", state)
    _write(bundle / "rss-pages.json", pages)
    _write(bundle / "delivery-receipts.json", {"version": 1, "receipts": receipts})
    _write(bundle / "migration-context.json", {
        "version": 1,
        "snapshot_taken_at": datetime.now(timezone.utc).isoformat(),
        "watch_config_revision": 1,
        "source_catalog_revision": 4,
        "legacy_job_id": "0c6b17e4c944",
        "legacy_reader_paused": True,
        "legacy_inflight_runs": 0,
    })
    return bundle, root / "bursawatch-rss-source-ingest"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _run(mode: str, bundle: Path, state_root: Path, *, expected: str | None = None, gate: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT), mode, "--bundle-dir", str(bundle), "--state-root", str(state_root)]
    if expected is not None:
        command.extend(["--expected-plan-sha256", expected])
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if gate:
        environment["BURSAWATCH_RSS_HANDOFF_ALLOW_APPLY"] = "1"
    else:
        environment.pop("BURSAWATCH_RSS_HANDOFF_ALLOW_APPLY", None)
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=10, env=environment)


def test_handoff_plan_and_apply_seed_only_new_rss_state_atomically(tmp_path: Path):
    bundle, state_root = _bundle(tmp_path, delivered=True)
    original = {path.name: path.read_bytes() for path in bundle.iterdir()}

    plan_result = _run("--plan", bundle, state_root)

    assert plan_result.returncode == 0, plan_result.stderr
    assert plan_result.stderr == ""
    plan = json.loads(plan_result.stdout)
    assert plan["aggregate"]["status"] == "ready"
    assert plan["aggregate"]["required_lanes"] == 4
    assert plan["snapshot"]["article_phase_counts"] == {"delivered": 1}
    assert plan["snapshot"]["frozen_config_revisions"] == {"1": 1}
    assert plan["snapshot"]["delivery_receipt_count"] == 1
    assert plan["snapshot"]["delivery_receipts_reconciled"] is True
    assert not state_root.exists()
    assert PRIVATE_SOURCE_TEXT not in plan_result.stdout
    assert "legacy-guid-" not in plan_result.stdout

    apply_result = _run("--apply", bundle, state_root, expected=plan["plan_sha256"], gate=True)

    assert apply_result.returncode == 0, apply_result.stderr
    applied = json.loads(apply_result.stdout)
    assert applied["outcome"] == "applied"
    assert applied["state_root"] == str(state_root)
    assert stat.S_IMODE(state_root.stat().st_mode) == 0o700
    assert {path.name: path.read_bytes() for path in bundle.iterdir()} == original
    cursor_paths = sorted(state_root.glob("rss-stockbit-*/cursor.json"))
    assert len(cursor_paths) == 4
    for path in cursor_paths:
        lane = path.parent.name.removeprefix("rss-stockbit-")
        cursor = json.loads(path.read_text())
        assert cursor["initialized"] is True
        assert cursor["position"] is None
        assert cursor["anchor"] == hashlib.sha256(f"legacy-guid-{lane}".encode()).hexdigest()
        assert cursor["boundary_published_at"] == NOW
        assert cursor["legacy_seed"]["legacy_state_sha256"] == plan["snapshot"]["stockbit_state_sha256"]
        assert f"legacy-guid-{lane}" not in path.read_text()
    validator = json.loads((state_root / "rss-stockbit-stockbit_commentary" / "http-validators.json").read_text())
    assert validator == {"version": 1, "etag": None, "last_modified": None}
    assert json.loads((state_root / "catalog-revision.json").read_text()) == {"revision": 4}
    assert json.loads((state_root / "watch-config-revision.json").read_text()) == {"revision": 1}
    receipt = json.loads((state_root / "legacy-cutover-receipt.json").read_text())
    assert receipt["version"] == 1
    assert receipt["lane_count"] == 4
    assert PRIVATE_SOURCE_TEXT not in json.dumps(receipt)
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in state_root.rglob("*") if path.is_file())
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in state_root.rglob("*") if path.is_dir())
    assert not list(tmp_path.glob(".bursawatch-rss-source-ingest.handoff-*"))


def test_handoff_apply_requires_explicit_gate_and_matching_plan_digest(tmp_path: Path):
    bundle, state_root = _bundle(tmp_path)
    plan = json.loads(_run("--plan", bundle, state_root).stdout)

    no_gate = _run("--apply", bundle, state_root, expected=plan["plan_sha256"])
    bad_digest = _run("--apply", bundle, state_root, expected="0" * 64, gate=True)

    assert no_gate.returncode == 1
    assert json.loads(no_gate.stdout)["aggregate"]["reason"].startswith("apply authorization")
    assert bad_digest.returncode == 1
    assert "changed after planning" in json.loads(bad_digest.stdout)["aggregate"]["reason"]
    assert not state_root.exists()


def test_handoff_refuses_pending_legacy_article_work_without_writes(tmp_path: Path):
    bundle, state_root = _bundle(tmp_path, pending=True)

    result = _run("--plan", bundle, state_root)

    assert result.returncode == 1
    plan = json.loads(result.stdout)
    assert plan["aggregate"]["status"] == "blocked"
    assert plan["aggregate"]["reason"] == "legacy_owner_work_pending"
    assert plan["snapshot"]["article_phase_counts"] == {"awaiting_agent": 1}
    assert PRIVATE_SOURCE_TEXT not in result.stdout
    assert not state_root.exists()


def test_handoff_refuses_media_and_304_without_writes(tmp_path: Path):
    bundle, state_root = _bundle(tmp_path)
    pages_path = bundle / "rss-pages.json"
    pages = json.loads(pages_path.read_text())
    pages["lanes"][LANES[0]]["items"][0]["media_present"] = True
    pages["lanes"][LANES[1]] = {
        "status": 304, "etag": None, "last_modified": '"unchanged"', "items": [],
    }
    _write(pages_path, pages)

    result = _run("--plan", bundle, state_root)

    assert result.returncode == 1
    plan = json.loads(result.stdout)
    assert plan["aggregate"]["status"] == "blocked"
    assert plan["lanes"][0]["reason"] == "media_item_present"
    assert plan["lanes"][1]["poll_status"] == "empty"
    assert plan["lanes"][1]["cursor_advanced"] is False
    assert not state_root.exists()


def test_handoff_refuses_inconsistent_delivery_receipt_snapshot(tmp_path: Path):
    bundle, state_root = _bundle(tmp_path)
    receipts_path = bundle / "delivery-receipts.json"
    _write(receipts_path, {"version": 1, "receipts": [{
        "operation_key_sha256": "a" * 64,
        "digest": "b" * 64,
        "status": "delivered",
        "receipt": {"channel_id": "1525102508714889257", "message_id": "123456789012345678"},
    }]})

    result = _run("--plan", bundle, state_root)

    assert result.returncode == 1
    plan = json.loads(result.stdout)
    assert plan["aggregate"]["reason"] == "delivery_receipt_inventory_mismatch"
    assert not state_root.exists()


def test_handoff_rejects_bundle_changed_after_plan(tmp_path: Path):
    bundle, state_root = _bundle(tmp_path)
    plan = json.loads(_run("--plan", bundle, state_root).stdout)
    context_path = bundle / "migration-context.json"
    context = json.loads(context_path.read_text())
    context["watch_config_revision"] = 2
    _write(context_path, context)

    result = _run("--apply", bundle, state_root, expected=plan["plan_sha256"], gate=True)

    assert result.returncode == 1
    assert json.loads(result.stdout)["aggregate"]["reason"] == "snapshot or plan changed after planning"
    assert not state_root.exists()


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"legacy_reader_paused": False}, "legacy_reader_not_paused"),
        ({"legacy_inflight_runs": 1}, "legacy_reader_inflight"),
        ({"snapshot_taken_at": "2026-09-28T04:00:00+00:00"}, "snapshot_stale"),
    ],
)
def test_handoff_requires_quiesced_reader_and_fresh_snapshot(tmp_path: Path, change, reason):
    bundle, state_root = _bundle(tmp_path)
    context_path = bundle / "migration-context.json"
    context = json.loads(context_path.read_text())
    context.update(change)
    _write(context_path, context)

    result = _run("--plan", bundle, state_root)

    assert result.returncode == 1
    assert json.loads(result.stdout)["aggregate"]["reason"] == reason
    assert not state_root.exists()
