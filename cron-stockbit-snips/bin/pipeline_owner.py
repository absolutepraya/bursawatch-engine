"""Admit fixed Stockbit RSS source work to the existing article owner state."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import config
import state
from agent_protocol import build_wake_payload
from models import Article


def _state_path() -> Path:
    return config.runtime().state_path


def _check_isolated(path: Path, no_post: bool) -> None:
    if no_post and path.expanduser().resolve().is_relative_to((Path.home() / ".hermes" / "state").resolve()):
        raise ValueError("no-post Stockbit source work requires isolated state")


def _validated(work: dict[str, Any]) -> tuple[Article, dict[str, object], dict[str, object]]:
    if type(work) is not dict or type(work.get("envelope")) is not dict:
        raise ValueError("Stockbit source work is invalid")
    envelope = work["envelope"]
    payload = envelope.get("payload")
    if type(payload) is not dict:
        raise ValueError("Stockbit source payload is invalid")
    article = Article.from_payload(payload.get("article"))
    feed = next((feed for feed in config.FEEDS if feed.lane == article.lane), None)
    if feed is None or article.lane_label != feed.label or article.media_url is not None:
        raise ValueError("Stockbit source article is outside the fixed text-only lanes")
    event_key = work.get("event_key")
    if type(event_key) is not str or not re.fullmatch(r"[0-9a-f]{64}", event_key):
        raise ValueError("Stockbit source event identity is invalid")
    effect = hashlib.sha256(f'{event_key}:1:stockbit_snips'.encode()).hexdigest()
    if (
        work.get("pipeline_id") != "stockbit_snips"
        or work.get("capability_id") != "stockbit_snips"
        or work.get("version") != 1
        or work.get("event_kind") != "original"
        or work.get("capability_version") != 1
        or work.get("settings") != {}
        or type(work.get("catalog_revision")) is not int
        or work["catalog_revision"] < 1
        or work.get("effect_key") != effect
        or work.get("work_key") != effect
        or envelope.get("platform") != "rss"
        or envelope.get("publisher_id") != "stockbit"
        or envelope.get("endpoint_id") != f"rss:stockbit:{article.lane.value}"
        or envelope.get("provider_event_id") != hashlib.sha256(article.guid.encode("utf-8")).hexdigest()
        or envelope.get("source_url") != article.url
        or envelope.get("published_at") != article.published_at.isoformat()
        or envelope.get("media_required") is not False
        or envelope.get("media_refs") != []
    ):
        raise ValueError("Stockbit source work identity is invalid")
    frozen = payload.get("watch_config_snapshot")
    if (
        not state._valid_config_snapshot(frozen)
        or type(payload.get("watch_config_revision")) is not int
        or frozen["revision"] != payload["watch_config_revision"]
    ):
        raise ValueError("Stockbit source work configuration revision is invalid")
    provenance = {
        "effect_key": effect,
        "event_key": work["event_key"],
        "version": 1,
        "catalog_revision": work["catalog_revision"],
        "content_hash": envelope.get("content_hash"),
    }
    if type(provenance["content_hash"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", provenance["content_hash"]):
        raise ValueError("Stockbit source content hash is invalid")
    return article, frozen, provenance


def submit(work: dict[str, Any], *, path: Path | None = None, no_post: bool = False, now: datetime | None = None) -> str:
    """Bind one immutable source article, without fetching or sending anything."""
    destination = path or _state_path()
    _check_isolated(destination, no_post)
    article, frozen, provenance = _validated(work)
    observed = now or datetime.now(article.published_at.tzinfo)
    with state.run_lock(destination):
        value = state.load_state(destination, config.FEEDS)
        articles = value["articles"]
        assert isinstance(articles, dict)
        existing = articles.get(article.key)
        if existing is not None:
            if (not isinstance(existing, dict) or existing.get("source_work") != provenance
                    or existing.get("article") != article.to_payload()
                    or existing.get("config_snapshot") != frozen):
                raise ValueError("Stockbit article conflicts with existing owner state")
            return "accepted"
        if not state.queue_article(value, article, observed):
            raise ValueError("Stockbit article could not be queued")
        record = articles[article.key]
        record["source_work"] = provenance
        record["config_snapshot"] = frozen
        state.save_state(destination, value)
    return "accepted"


def _pending_source(value: dict[str, object], now: datetime) -> tuple[str, Article] | None:
    articles = value["articles"]
    assert isinstance(articles, dict)
    selected = {
        key: record for key, record in articles.items()
        if isinstance(record, dict) and isinstance(record.get("source_work"), dict)
    }
    return state.pending_agent({"articles": selected}, now)


def agent_status(*, path: Path | None = None, now: datetime | None = None) -> dict[str, object]:
    destination = path or _state_path()
    observed = now or datetime.now().astimezone()
    with state.run_lock(destination):
        value = state.load_state(destination, config.FEEDS)
        pending = _pending_source(value, observed)
        if pending is None:
            return {"ready": False}
        key, article = pending
        record = value["articles"][key]
        return {"ready": True, "pipeline_id": "stockbit_snips", "event_key": record["source_work"]["event_key"], "published_at": article.published_at.isoformat()}


def claim_agent(*, path: Path | None = None, no_post: bool = False, now: datetime | None = None) -> dict[str, object]:
    destination = path or _state_path()
    _check_isolated(destination, no_post)
    observed = now or datetime.now().astimezone()
    with state.run_lock(destination):
        value = state.load_state(destination, config.FEEDS)
        pending = _pending_source(value, observed)
        if pending is None:
            return {"wakeAgent": False, "items": []}
        key, article = pending
        record = value["articles"][key]
        snapshot = record["config_snapshot"]
        if not state._valid_config_snapshot(snapshot):
            raise ValueError("Stockbit source article has invalid frozen configuration")
        state.claim_agent(record, observed)
        state.save_state(destination, value)
        return build_wake_payload(article, snapshot["additional_prompt_instruction"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=("agent-status", "claim-agent"))
    args = parser.parse_args(argv)
    no_post = os.environ.get("BURSAWATCH_RSS_SOURCE_NO_POST") == "1"
    if args.command == "agent-status":
        result = agent_status()
    elif args.command == "claim-agent":
        result = claim_agent(no_post=no_post)
    else:
        result = {"outcome": submit(json.load(sys.stdin), no_post=no_post)}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
