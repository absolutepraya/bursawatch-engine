from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-rss-source-ingest" / "bin"))
from adapter import endpoints, plan_legacy_cursor_seed, require_legacy_cursor_seed, run_once
from runner import run_once as run_pipeline

sys.path.insert(0, str(ROOT / "cron-stockbit-snips" / "bin"))
from config import FEEDS, LoadedStockbitConfig, load_watch_config_data
from models import Article
from rss import FetchResult
from source_ingest import IntakeBlocked
import pipeline_owner

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def test_stockbit_legacy_cursor_plan_stays_blocked_without_page_proof(tmp_path):
    source = tmp_path / "snapshot" / "stockbit.json"
    source.parent.mkdir()
    source.write_text(json.dumps({"feeds": {}, "articles": {}}))
    result = plan_legacy_cursor_seed(source, {"platform": "rss", "endpoint_id": "rss:stockbit:unboxing", "publisher_id": "stockbit", "address": "https://snips.stockbit.com/feed", "provider_id": "unboxing"}, 4)
    assert result["status"] == "blocked"
    assert "GUID" in result["reason"]
    assert result["proposed_cursor"] is None
    assert result["legacy_state_sha256"]


def test_stockbit_legacy_cursor_preview_requires_exact_bounded_page_proof(tmp_path):
    snapshot, loaded = snapshot_and_config()
    selected, _feeds = endpoints(snapshot, loaded)
    feed = FEEDS[0]
    endpoint = selected[f"rss:stockbit:{feed.lane.value}"]
    boundary = Article(feed.lane, feed.label, "legacy-guid", "https://snips.stockbit.com/legacy", "Boundary", "Boundary body", NOW)
    older = Article(feed.lane, feed.label, "older-guid", "https://snips.stockbit.com/older", "Older", "Older body", NOW - timedelta(minutes=1))
    newer = Article(feed.lane, feed.label, "newer-guid", "https://snips.stockbit.com/newer", "Newer", "Newer body", NOW + timedelta(minutes=1))
    legacy_path = tmp_path / "snapshot" / "stockbit.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({"feeds": {feed.lane.value: {"cursor": {"published_at": boundary.published_at.isoformat(), "guid": boundary.guid}, "etag": '"legacy-etag"', "last_modified": "Sun, 27 Sep 2026 08:00:00 GMT"}}, "articles": {}}))
    state_root = tmp_path / "new-state"
    page = FetchResult(feed, (newer, boundary, older), '"page-etag"', "Mon, 28 Sep 2026 08:00:00 GMT", False)

    preview = plan_legacy_cursor_seed(legacy_path, endpoint, snapshot["revision"], state_root=state_root, page=page)

    assert preview["status"] == "preview"
    assert preview["apply"] is False
    assert preview["proposed_anchor"] == hashlib.sha256(boundary.guid.encode()).hexdigest()
    assert preview["boundary_timestamp"] == boundary.published_at.isoformat()
    assert preview["feed_page_item_count"] == 3
    assert preview["http_validators"] == {"etag": '"page-etag"', "last_modified": "Mon, 28 Sep 2026 08:00:00 GMT"}
    page_identity = [(article.published_at.isoformat(), article.guid) for article in (newer, boundary, older)]
    expected_page_hash = hashlib.sha256(json.dumps(page_identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert preview["feed_page_sha256"] == expected_page_hash
    assert not state_root.exists()


@pytest.mark.parametrize("boundary_mode", ["missing", "duplicate", "timestamp_mismatch", "not_modified"])
def test_stockbit_legacy_cursor_preview_blocks_unproven_boundary(tmp_path, boundary_mode):
    snapshot, loaded = snapshot_and_config()
    selected, _feeds = endpoints(snapshot, loaded)
    feed = FEEDS[0]
    endpoint = selected[f"rss:stockbit:{feed.lane.value}"]
    legacy_path = tmp_path / "snapshot" / "stockbit.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({"feeds": {feed.lane.value: {"cursor": {"published_at": NOW.isoformat(), "guid": "legacy-guid"}}}, "articles": {}}))
    boundary = Article(feed.lane, feed.label, "legacy-guid", "https://snips.stockbit.com/legacy", "Boundary", "Boundary body", NOW)
    other = Article(feed.lane, feed.label, "other-guid", "https://snips.stockbit.com/other", "Other", "Other body", NOW - timedelta(minutes=1))
    if boundary_mode == "missing":
        articles = (other,)
        not_modified = False
    elif boundary_mode == "duplicate":
        articles = (boundary, boundary, other)
        not_modified = False
    elif boundary_mode == "timestamp_mismatch":
        articles = (Article(feed.lane, feed.label, "legacy-guid", boundary.url, boundary.source_title, boundary.source_text, NOW + timedelta(seconds=1)), other)
        not_modified = False
    else:
        articles = ()
        not_modified = True
    page = FetchResult(feed, articles, '"page-etag"', None, not_modified)

    result = plan_legacy_cursor_seed(legacy_path, endpoint, snapshot["revision"], state_root=tmp_path / "new-state", page=page)

    assert result["status"] == "blocked"
    assert result["apply"] is False
    assert result["proposed_cursor"] is None
    assert result["legacy_state_sha256"]


def test_stockbit_saturated_page_without_legacy_guid_never_bootstraps_latest(tmp_path):
    snapshot, loaded = snapshot_and_config()
    selected, _feeds = endpoints(snapshot, loaded)
    feed = FEEDS[0]
    endpoint = selected[f"rss:stockbit:{feed.lane.value}"]
    legacy_path = tmp_path / "snapshot" / "stockbit.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(json.dumps({"feeds": {feed.lane.value: {"cursor": {"published_at": NOW.isoformat(), "guid": "legacy-guid"}}}, "articles": {}}))
    articles = tuple(
        Article(feed.lane, feed.label, f"page-{index:02}", f"https://snips.stockbit.com/{index}", "Page item", "Page body", NOW - timedelta(minutes=index))
        for index in range(20)
    )

    result = plan_legacy_cursor_seed(
        legacy_path,
        endpoint,
        snapshot["revision"],
        state_root=tmp_path / "new-state",
        page=FetchResult(feed, articles, '"page-etag"', None, False),
    )

    assert result["status"] == "blocked"
    assert result["proposed_cursor"] is None
    assert "absent or ambiguous" in result["reason"]


class Inbox:
    def __init__(self):
        self.events = []
    def accept(self, event):
        self.events.append(event)
        identity = [event[key] for key in ("platform", "endpoint_id", "provider_event_id")]
        return {"event_key": hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest(), "version": 1, "duplicate": False, "work_keys": []}


def snapshot_and_config():
    settings = {"version": 1, "feeds": [{"id": feed.lane.value, "enabled": True} for feed in FEEDS], "destinations": {"id_stocks_news_channel_id": "1525102508714889257", "macro_news_channel_id": "1531655369884045382"}, "additional_prompt_instruction": ""}
    loaded = LoadedStockbitConfig(load_watch_config_data(settings), 7)
    rows = [{"platform": "rss", "endpoint_id": f"rss:stockbit:{feed.lane.value}", "publisher_id": "stockbit", "address": feed.url, "provider_id": feed.lane.value, "capability_id": "stockbit_snips", "verification_status": "verified", "enabled": True} for feed in FEEDS]
    return {"revision": 4, "subscriptions": rows}, loaded


def test_four_fixed_lanes_and_frozen_revision(tmp_path):
    snapshot, loaded = snapshot_and_config()
    selected, _ = endpoints(snapshot, loaded)
    assert len(selected) == 4
    article = lambda feed, guid, when=NOW: Article(feed.lane, feed.label, guid, f"https://snips.stockbit.com/{guid}", "Title", "Text", when)
    pages = {feed.lane.value: [article(feed, "old")] for feed in FEEDS}
    fetch = lambda feed, **_kwargs: SimpleNamespace(not_modified=False, articles=list(reversed(pages[feed.lane.value])))
    inbox = Inbox()
    assert all(row["status"] == "bootstrapped" for row in run_once(snapshot, loaded, tmp_path, inbox, NOW, fetch_feed=fetch))
    pages[FEEDS[0].lane.value].append(article(FEEDS[0], "new", NOW + timedelta(minutes=1)))
    outcomes = run_once(snapshot, loaded, tmp_path, inbox, NOW, fetch_feed=fetch)
    assert [row["accepted"] for row in outcomes] == [1, 0, 0, 0]
    assert [row["fetched"] for row in outcomes] == [2, 1, 1, 1]
    assert inbox.events[0]["payload"]["watch_config_revision"] == 7


def _seeded_rss_root(root: Path) -> dict[str, bytes]:
    root.mkdir()
    (root / "catalog-revision.json").write_text('{"revision":4}')
    (root / "watch-config-revision.json").write_text('{"revision":7}')
    cursor_bytes = {}
    for feed in FEEDS:
        endpoint_id = f"rss:stockbit:{feed.lane.value}"
        anchor = hashlib.sha256(f"legacy-{feed.lane.value}".encode()).hexdigest()
        endpoint = {
            "platform": "rss", "endpoint_id": endpoint_id, "publisher_id": "stockbit",
            "address": feed.url, "provider_id": feed.lane.value,
        }
        provenance = {
            "legacy_state_sha256": "a" * 64,
            "endpoint": endpoint,
            "catalog_revision": 4,
            "proposed_anchor": anchor,
            "cursor_shape": "generic",
            "boundary_timestamp": NOW.isoformat(),
        }
        lane_root = root / endpoint_id.replace(":", "-")
        lane_root.mkdir()
        cursor = {
            "initialized": True,
            "anchor": anchor,
            "position": None,
            "boundary_published_at": NOW.isoformat(),
            "legacy_seed": provenance,
        }
        cursor_raw = json.dumps(cursor, sort_keys=True, separators=(",", ":"))
        (lane_root / "cursor.json").write_text(cursor_raw)
        cursor_bytes[feed.lane.value] = cursor_raw.encode()
        (lane_root / "http-validators.json").write_text('{"version":1,"etag":null,"last_modified":null}')
    return cursor_bytes


def test_production_seed_gate_requires_all_four_reviewed_cursors(tmp_path):
    root = tmp_path / "bursawatch-rss-source-ingest"

    with pytest.raises(IntakeBlocked):
        require_legacy_cursor_seed(root, 4, 7)

    assert not root.exists()
    _seeded_rss_root(root)
    require_legacy_cursor_seed(root, 4, 7)

    cursor_path = root / "rss-stockbit-unboxing" / "cursor.json"
    cursor = json.loads(cursor_path.read_text())
    cursor["anchor"] = hashlib.sha256(b"post-cutover-item").hexdigest()
    cursor["boundary_published_at"] = (NOW + timedelta(minutes=1)).isoformat()
    cursor_path.write_text(json.dumps(cursor, sort_keys=True, separators=(",", ":")))
    require_legacy_cursor_seed(root, 4, 7)


def test_production_runner_blocks_before_fetch_when_cursor_handoff_is_missing(tmp_path):
    snapshot, loaded = snapshot_and_config()
    root = tmp_path / "bursawatch-rss-source-ingest"

    class IdleInbox:
        def claim(self, _pipelines, _limit):
            return []

    def owner_command(command):
        assert command == "agent-status"
        return {"ready": False}

    result = run_pipeline(
        snapshot,
        loaded,
        root,
        IdleInbox(),
        NOW,
        fetch_feed=lambda *_args, **_kwargs: pytest.fail("missing seed must block before feed fetch"),
        owner_command=owner_command,
        require_legacy_seed=True,
    )

    assert result["source"] == [{
        "endpoint_id": "rss:stockbit", "status": "blocked", "reason": "migration_cursor_handoff_invalid",
    }]
    assert not root.exists()


@pytest.mark.parametrize("page_case", ["unordered", "ambiguous_equal_timestamp"])
def test_live_rss_page_holds_cursor_when_order_cannot_be_proven(tmp_path, page_case):
    snapshot, loaded = snapshot_and_config()
    feed = FEEDS[0]
    root = tmp_path / "bursawatch-rss-source-ingest"
    cursor_bytes = _seeded_rss_root(root)
    feed_dir = root / "rss-stockbit-stockbit_commentary"
    cursor_path = feed_dir / "cursor.json"
    cursor = json.loads(cursor_path.read_text())
    page_by_lane = {item.lane.value: FetchResult(item, (), None, None, False) for item in FEEDS}
    if page_case == "unordered":
        page_by_lane[feed.lane.value] = FetchResult(feed, (
            Article(feed.lane, feed.label, "older", "https://snips.stockbit.com/older", "Older", "Body", NOW),
            Article(feed.lane, feed.label, "newer", "https://snips.stockbit.com/newer", "Newer", "Body", NOW + timedelta(minutes=1)),
        ), None, None, False)
    else:
        page_by_lane[feed.lane.value] = FetchResult(feed, (
            Article(feed.lane, feed.label, "same-time-other", "https://snips.stockbit.com/item", "Item", "Body", NOW),
        ), None, None, False)
    before_cursor = cursor_path.read_bytes()
    before_validators = (feed_dir / "http-validators.json").read_bytes()

    results = run_once(snapshot, loaded, root, Inbox(), NOW + timedelta(minutes=2), fetch_feed=lambda selected, **_kwargs: page_by_lane[selected.lane.value])

    assert results[0]["status"] == "blocked"
    assert results[0]["fetched"] == len(page_by_lane[feed.lane.value].articles)
    assert cursor_path.read_bytes() == before_cursor
    assert (feed_dir / "http-validators.json").read_bytes() == before_validators
    assert cursor["anchor"] == hashlib.sha256(b"legacy-stockbit_commentary").hexdigest()


def test_not_modified_feed_reuses_validators_without_advancing_cursor(tmp_path):
    snapshot, loaded = snapshot_and_config()
    last_modified = "Mon, 28 Sep 2026 08:00:00 GMT"

    def initial_page(feed, **kwargs):
        assert kwargs == {"page": 1, "etag": None, "last_modified": None, "provider_order": True}
        article = Article(feed.lane, feed.label, f"old-{feed.lane.value}", f"https://snips.stockbit.com/{feed.lane.value}", "Old", "Old body", NOW)
        return FetchResult(feed, (article,), '"stockbit-v1"', last_modified, False)

    inbox = Inbox()
    first = run_once(snapshot, loaded, tmp_path, inbox, NOW, fetch_feed=initial_page)
    assert {row["status"] for row in first} == {"bootstrapped"}
    cursor_paths = sorted(tmp_path.glob("rss-stockbit-*/cursor.json"))
    before = {path: path.read_bytes() for path in cursor_paths}
    seen = {}

    def unchanged_page(feed, **kwargs):
        seen[feed.lane.value] = kwargs
        return FetchResult(feed, (), kwargs.get("etag"), kwargs.get("last_modified"), True)

    second = run_once(snapshot, loaded, tmp_path, inbox, NOW, fetch_feed=unchanged_page)

    assert {row["status"] for row in second} == {"empty"}
    assert {row["fetched"] for row in second} == {0}
    assert set(seen) == {feed.lane.value for feed in FEEDS}
    assert all(
        kwargs == {"page": 1, "etag": '"stockbit-v1"', "last_modified": last_modified, "provider_order": True}
        for kwargs in seen.values()
    )
    assert {path: path.read_bytes() for path in cursor_paths} == before


def test_media_metadata_is_stripped_and_text_event_advances_cursor_without_replay(tmp_path):
    snapshot, loaded = snapshot_and_config()
    feed = FEEDS[0]
    old = Article(feed.lane, feed.label, "old", "https://snips.stockbit.com/old", "Old", "Old body", NOW)
    text = Article(feed.lane, feed.label, "text", "https://snips.stockbit.com/text", "Text", "Text body", NOW + timedelta(minutes=1))
    media = Article(
        feed.lane,
        feed.label,
        "media",
        "https://snips.stockbit.com/media",
        "Media",
        "Media body",
        NOW + timedelta(minutes=2),
        media_url="https://unreviewed.example.test/image.jpg",
    )
    pages = {lane.lane.value: [Article(lane.lane, lane.label, f"old-{lane.lane.value}", f"https://snips.stockbit.com/{lane.lane.value}", "Old", "Old body", NOW)] for lane in FEEDS}
    pages[feed.lane.value] = [old]

    def first_page(selected_feed, **_kwargs):
        return FetchResult(selected_feed, tuple(reversed(pages[selected_feed.lane.value])), '"etag-v1"', "Mon, 28 Sep 2026 08:00:00 GMT", False)

    state_root = tmp_path / "state"
    run_once(snapshot, loaded, state_root, Inbox(), NOW, fetch_feed=first_page)
    validator_path = state_root / f"rss-stockbit-{feed.lane.value}" / "http-validators.json"
    before = validator_path.read_bytes()
    pages[feed.lane.value] = [old, text, media]
    seen = []

    def media_page(selected_feed, **kwargs):
        seen.append(kwargs)
        if selected_feed.lane == feed.lane:
            return FetchResult(selected_feed, tuple(reversed(pages[selected_feed.lane.value])), '"etag-v2"', "Mon, 28 Sep 2026 08:01:00 GMT", False)
        return FetchResult(selected_feed, tuple(reversed(pages[selected_feed.lane.value])), '"etag-v1"', "Mon, 28 Sep 2026 08:00:00 GMT", False)

    inbox = Inbox()
    result = run_once(snapshot, loaded, state_root, inbox, NOW, fetch_feed=media_page)

    assert result[0]["status"] == "accepted"
    assert result[0]["accepted"] == 2
    assert len(inbox.events) == 2
    media_event = inbox.events[-1]
    assert media_event["provider_event_id"] == hashlib.sha256(b"media").hexdigest()
    assert media_event["payload"]["article"]["guid"] == "media"
    assert media_event["payload"]["article"]["source_text"] == "Media body"
    assert "media_url" not in media_event["payload"]["article"]
    assert media_event["media_required"] is False
    assert media_event["media_refs"] == []
    assert "unreviewed.example.test" not in json.dumps(media_event)
    assert json.loads(validator_path.read_text()) == {"version": 1, "etag": '"etag-v2"', "last_modified": "Mon, 28 Sep 2026 08:01:00 GMT"}
    assert validator_path.read_bytes() != before
    assert len(seen) == len(FEEDS)
    assert all(kwargs["etag"] == '"etag-v1"' for kwargs in seen)

    replay = run_once(snapshot, loaded, state_root, inbox, NOW, fetch_feed=media_page)
    assert replay[0]["accepted"] == 0
    assert len(inbox.events) == 2
    cursor = json.loads((state_root / f"rss-stockbit-{feed.lane.value}" / "cursor.json").read_text())
    assert cursor["anchor"] == hashlib.sha256(b"media").hexdigest()


def test_stockbit_rejects_unreviewed_lane_and_missing_live_revision():
    snapshot, loaded = snapshot_and_config()
    with pytest.raises(Exception):
        endpoints({"revision": 4, "subscriptions": snapshot["subscriptions"] + [{**snapshot["subscriptions"][0], "endpoint_id": "rss:arbitrary", "address": "https://example.com/rss"}]}, loaded)
    with pytest.raises(Exception):
        endpoints(snapshot, LoadedStockbitConfig(loaded.config, 0))


def test_live_revision_change_blocks_reenable_without_history_replay(tmp_path):
    snapshot, loaded = snapshot_and_config()
    fetch = lambda feed, **_kwargs: SimpleNamespace(not_modified=False, articles=(Article(feed.lane, feed.label, "old", "https://snips.stockbit.com/old", "Title", "Text", NOW),))
    run_once(snapshot, loaded, tmp_path, Inbox(), NOW, fetch_feed=fetch)
    with pytest.raises(Exception, match="future-only transition"):
        run_once(snapshot, LoadedStockbitConfig(loaded.config, 8), tmp_path, Inbox(), NOW, fetch_feed=fetch)


def test_source_work_claim_enters_stockbit_owner_then_wakes_agent(tmp_path):
    snapshot, loaded = snapshot_and_config()
    feed = FEEDS[0]
    old = Article(feed.lane, feed.label, "old", "https://snips.stockbit.com/old", "Old", "Old body", NOW)
    new = Article(feed.lane, feed.label, "new", "https://snips.stockbit.com/new", "New", "New body", NOW + timedelta(minutes=1))
    pages = {item.lane.value: [Article(item.lane, item.label, "old", "https://snips.stockbit.com/old", "Old", "Old body", NOW)] for item in FEEDS}
    fetch = lambda selected, **_kwargs: SimpleNamespace(not_modified=False, articles=list(reversed(pages[selected.lane.value])))
    owner_path = tmp_path / "stockbit-owner.json"

    class WorkInbox(Inbox):
        def __init__(self):
            super().__init__()
            self.pending = []
            self.begun = []
        def accept(self, event):
            result = super().accept(event)
            effect = hashlib.sha256(f'{result["event_key"]}:1:stockbit_snips'.encode()).hexdigest()
            self.pending.append({"pipeline_id": "stockbit_snips", "capability_id": "stockbit_snips", "capability_version": 1, "catalog_revision": 4, "settings": {}, "event_kind": "original", "version": 1, "event_key": result["event_key"], "work_key": effect, "effect_key": effect, "lease_token": "fake-lease", "envelope": event})
            return result
        def claim(self, pipelines, limit):
            assert pipelines == ["stockbit_snips"] and limit == 20
            work, self.pending = self.pending[:limit], self.pending[limit:]
            return work
        def begin(self, key, token):
            self.begun.append(key)
            return True
        def settle(self, key, token, success, error_code=None):
            return {"work_key": key, "status": "done" if success else "pending"}

    inbox = WorkInbox()
    def command(name):
        if name == "agent-status":
            return pipeline_owner.agent_status(path=owner_path, now=NOW + timedelta(minutes=1))
        assert name == "claim-agent"
        return pipeline_owner.claim_agent(path=owner_path, no_post=True, now=NOW + timedelta(minutes=1))
    handler = lambda work: pipeline_owner.submit(work, path=owner_path, no_post=True, now=NOW)

    initial = run_pipeline(snapshot, loaded, tmp_path / "rss", inbox, NOW, fetch_feed=fetch, handler=handler, owner_command=command)
    assert initial["wakeAgent"] is False and initial["work"] == []
    pages[feed.lane.value] = [old, new]
    result = run_pipeline(snapshot, loaded, tmp_path / "rss", inbox, NOW + timedelta(minutes=1), fetch_feed=fetch, handler=handler, owner_command=command)
    assert result["source"][0]["accepted"] == 1
    assert result["work"] == [{"work_key": inbox.begun[0], "status": "done"}]
    assert result["wakeAgent"] is True
    assert result["items"][0]["candidate_key"] == new.key
    assert result["items"][0]["source_title"] == "New"


def test_revision_block_holds_source_cursor_but_drains_prior_work(tmp_path):
    snapshot, loaded = snapshot_and_config()
    fetch = lambda feed, **_kwargs: SimpleNamespace(not_modified=False, articles=(Article(feed.lane, feed.label, "old", "https://snips.stockbit.com/old", "Old", "Old body", NOW),))
    run_once(snapshot, loaded, tmp_path, Inbox(), NOW, fetch_feed=fetch)
    cursors = {path: path.read_bytes() for path in tmp_path.glob("rss-stockbit-*/cursor.json")}

    class PendingInbox:
        def claim(self, pipelines, limit):
            return [{"work_key": "prior", "lease_token": "lease", "pipeline_id": "stockbit_snips"}]
        def begin(self, key, token):
            return True
        def settle(self, key, token, success, error_code=None):
            return {"work_key": key, "status": "done" if success else "pending"}

    seen = []
    blocked = run_pipeline(
        snapshot, LoadedStockbitConfig(loaded.config, 8), tmp_path, PendingInbox(), NOW,
        fetch_feed=lambda *args, **kwargs: pytest.fail("revision mismatch must block RSS fetching"),
        handler=lambda work: seen.append(work["work_key"]),
        owner_command=lambda *_args: {"ready": False},
    )
    assert blocked["source"] == [{"endpoint_id": "rss:stockbit", "status": "blocked", "reason": "intake_config_mismatch"}]
    assert blocked["work"] == [{"work_key": "prior", "status": "done"}]
    assert seen == ["prior"]
    assert {path: path.read_bytes() for path in cursors} == cursors
