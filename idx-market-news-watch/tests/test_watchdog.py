from __future__ import annotations

from datetime import datetime, timedelta

import watchdog
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
    monkeypatch.setattr(watchdog.scan, "post_hermes_text", lambda content, event_key, dry_run: notices.append((content, event_key)) or "id")
    now = datetime.fromisoformat("2026-07-14T08:30:00+07:00")

    assert watchdog.report_watchdog_fatal(now, "poll stalled", dry_run=False)
    assert not watchdog.report_watchdog_fatal(now + timedelta(minutes=1), "poll stalled", dry_run=False)
    assert len(notices) == 1
