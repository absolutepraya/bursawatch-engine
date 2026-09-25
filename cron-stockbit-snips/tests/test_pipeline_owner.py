from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib

import pytest

import config
import pipeline_owner
import state
from agent_protocol import build_wake_payload
from models import Article


NOW = datetime(2026, 9, 24, 7, tzinfo=UTC)


def source_work() -> dict:
    feed = config.FEEDS[0]
    article = Article(feed.lane, feed.label, "guid/101", "https://snips.stockbit.com/guid-101", "Headline", "Source text", NOW)
    event_key = hashlib.sha256(b"stockbit-source-event").hexdigest()
    effect_key = hashlib.sha256(f"{event_key}:1:stockbit_snips".encode()).hexdigest()
    return {
        "pipeline_id": "stockbit_snips", "capability_id": "stockbit_snips", "capability_version": 1, "catalog_revision": 4, "settings": {}, "event_kind": "original",
        "version": 1, "event_key": event_key, "effect_key": effect_key, "work_key": effect_key,
        "envelope": {
            "platform": "rss", "publisher_id": "stockbit", "endpoint_id": f"rss:stockbit:{feed.lane.value}",
            "provider_event_id": hashlib.sha256(article.guid.encode()).hexdigest(),
            "source_url": article.url, "published_at": article.published_at.isoformat(),
            "content_hash": hashlib.sha256(b"article-content").hexdigest(), "media_required": False, "media_refs": [],
            "payload": {
                "article": article.to_payload(), "watch_config_revision": 7,
                "watch_config_snapshot": {
                    "revision": 7, "additional_prompt_instruction": "Prioritize the source numbers",
                    "id_stocks_news_channel_id": "123456789012345678",
                    "macro_news_channel_id": "234567890123456789",
                },
            },
        },
    }


def test_source_work_queues_once_and_wakes_with_exact_existing_payload(tmp_path, monkeypatch):
    path = tmp_path / "stockbit.json"
    work = source_work()
    assert pipeline_owner.submit(work, path=path, no_post=True, now=NOW) == "accepted"
    original = path.read_bytes()
    assert pipeline_owner.submit(work, path=path, no_post=True, now=NOW) == "accepted"
    assert path.read_bytes() == original
    saved = state.load_state(path, config.FEEDS)
    key = Article.from_payload(work["envelope"]["payload"]["article"]).key
    assert saved["articles"][key]["config_snapshot"] == work["envelope"]["payload"]["watch_config_snapshot"]
    assert pipeline_owner.agent_status(path=path, now=NOW)["event_key"] == work["event_key"]
    monkeypatch.setattr(config, "load_watch_config_for_run", lambda: pytest.fail("frozen source work must not reload live config"))
    wake = pipeline_owner.claim_agent(path=path, no_post=True, now=NOW)
    assert wake == build_wake_payload(Article.from_payload(work["envelope"]["payload"]["article"]), "Prioritize the source numbers")
    assert wake["items"][0]["candidate_key"] == key
    assert wake["items"][0]["operator_instruction"] == "Prioritize the source numbers"
    assert pipeline_owner.agent_status(path=path, now=NOW + timedelta(minutes=1)) == {"ready": False}
    assert pipeline_owner.agent_status(path=path, now=NOW + timedelta(minutes=3))["ready"] is True


def test_revision_mismatch_and_existing_legacy_article_fail_closed(tmp_path):
    path = tmp_path / "stockbit.json"
    work = source_work()
    mismatch = deepcopy(work)
    mismatch["envelope"]["payload"]["watch_config_snapshot"]["revision"] = 8
    with pytest.raises(ValueError, match="revision"):
        pipeline_owner.submit(mismatch, path=path, no_post=True, now=NOW)
    assert not path.exists()
    legacy = state.new_state(config.FEEDS)
    article = Article.from_payload(work["envelope"]["payload"]["article"])
    state.queue_article(legacy, article, NOW)
    state.save_state(path, legacy)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="conflicts"):
        pipeline_owner.submit(work, path=path, no_post=True, now=NOW)
    assert path.read_bytes() == before


def test_same_candidate_key_from_different_source_event_fails_closed(tmp_path):
    path = tmp_path / "stockbit.json"
    work = source_work()
    pipeline_owner.submit(work, path=path, no_post=True, now=NOW)
    other = deepcopy(work)
    other["envelope"]["payload"]["article"]["guid"] = "guid 101"
    other["envelope"]["provider_event_id"] = hashlib.sha256(b"guid 101").hexdigest()
    other["event_key"] = hashlib.sha256(b"different-event").hexdigest()
    other["work_key"] = other["effect_key"] = hashlib.sha256(f'{other["event_key"]}:1:stockbit_snips'.encode()).hexdigest()
    with pytest.raises(ValueError):
        pipeline_owner.submit(other, path=path, no_post=True, now=NOW)
