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
from source_ingest import IntakeBlocked, _write, bind_catalog_revision, envelope, ingest_all, ingest_endpoint, select_endpoints
from source_event_client import SourceEventHandoff
from legacy_cursor_seed import LegacySeedBlocked, plan_catalog_revision_transition, plan_seed, read_legacy_snapshot

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
ENDPOINT = {"endpoint_id": "x:alpha", "publisher_id": "alpha", "platform": "x", "address": "alpha", "provider_id": None, "catalog_revision": 5}
MEDIA_REF = {"ref": "10000000-0000-4000-8000-000000000001", "sha256": "a" * 64, "kind": "image", "content_type": "image/jpeg", "size_bytes": 128, "filename": "chart.jpg", "durable": True}


def item(identity: str, *, media: bool = False, media_refs: list[dict] | None = None, minute: int = 0) -> dict:
    return {"provider_event_id": identity, "published_at": NOW.replace(minute=minute).isoformat(), "source_url": f"https://x.com/alpha/status/{identity}", "payload": {"text": identity}, "media_refs": list(media_refs or []), "media_required": media}


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


def test_legacy_seed_requires_unchanged_preview_and_refuses_initialized_or_pending_state(tmp_path, monkeypatch):
    snapshot = tmp_path / "synthetic-snapshot"
    source = snapshot / "legacy.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"cursor": 10}))
    state_root = snapshot / "new"
    endpoint = {"platform": "x", "endpoint_id": "x:alpha", "publisher_id": "alpha", "address": "alpha", "provider_id": None, "catalog_revision": 5}
    raw, _ = read_legacy_snapshot(source)
    preview = plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic")
    with pytest.raises(LegacySeedBlocked, match="catalog revision"):
        plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=6, anchor="10", cursor_shape="generic", apply=True, expected_plan=preview)
    source.write_text(json.dumps({"cursor": 11}))
    with pytest.raises(LegacySeedBlocked, match="unchanged preview plan"):
        changed, _ = read_legacy_snapshot(source)
        plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=changed, catalog_revision=5, anchor="11", cursor_shape="generic", apply=True, expected_plan=preview)
    source.write_text(json.dumps({"cursor": 10}))
    raw, _ = read_legacy_snapshot(source)
    preview = plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic")
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic", apply=True, expected_plan=preview)
    with pytest.raises(LegacySeedBlocked, match="initialized source cursor"):
        plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic", apply=True, expected_plan=preview)


def test_legacy_seed_refuses_pending_source_handoff(tmp_path, monkeypatch):
    snapshot = tmp_path / "synthetic-snapshot"
    source = snapshot / "legacy.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"cursor": 10}))
    state_root = snapshot / "new"
    endpoint = {"platform": "x", "endpoint_id": "x:alpha", "publisher_id": "alpha", "address": "alpha", "provider_id": None, "catalog_revision": 5}
    pending = state_root / "x-alpha" / "handoff" / "pending.json"
    pending.parent.mkdir(parents=True)
    pending.write_text("{}")
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    with pytest.raises(LegacySeedBlocked, match="pending source handoff"):
        raw, _ = read_legacy_snapshot(source)
        plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic")


