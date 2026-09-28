from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "cron-rss-source-ingest" / "bin" / "runner.py"
PRIVATE_SOURCE_TEXT = "private source text must not appear in heartbeat"
sys.path.insert(0, str(ROOT / "cron-rss-source-ingest" / "bin"))
from runner import send_heartbeat


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
