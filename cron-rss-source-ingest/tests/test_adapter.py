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
from adapter import endpoints, run_once

sys.path.insert(0, str(ROOT / "cron-stockbit-snips" / "bin"))
from config import FEEDS, LoadedStockbitConfig, load_watch_config_data
from models import Article

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


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
    assert inbox.events[0]["payload"]["watch_config_revision"] == 7


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


def test_media_url_blocks_without_entering_inbox_or_safe_marker(tmp_path):
    snapshot, loaded = snapshot_and_config()
    feed = FEEDS[0]
    old = Article(feed.lane, feed.label, "old", "https://snips.stockbit.com/old", "Title", "Text", NOW)
    media = Article(
        feed.lane,
        feed.label,
        "media-guid",
        "https://snips.stockbit.com/media",
        "Media title",
        "Media text",
        NOW + timedelta(minutes=1),
        media_url="https://unreviewed.example.test/image.jpg?signature=private",
    )
    pages = {lane.lane.value: [old] for lane in FEEDS}
    fetch = lambda selected, **_kwargs: SimpleNamespace(not_modified=False, articles=list(reversed(pages[selected.lane.value])))
    inbox = Inbox()
    run_once(snapshot, loaded, tmp_path, inbox, NOW, fetch_feed=fetch)

    pages[feed.lane.value].append(media)
    result = run_once(snapshot, loaded, tmp_path, inbox, NOW, fetch_feed=fetch)
    assert result[0] == {"endpoint_id": f"rss:stockbit:{feed.lane.value}", "status": "blocked", "reason": "media_blocked"}
    assert inbox.events == []
    marker_path = tmp_path / f"rss-stockbit-{feed.lane.value}" / "blocked-media.json"
    marker = json.loads(marker_path.read_text())
    assert marker["payload"]["article"]["guid"] == "media-guid"
    assert "media_url" not in marker["payload"]["article"]
    assert "unreviewed.example.test" not in json.dumps(marker)
    assert Article.from_payload(media.to_payload()).media_url == media.media_url