def test_legacy_seed_apply_requires_dedicated_environment_opt_in(tmp_path, monkeypatch):
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps({"cursor": 10}))
    endpoint = {"platform": "x", "endpoint_id": "x:alpha", "publisher_id": "alpha", "address": "alpha", "provider_id": None, "catalog_revision": 5}
    raw, _ = read_legacy_snapshot(source)
    preview = plan_seed(legacy_state_path=source, state_root=tmp_path / "state", endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic")
    monkeypatch.delenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", raising=False)
    with pytest.raises(LegacySeedBlocked, match="BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY=1"):
        plan_seed(legacy_state_path=source, state_root=tmp_path / "state", endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic", apply=True, expected_plan=preview)
    with pytest.raises(LegacySeedBlocked, match="unchanged preview plan"):
        plan_seed(legacy_state_path=source, state_root=tmp_path / "other-state", endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic", apply=True, expected_plan=preview)


def test_legacy_seed_atomic_create_does_not_overwrite_concurrent_cursor(tmp_path, monkeypatch):
    import legacy_cursor_seed

    source = tmp_path / "legacy.json"
    source.write_text(json.dumps({"cursor": 10}))
    state_root = tmp_path / "state"
    endpoint = {"platform": "x", "endpoint_id": "x:alpha", "publisher_id": "alpha", "address": "alpha", "provider_id": None, "catalog_revision": 5}
    raw, _ = read_legacy_snapshot(source)
    preview = plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic")
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    real_link = legacy_cursor_seed.os.link

    def concurrent_create(source_path, cursor_path):
        cursor_path.write_text("concurrent-owner")
        return real_link(source_path, cursor_path)

    monkeypatch.setattr(legacy_cursor_seed.os, "link", concurrent_create)
    with pytest.raises(LegacySeedBlocked, match="appeared during apply"):
        plan_seed(legacy_state_path=source, state_root=state_root, endpoint=endpoint, snapshot_bytes=raw, catalog_revision=5, anchor="10", cursor_shape="generic", apply=True, expected_plan=preview)
    cursor_path = state_root / "x-alpha" / "cursor.json"
    assert cursor_path.read_text() == "concurrent-owner"


def test_catalog_revision_transition_seeds_all_cursors_before_advancing_and_resumes(tmp_path, monkeypatch):
    import legacy_cursor_seed

    root = tmp_path / "state"
    root.mkdir()
    _write(root / "catalog-revision.json", {"revision": 2})
    _write(root / "x-existing" / "cursor.json", {"initialized": True, "anchor": "20", "position": None})
    sources = []
    seeds = []
    for endpoint_id, publisher, anchor in (("x:alpha", "alpha", "100"), ("x:beta", "beta", "200")):
        source = tmp_path / f"{publisher}.json"
        source.write_text(json.dumps({"anchor": anchor}))
        raw, _ = read_legacy_snapshot(source)
        endpoint = {"platform": "x", "endpoint_id": endpoint_id, "publisher_id": publisher, "address": publisher, "provider_id": None, "catalog_revision": 3}
        seeds.append({"legacy_state_path": source, "endpoint": endpoint, "snapshot_bytes": raw, "anchor": anchor, "cursor_shape": "generic"})
        sources.append(source)

    preview = plan_catalog_revision_transition(state_root=root, from_revision=2, to_revision=3, seeds=seeds)
    assert preview["status"] == "preview"
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 2}
    assert not (root / "x-alpha" / "cursor.json").exists()
    assert not (root / "x-beta" / "cursor.json").exists()

    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    original_write = legacy_cursor_seed._write_cursor_exclusive
    calls = 0

    def interrupt_after_first(path, record):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic interruption")
        original_write(path, record)

    monkeypatch.setattr(legacy_cursor_seed, "_write_cursor_exclusive", interrupt_after_first)
    with pytest.raises(OSError, match="synthetic interruption"):
        plan_catalog_revision_transition(state_root=root, from_revision=2, to_revision=3, seeds=seeds, apply=True, expected_plan=preview)
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 2}
    assert (root / "x-alpha" / "cursor.json").is_file()
    assert not (root / "x-beta" / "cursor.json").exists()

    monkeypatch.setattr(legacy_cursor_seed, "_write_cursor_exclusive", original_write)
    applied = plan_catalog_revision_transition(state_root=root, from_revision=2, to_revision=3, seeds=seeds, apply=True, expected_plan=preview)
    assert applied["status"] == "applied"
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 3}
    assert cursor(root, "x:alpha")["anchor"] == "100"
    assert cursor(root, "x:beta")["anchor"] == "200"
    journal = json.loads((root / "catalog-transitions" / "2-to-3.json").read_text())
    assert journal["status"] == "complete"
    assert set(journal["seeded_endpoints"]) == {"x:alpha", "x:beta"}

    repeated = plan_catalog_revision_transition(state_root=root, from_revision=2, to_revision=3, seeds=seeds, apply=True, expected_plan=preview)
    assert repeated["status"] == "applied"


def test_catalog_revision_transition_requires_unchanged_state_and_exact_seed_set(tmp_path, monkeypatch):
    root = tmp_path / "state"
    root.mkdir()
    _write(root / "catalog-revision.json", {"revision": 2})
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps({"anchor": "100"}))
    raw, _ = read_legacy_snapshot(source)
    endpoint = {"platform": "x", "endpoint_id": "x:alpha", "publisher_id": "alpha", "address": "alpha", "provider_id": None, "catalog_revision": 3}
    seeds = [{"legacy_state_path": source, "endpoint": endpoint, "snapshot_bytes": raw, "anchor": "100", "cursor_shape": "generic"}]
    preview = plan_catalog_revision_transition(state_root=root, from_revision=2, to_revision=3, seeds=seeds)
    _write(root / "unrelated.json", {"changed": True})
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")
    with pytest.raises(LegacySeedBlocked, match="unchanged catalog transition preview"):
        plan_catalog_revision_transition(state_root=root, from_revision=2, to_revision=3, seeds=seeds, apply=True, expected_plan=preview)
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 2}


