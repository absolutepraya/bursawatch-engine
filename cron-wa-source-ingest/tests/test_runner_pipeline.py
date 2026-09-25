from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-wa-source-ingest" / "bin"))

import runner

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


class Inbox:
    def __init__(self):
        self.row = {
            "work_key": "a" * 64, "lease_token": "lease", "pipeline_id": "swing_chart_context",
            "status": "pending",
        }

    def claim(self, pipeline_ids, limit):
        assert pipeline_ids == ["swing_chart_context"] and limit == 20
        if self.row["status"] != "pending":
            return []
        self.row["status"] = "leased"
        return [dict(self.row)]

    def begin(self, work_key, lease_token):
        assert work_key == self.row["work_key"] and lease_token == "lease"
        self.row["status"] = "executing"
        return True

    def settle(self, work_key, lease_token, success, error_code=None):
        assert work_key == self.row["work_key"] and lease_token == "lease"
        self.row["status"] = "done" if success else "pending"
        return {"status": self.row["status"]}


def test_whatsapp_source_runner_dispatches_work_and_returns_existing_agent_wake(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ingest_once", lambda *_args, **_kwargs: [{"status": "accepted", "accepted": 1}])
    inbox = Inbox()
    handled = []
    handler = lambda item: handled.append(item["work_key"])
    agent = {"wakeAgent": True, "item": {"event_key": "bri-event"}}

    result = runner.run_once(
        {"revision": 4}, (), tmp_path / "queue", tmp_path / "state", inbox, NOW,
        handlers={"swing_chart_context": handler}, agent_claim=lambda: agent,
    )

    assert result["source"] == [{"status": "accepted", "accepted": 1}]
    assert result["work"] == [{"work_key": "a" * 64, "status": "done"}]
    assert handled == ["a" * 64]
    assert result["wakeAgent"] is True and result["item"]["event_key"] == "bri-event"
