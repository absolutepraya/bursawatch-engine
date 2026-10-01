from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cron-rss-source-ingest" / "bin" / "runner.py"
PRIVATE_SOURCE_TEXT = "private source text must not appear in heartbeat"
sys.path.insert(0, str(ROOT / "cron-rss-source-ingest" / "bin"))
from runner import run_once, send_heartbeat
import runner as rss_runner
sys.path.insert(0, str(ROOT / "cron-stockbit-snips" / "bin"))
from config import FEEDS, LoadedStockbitConfig, load_watch_config_data


def test_runner_synthetic_verification_uses_no_network_secrets_or_writes(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    environment = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TZ": "Asia/Jakarta",
        "LANG": "C.UTF-8",
    }

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--verify-synthetic"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["outcome"] == "synthetic-ok"
    assert report["network"] is False
    assert report["secrets"] is False
    assert report["writes"] is False
    assert report["events"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", report["content_hash"])
    assert list(home.iterdir()) == []


def test_runner_blocks_invalid_transition_chain_but_settles_existing_work(tmp_path: Path, monkeypatch):
    now = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
    settings = {
        "version": 1,
        "feeds": [{"id": feed.lane.value, "enabled": True} for feed in FEEDS],
        "destinations": {
            "id_stocks_news_channel_id": "1525102508714889257",
            "macro_news_channel_id": "1531655369884045382",
        },
        "additional_prompt_instruction": "",
    }
    loaded = LoadedStockbitConfig(load_watch_config_data(settings), 7)
    snapshot = {
        "revision": 7,
        "subscriptions": [
            {
                "platform": "rss",
                "endpoint_id": f"rss:stockbit:{feed.lane.value}",
                "publisher_id": "stockbit",
                "address": feed.url,
                "provider_id": feed.lane.value,
                "capability_id": "stockbit_snips",
                "verification_status": "verified",
                "enabled": True,
            }
            for feed in FEEDS
        ],
    }
    root = tmp_path / "bursawatch-rss-source-ingest"
    root.mkdir()
    (root / "catalog-revision.json").write_text('{"revision":7}', encoding="utf-8")
    (root / "watch-config-revision.json").write_text('{"revision":7}', encoding="utf-8")
    for feed in FEEDS:
        lane = feed.lane.value
        endpoint_id = f"rss:stockbit:{lane}"
        endpoint = {
            "platform": "rss",
            "endpoint_id": endpoint_id,
            "publisher_id": "stockbit",
            "address": feed.url,
            "provider_id": lane,
        }
        anchor = hashlib.sha256(f"legacy-{lane}".encode()).hexdigest()
        lane_root = root / endpoint_id.replace(":", "-")
        lane_root.mkdir()
        (lane_root / "cursor.json").write_text(json.dumps({
            "initialized": True,
            "anchor": anchor,
            "position": None,
            "boundary_published_at": now.isoformat(),
            "legacy_seed": {
                "legacy_state_sha256": "a" * 64,
                "endpoint": endpoint,
                "catalog_revision": 4,
                "proposed_anchor": anchor,
                "cursor_shape": "generic",
                "boundary_timestamp": now.isoformat(),
            },
        }, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        (lane_root / "http-validators.json").write_text(
            '{"version":1,"etag":null,"last_modified":null}', encoding="utf-8"
        )

    work_item = {"work_key": "accepted-work", "lease_token": "lease", "pipeline_id": "stockbit_snips"}
    calls = []

    class Inbox:
        def claim(self, pipelines, limit):
            calls.append(("claim", pipelines, limit))
            return [work_item]

        def begin(self, work_key, lease_token):
            calls.append(("begin", work_key, lease_token))
            return True

        def settle(self, work_key, lease_token, success, *_args):
            calls.append(("settle", work_key, lease_token, success))
            return {"status": "done"}

    owner_calls = []

    def owner_command(command):
        owner_calls.append(command)
        if command == "agent-status":
            return {
                "ready": True,
                "pipeline_id": "stockbit_snips",
                "event_key": "b" * 64,
                "published_at": now.isoformat(),
            }
        assert command == "claim-agent"
        return {"wakeAgent": False, "items": []}

    handled = []
    real_guard = rss_runner.require_legacy_cursor_seed

    def observe_effective_inputs(state_root, effective_snapshot, effective_config):
        assert effective_snapshot is snapshot
        assert effective_config is loaded
        return real_guard(state_root, effective_snapshot, effective_config)

    monkeypatch.setattr(rss_runner, "require_legacy_cursor_seed", observe_effective_inputs)
    result = run_once(
        snapshot,
        loaded,
        root,
        Inbox(),
        now,
        fetch_feed=lambda *_args, **_kwargs: pytest.fail("invalid journal chain must block before feed fetch"),
        handler=handled.append,
        owner_command=owner_command,
        require_legacy_seed=True,
    )

    assert result["source"] == [{
        "endpoint_id": "rss:stockbit",
        "status": "blocked",
        "reason": "migration_cursor_handoff_invalid",
    }]
    assert result["work"] == [{"work_key": "accepted-work", "status": "done"}]
    assert handled == [work_item]
    assert owner_calls == ["agent-status", "claim-agent"]
    assert [call[0] for call in calls] == ["claim", "begin", "settle"]


def test_reader_heartbeat_uses_delivery_owner_and_contains_only_counts():
    calls = []
    result = {
        "source": [
            {"endpoint_id": "rss:stockbit:unboxing", "status": "accepted", "accepted": 2, "fetched": 4},
            {"endpoint_id": "rss:stockbit:unboxing_ipo", "status": "empty", "accepted": 0, "fetched": 0},
            {"endpoint_id": "rss:stockbit:ai_reports_stockbit", "status": "blocked", "reason": "media_blocked", "accepted": 0, "fetched": 0},
        ],
        "work": [{"work_key": "opaque", "status": "done"}],
        "wakeAgent": True,
        "items": [{"source_title": PRIVATE_SOURCE_TEXT}],
    }

    send_heartbeat(
        result,
        datetime(2026, 9, 28, 4, 22, tzinfo=timezone.utc),
        pending_count=3,
        post_text=lambda content, channel, **kwargs: calls.append((content, channel, kwargs)),
    )

    assert len(calls) == 1
    content, channel, kwargs = calls[0]
    assert channel == "1505162000420835388"
    assert content == "🫀 stockbit-snips · 11:22 WIB · 4 fetched · 2 queued · 0 delivered · 1 errors · 3 pending ⚠️"
    assert kwargs == {"dry_run": False, "event_key": "heartbeat:202609281122", "leg": "heartbeat"}
    assert PRIVATE_SOURCE_TEXT not in content