def test_acknowledged_handoff_recovery_preserves_staged_publication_time(tmp_path):
    inbox = Inbox()
    endpoint = dict(ENDPOINT)
    state_root = tmp_path / "state"
    endpoint_root = state_root / "x-alpha"
    cursor_path = endpoint_root / "cursor.json"
    _write(cursor_path, {"initialized": True, "anchor": "10", "position": None})
    event = envelope(endpoint, item("11", minute=3), NOW, "fake-1")
    handoff = SourceEventHandoff(endpoint_root / "handoff", inbox)
    handoff.stage(event)
    _write(endpoint_root / "pending-position.json", {"envelope": event, "position": None})
    later = event["published_at"]
    result = ingest_endpoint(endpoint, lambda _: [], state_root, inbox, NOW, "fake-1")
    assert result["status"] == "empty"
    assert inbox.events[0]["provider_event_id"] == "11"
    assert cursor(state_root)["anchor"] == "11"
    assert cursor(state_root)["boundary_published_at"] == later


def test_empty_first_poll_initializes_and_accepts_first_later_event(tmp_path):
    inbox = Inbox()
    assert ingest_endpoint(ENDPOINT, lambda _: [], tmp_path, inbox, NOW, "fake-1")["status"] == "bootstrapped_empty"
    assert cursor(tmp_path) == {"initialized": True, "anchor": None, "position": None}
    assert ingest_endpoint(ENDPOINT, lambda _: [item("11")], tmp_path, inbox, NOW, "fake-1")["accepted"] == 1
    assert [event["provider_event_id"] for event in inbox.events] == ["11"]


def test_unmarked_numeric_endpoint_blocks_when_anchor_falls_off(tmp_path):
    endpoint_root = tmp_path / "x-alpha"
    _write(endpoint_root / "cursor.json", {"initialized": True, "anchor": "10", "position": None})
    inbox = Inbox()
    page = {"items": [item("11"), item("12")], "truncated": False, "contiguous": False}
    result = ingest_all({"x:alpha": ENDPOINT}, {"x:alpha": lambda _: page}, tmp_path, inbox, NOW, "fake-1")
    assert result == [{"endpoint_id": "x:alpha", "status": "blocked", "reason": "source_blocked"}]
    assert inbox.events == []


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


def test_complete_anchored_page_drains_over_two_bounded_polls(tmp_path):
    inbox = Inbox()
    page = {"items": [item("10")], "truncated": False, "contiguous": False}
    assert ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")["status"] == "bootstrapped"
    page["items"].extend(item(str(identity)) for identity in range(11, 32))

    first = ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert first["accepted"] == 20
    assert cursor(tmp_path)["anchor"] == "30"
    assert [event["provider_event_id"] for event in inbox.events] == [str(identity) for identity in range(11, 31)]

    second = ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert second["accepted"] == 1
    assert cursor(tmp_path)["anchor"] == "31"
    assert [event["provider_event_id"] for event in inbox.events] == [str(identity) for identity in range(11, 32)]


def test_empty_bootstrap_backlog_drains_in_two_bounded_polls(tmp_path):
    inbox = Inbox()
    assert ingest_endpoint(ENDPOINT, lambda _: [], tmp_path, inbox, NOW, "fake-1")["status"] == "bootstrapped_empty"
    page = {"items": [item(str(identity)) for identity in range(1, 22)], "truncated": False, "contiguous": False}

    first = ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert first["accepted"] == 20
    assert cursor(tmp_path)["anchor"] == "20"
    assert [event["provider_event_id"] for event in inbox.events] == [str(identity) for identity in range(1, 21)]

    second = ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert second["accepted"] == 1
    assert cursor(tmp_path)["anchor"] == "21"
    assert [event["provider_event_id"] for event in inbox.events] == [str(identity) for identity in range(1, 22)]


def test_saturated_page_with_visible_anchor_drains_in_bounded_polls(tmp_path):
    inbox = Inbox()
    ingest_endpoint(ENDPOINT, lambda _: [item("10")], tmp_path, inbox, NOW, "fake-1")
    page = {"items": [item(str(identity)) for identity in range(10, 110)], "truncated": True, "contiguous": False}

    accepted = []
    for _ in range(5):
        result = ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
        assert result["accepted"] <= 20
        accepted.append(result["accepted"])

    assert accepted == [20, 20, 20, 20, 19]
    assert cursor(tmp_path)["anchor"] == "109"
    assert [event["provider_event_id"] for event in inbox.events] == [str(identity) for identity in range(11, 110)]


