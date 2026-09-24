"""Stockbit's four fixed RSS lanes as system-owned source endpoints."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-stockbit-snips" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-stockbit-snips" / "bin"
sys.path.insert(0, str(owner))

from source_ingest import IntakeBlocked, _write, bind_catalog_revision, ingest_all, select_endpoints

ALLOWED = {"stockbit_snips"}


def _bind_revision(state_root: Path, revision: int) -> None:
    """Fail closed on feed re-enable until a reviewed future-only transition."""
    path = state_root / "watch-config-revision.json"
    if not path.exists():
        if any(state_root.glob("rss-stockbit-*/cursor.json")):
            raise IntakeBlocked("RSS cursors have no recorded live configuration revision")
        _write(path, {"revision": revision})
        return
    try:
        recorded = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise IntakeBlocked("RSS live configuration revision record is invalid") from error
    if type(recorded) is not dict or recorded.get("revision") != revision:
        raise IntakeBlocked("Stockbit live configuration revision changed; reviewed future-only transition required")


def endpoints(snapshot: dict[str, Any], loaded_config: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    from config import FEEDS
    if type(loaded_config.revision) is not int or loaded_config.revision < 1:
        raise IntakeBlocked("Stockbit requires a validated live configuration revision")
    feeds = {feed.lane.value: feed for feed in FEEDS}
    configured = {setting.lane.value: setting.enabled for setting in loaded_config.config.feeds}
    if set(configured) != set(feeds):
        raise IntakeBlocked("Stockbit must retain exactly four fixed lanes")
    bindings = {f"rss:stockbit:{lane}": {"platform": "rss", "publisher_id": "stockbit", "address": feed.url, "provider_id": lane} for lane, feed in feeds.items() if configured[lane]}
    selected = select_endpoints(snapshot, "rss", bindings, ALLOWED)
    if set(selected) != set(bindings):
        raise IntakeBlocked("Stockbit catalog and live enabled lanes differ")
    return selected, feeds


def _item(article: Any, revision: int) -> dict[str, Any]:
    payload = article.to_payload()
    # The existing Stockbit renderer does not consume media_url. Preserve the
    # article field for its parser contract; no media byte or signed URL is
    # fetched or promised to a downstream worker.
    return {"provider_event_id": hashlib.sha256(article.guid.encode("utf-8")).hexdigest(), "published_at": article.published_at.isoformat(), "source_url": article.url, "payload": {"article": payload, "watch_config_revision": revision}, "media_required": False}


def run_once(snapshot: dict[str, Any], loaded_config: Any, state_root: Path, inbox: Any, observed_at: datetime, *, fetch_feed: Any = None) -> list[dict[str, Any]]:
    selected, feeds = endpoints(snapshot, loaded_config)
    bind_catalog_revision(state_root, snapshot["revision"])
    _bind_revision(state_root, loaded_config.revision)
    if fetch_feed is None:
        from rss import fetch_feed as fetch_feed_impl
        fetch_feed = fetch_feed_impl
    fetchers = {}
    for endpoint_id, endpoint in selected.items():
        feed = feeds[endpoint["provider_id"]]
        def fetch(_after_id: str | None, feed: Any = feed) -> list[dict[str, Any]]:
            result = fetch_feed(feed, page=1)
            if result.not_modified:
                # This adapter does not persist conditional headers yet.
                raise IntakeBlocked("unexpected conditional RSS response")
            return [_item(article, loaded_config.revision) for article in result.articles]
        fetchers[endpoint_id] = fetch
    return ingest_all(selected, fetchers, state_root, inbox, observed_at, "stockbit-rss-parser-1")
