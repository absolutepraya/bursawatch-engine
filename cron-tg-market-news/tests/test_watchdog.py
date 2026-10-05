from __future__ import annotations

from datetime import datetime, timedelta

import watchdog
import delivery
from state import empty_state, save_state


def test_watchdog_detects_stale_poll_after_ten_minutes(tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    state = empty_state()
    state["last_poll_success"] = "2026-07-14T08:19:59+07:00"
    save_state(state, tmp_state)

    assert watchdog.is_stale(state, datetime.fromisoformat("2026-07-14T08:30:00+07:00"))
    state["last_poll_success"] = "2026-07-14T08:20:00+07:00"
    assert not watchdog.is_stale(state, datetime.fromisoformat("2026-07-14T08:30:00+07:00"))


def test_watchdog_deduplicates_a_fatal_per_hour(tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    notices = []
    monkeypatch.setattr(watchdog.scan, "delivery_client_from_environment", lambda: object())
    monkeypatch.setattr(
        watchdog.scan,
        "post_hermes_text",
        lambda content, event_key, dry_run, **kwargs: notices.append((content, event_key)) or "id",
    )
    now = datetime.fromisoformat("2026-07-14T08:30:00+07:00")

    assert watchdog.report_watchdog_fatal(now, "poll stalled", dry_run=False)
    assert not watchdog.report_watchdog_fatal(now + timedelta(minutes=1), "poll stalled", dry_run=False)
    assert len(notices) == 1


def test_watchdog_uses_shared_delivery_client_for_fatal_heartbeat(tmp_state, monkeypatch):
    monkeypatch.setenv("IDX_MARKET_NEWS_STATE_PATH", str(tmp_state))
    receipt_type = delivery.OperationReceipt

    class Owner:
        def __init__(self):
            self.submissions = []
            self.receipts = {}

        def status(self, operation_key):
            return self.receipts.get(operation_key)

        def submit(self, operation):
            self.submissions.append(operation)
            receipt = receipt_type(
                id="owner-1",
                key=operation.key,
                digest=operation.digest,
                status="delivered",
                receipt={"channel_id": operation.target["channel_id"], "message_id": "9001"},
            )
            self.receipts[operation.key] = receipt
            return receipt

        def wait(self, operation_key, timeout_seconds):
            assert timeout_seconds == delivery.DELIVERY_RECEIPT_WAIT_SECONDS
            return self.receipts[operation_key]

    delivery_owner = Owner()
    monkeypatch.setattr(watchdog.scan, "delivery_client_from_environment", lambda: delivery_owner)

    assert watchdog.report_watchdog_fatal(
        datetime.fromisoformat("2026-07-14T08:30:00+07:00"),
        "poll stalled",
        dry_run=False,
    )

    operation = delivery_owner.submissions[0]
    assert operation.key.startswith("bursawatch-market-news:watchdog-fatal-")
    assert operation.target["channel_id"] == watchdog.scan.config.active_watch_config().heartbeat_channel_id
    assert "poll stalled" in operation.payload["content"]