def test_truncated_page_without_old_anchor_blocks_and_retains_cursor(tmp_path):
    inbox = Inbox()
    ingest_endpoint(ENDPOINT, lambda _: [item("10")], tmp_path, inbox, NOW, "fake-1")
    page = {"items": [item(str(identity)) for identity in range(11, 32)], "truncated": True, "contiguous": False}

    with pytest.raises(IntakeBlocked, match="truncated"):
        ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")

    assert cursor(tmp_path)["anchor"] == "10"
    assert inbox.events == []


def test_contiguous_partial_batch_does_not_advance_scanned_through(tmp_path):
    inbox = Inbox()
    bootstrap = item("10")
    bootstrap["ingest_position"] = "001"
    ingest_endpoint(ENDPOINT, lambda _: {"items": [bootstrap], "truncated": False, "contiguous": True}, tmp_path, inbox, NOW, "fake-1")
    page_items = []
    for position, identity in enumerate(range(11, 36), start=2):
        row = item(str(identity))
        row["ingest_position"] = f"{position:03}"
        page_items.append(row)
    page = {"items": page_items, "truncated": False, "contiguous": True, "scanned_through": "999"}

    first = ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert first["accepted"] == 20
    assert cursor(tmp_path)["position"] == "021"
    assert [event["provider_event_id"] for event in inbox.events] == [str(identity) for identity in range(11, 31)]

    second = ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert second["accepted"] == 5
    assert cursor(tmp_path)["position"] == "999"
    assert [event["provider_event_id"] for event in inbox.events] == [str(identity) for identity in range(11, 36)]


def test_media_block_holds_only_affected_cursor(tmp_path):
    inbox = Inbox()
    ingest_endpoint(ENDPOINT, lambda _: [item("10")], tmp_path, inbox, NOW, "fake-1")
    with pytest.raises(IntakeBlocked, match="media"):
        ingest_endpoint(ENDPOINT, lambda _: [item("10"), item("11", media=True, minute=1)], tmp_path, inbox, NOW, "fake-1")
    assert cursor(tmp_path)["anchor"] == "10"
    marker = json.loads((tmp_path / "x-alpha" / "blocked-media.json").read_text())
    assert marker["provider_event_id"] == "11"


def test_durable_media_refs_survive_spool_retry_and_ack(tmp_path):
    inbox = Inbox()
    ingest_endpoint(ENDPOINT, lambda _: [item("10")], tmp_path, inbox, NOW, "fake-1")
    page = [item("10"), item("11", media=True, media_refs=[MEDIA_REF], minute=1)]
    inbox.fail = True
    with pytest.raises(OSError):
        ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")
    assert cursor(tmp_path)["anchor"] == "10"
    pending = SourceEventHandoff(tmp_path / "x-alpha" / "handoff", inbox).spool.pending()
    assert pending[0].payload["envelope"]["media_refs"] == [MEDIA_REF]
    inbox.fail = False
    assert ingest_endpoint(ENDPOINT, lambda _: page, tmp_path, inbox, NOW, "fake-1")["accepted"] == 0
    assert cursor(tmp_path)["anchor"] == "11"
    assert len(inbox.events) == 1
    assert inbox.events[0]["media_refs"] == [MEDIA_REF]
    assert inbox.events[0]["media_required"] is True


def test_media_references_are_validated_before_inbox_acceptance(tmp_path):
    inbox = Inbox()
    ingest_endpoint(ENDPOINT, lambda _: [item("10")], tmp_path, inbox, NOW, "fake-1")
    invalid = {**MEDIA_REF, "content_type": "video/mp4"}
    with pytest.raises(IntakeBlocked, match="media"):
        ingest_endpoint(ENDPOINT, lambda _: [item("10"), item("11", media=True, media_refs=[invalid], minute=1)], tmp_path, inbox, NOW, "fake-1")
    assert cursor(tmp_path)["anchor"] == "10"
    assert inbox.events == []


def test_endpoint_isolation_and_catalog_identity(tmp_path):
    inbox = Inbox()
    other = {**ENDPOINT, "endpoint_id": "x:beta", "address": "beta"}
    selected = {"x:alpha": ENDPOINT, "x:beta": other}
    fetchers = {"x:alpha": lambda _: [item("10")], "x:beta": lambda _: [item("20")]}
    assert [row["status"] for row in ingest_all(selected, fetchers, tmp_path, inbox, NOW, "fake-1")] == ["bootstrapped", "bootstrapped"]
    fetchers = {"x:alpha": lambda _: [item("10"), item("11", media=True, minute=1)], "x:beta": lambda _: [item("20"), item("21", minute=1)]}
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
