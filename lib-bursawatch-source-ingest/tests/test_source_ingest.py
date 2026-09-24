from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib-bursawatch-control" / "bin"))
sys.path.insert(0, str(ROOT / "lib-bursawatch-source-ingest" / "bin"))
from source_ingest import IntakeBlocked, bind_catalog_revision, ingest_all, ingest_endpoint, select_endpoints
from source_event_client import SourceEventHandoff

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
ENDPOINT = {"endpoint_id": "x:alpha", "publisher_id": "alpha", "platform": "x", "address": "alpha", "provider_id": None}


def item(identity: str, *, media: bool = False, minute: int = 0) -> dict:
    return {"provider_event_id": identity, "published_at": NOW.replace(minute=minute).isoformat(), "source_url": f"https://x.com/alpha/status/{identity}", "payload": {"text": identity}, "media_required": media}


class Inbox:
    def __init__(self):
        self.events = []
        self.fail = False

    def accept(self, envelope):
        if self.fail:
            raise OSError("inbox unavailable")
        self.events.append(envelope)
        key = hashlib.sha256(json.dumps([envelope[k] for k in ("platform", "endpoint_id", "provider_event_id")], separators=(",", ":")).encode()).hexdigest()
        return {"event_key": key, "version": 1, "duplicate": False, "work_keys": []}


def cursor(root: Path, endpoint_id: str = "x:alpha") -> dict:
    return json.loads((root / endpoint_id.replace(":", "-") / "cursor.json").read_text())


def test_empty_first_poll_initializes_and_accepts_first_later_event(tmp_path):
    inbox = Inbox()
    assert ingest_endpoint(ENDPOINT, lambda _: [], tmp_path, inbox, NOW, "fake-1")["status"] == "bootstrapped_empty"
    assert cursor(tmp_path) == {"initialized": True, "anchor": None, "position": None}
    assert ingest_endpoint(ENDPOINT, lambda _: [item("11")], tmp_path, inbox, NOW, "fake-1")["accepted"] == 1
    assert [event["provider_event_id"] for event in inbox.events] == ["11"]


def test_future_only_ack_and_spool_resume(tmp_path):
    inbox = Inbox()
    page = [item("10")]
    assert ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")["status"] == "bootstrapped"
    page.append(item("11", minute=1))
    inbox.fail = True
    with pytest.raises(OSError):
        ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert cursor(tmp_path)["anchor"] == "10"
    assert len(SourceEventHandoff(tmp_path / "x-alpha" / "handoff", inbox).spool.pending()) == 1
    inbox.fail = False
    assert ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")["accepted"] == 0
    assert cursor(tmp_path)["anchor"] == "11"
    assert [event["provider_event_id"] for event in inbox.events] == ["11"]


def test_media_and_batch_overflow_hold_only_affected_cursor(tmp_path):
    inbox = Inbox()
    ingest_endpoint(ENDPOINT, lambda _: [item("10")], tmp_path, inbox, NOW, "fake-1")
    with pytest.raises(IntakeBlocked, match="media"):
        ingest_endpoint(ENDPOINT, lambda _: [item("11", media=True, minute=1)], tmp_path, inbox, NOW, "fake-1")
    assert cursor(tmp_path)["anchor"] == "10"
    marker = json.loads((tmp_path / "x-alpha" / "blocked-media.json").read_text())
    assert marker["provider_event_id"] == "11"
    with pytest.raises(IntakeBlocked, match="batch"):
        ingest_endpoint(ENDPOINT, lambda _: [item(str(n), minute=n) for n in range(11, 32)], tmp_path, inbox, NOW, "fake-1")
    assert cursor(tmp_path)["anchor"] == "10"


def test_endpoint_isolation_and_catalog_identity(tmp_path):
    inbox = Inbox()
    other = {**ENDPOINT, "endpoint_id": "x:beta", "address": "beta"}
    selected = {"x:alpha": ENDPOINT, "x:beta": other}
    fetchers = {"x:alpha": lambda _: [item("10")], "x:beta": lambda _: [item("20")]}
    assert [row["status"] for row in ingest_all(selected, fetchers, tmp_path, inbox, NOW, "fake-1")] == ["bootstrapped", "bootstrapped"]
    fetchers = {"x:alpha": lambda _: [item("11", media=True, minute=1)], "x:beta": lambda _: [item("21", minute=1)]}
    assert [row["status"] for row in ingest_all(selected, fetchers, tmp_path, inbox, NOW, "fake-1")] == ["blocked", "accepted"]
    assert cursor(tmp_path, "x:alpha")["anchor"] == "10"
    assert cursor(tmp_path, "x:beta")["anchor"] == "21"
    row = {**ENDPOINT, "capability_id": "company_news", "enabled": True, "verification_status": "verified"}
    snapshot = {"revision": 2, "subscriptions": [row]}
    assert set(select_endpoints(snapshot, "x", {"x:alpha": ENDPOINT}, {"company_news"})) == {"x:alpha"}
    with pytest.raises(IntakeBlocked):
        select_endpoints({"revision": 2, "subscriptions": [{**row, "publisher_id": "wrong"}]}, "x", {"x:alpha": ENDPOINT}, {"company_news"})


def test_catalog_revision_change_requires_future_only_plan(tmp_path):
    bind_catalog_revision(tmp_path, 2)
    with pytest.raises(IntakeBlocked, match="future-only transition"):
        bind_catalog_revision(tmp_path, 3)
