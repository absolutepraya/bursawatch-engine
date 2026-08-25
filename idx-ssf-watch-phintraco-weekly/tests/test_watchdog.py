from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest

import scan
import watchdog


def test_watchdog_is_stale_after_sixty_five_minutes() -> None:
    now = datetime(2026, 7, 14, 6, 5, 1, tzinfo=scan.WIB)
    state = scan.empty_state()
    state["last_poll_success"] = (
        now - timedelta(minutes=65, seconds=1)
    ).isoformat()

    assert watchdog.is_stale(state, now) is True
    state["last_poll_success"] = (now - timedelta(minutes=65)).isoformat()
    assert watchdog.is_stale(state, now) is False


def test_watchdog_never_mutates_scanner_state_outside_notices(
    tmp_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = scan.empty_state()
    state["observed_message_id"] = 33681
    state["bootstrap_complete"] = True
    state["last_poll_success"] = (
        datetime(2026, 7, 14, 4, 0, tzinfo=scan.WIB)
    ).isoformat()
    scan.save_state(state)
    original = tmp_state.read_bytes()
    posted: list[str] = []
    monkeypatch.setattr(
        watchdog.scan,
        "post_operational_text",
        lambda content, nonce, dry_run: posted.append(content) or "message-id",
    )

    assert watchdog.run(now=datetime(2026, 7, 14, 6, 0, tzinfo=scan.WIB), dry_run=True) == 1

    assert tmp_state.read_bytes() == original
    notices = tmp_state.parent / "watchdog-notices.json"
    assert notices.is_file()
    assert json.loads(notices.read_text())["last_error_notice"] is not None
    assert posted[0].startswith("❌ idx-ssf")
