from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

import config
import discord
import state
from agent_protocol import analysis_payload, build_wake_payload, validate_submission
from market_data import get_market_snapshot
from models import Analysis, Article, Route
from render import render
from rss import fetch_feed


WIB = ZoneInfo("Asia/Jakarta")


def _now() -> datetime:
    return datetime.now(WIB)


def _reason(error: object) -> str:
    value = " ".join(str(error).split())
    return value[:300]


def _assert_no_post_isolated(runtime: config.RuntimeConfig) -> None:
    if not runtime.no_post:
        return
    production_root = (Path.home() / ".hermes" / "state").resolve()
    try:
        runtime.state_path.resolve().relative_to(production_root)
    except ValueError:
        return
    raise RuntimeError("STOCKBIT_SNIPS_NO_POST=1 requires a temporary state path")


def _feed_status(value: dict[str, object], lane: str) -> dict[str, object]:
    feeds = value["feeds"]
    assert isinstance(feeds, dict)
    record = feeds[lane]
    assert isinstance(record, dict)
    return record


def _article_record(value: dict[str, object], key: str) -> dict[str, object]:
    articles = value["articles"]
    assert isinstance(articles, dict)
    record = articles.get(key)
    if not isinstance(record, dict):
        raise RuntimeError(f"Stockbit Snips article {key!r} is not in durable state")
    return record


def _fetch_into_state(value: dict[str, object], runtime: config.RuntimeConfig, now: datetime) -> dict[str, object]:
    stats: dict[str, object] = {
        "fetched": 0,
        "queued": 0,
        "bootstrapped": 0,
        "not_modified": 0,
        "errors": [],
    }
    for feed in config.FEEDS:
        record = _feed_status(value, feed.lane.value)
        try:
            result = fetch_feed(
                feed,
                timeout=runtime.request_timeout,
                etag=record.get("etag") if isinstance(record.get("etag"), str) else None,
                last_modified=record.get("last_modified") if isinstance(record.get("last_modified"), str) else None,
            )
            record["etag"] = result.etag
            record["last_modified"] = result.last_modified
            record["last_poll_success"] = now.isoformat()
            record["last_error"] = None
            if result.not_modified:
                stats["not_modified"] = int(stats["not_modified"]) + 1
                continue
            articles = list(result.articles)
            stats["fetched"] = int(stats["fetched"]) + len(articles)
            if not articles:
                errors = stats["errors"]
                assert isinstance(errors, list)
                errors.append(f"{feed.label}: empty RSS feed")
                continue
            cursor = state.cursor_tuple(record)
            if cursor is None:
                state.set_cursor(record, max(articles, key=lambda item: (item.published_at, item.guid)))
                stats["bootstrapped"] = int(stats["bootstrapped"]) + 1
                continue
            new_articles = [article for article in articles if state.article_is_new(record, article)]
            for article in sorted(new_articles, key=lambda item: (item.published_at, item.guid)):
                if state.queue_article(value, article, now):
                    stats["queued"] = int(stats["queued"]) + 1
            state.set_cursor(record, max(articles, key=lambda item: (item.published_at, item.guid)))
        except Exception as error:
            record["last_error"] = _reason(error)
            errors = stats["errors"]
            assert isinstance(errors, list)
            errors.append(f"{feed.label}: {_reason(error)}")
    value["last_run"] = now.isoformat()
    return stats


def _analysis_from_record(record: Mapping[str, object]) -> Analysis:
    payload = record.get("analysis")
    if not isinstance(payload, Mapping):
        raise RuntimeError("Stockbit article has no durable analysis")
    try:
        return Analysis(
            candidate_key=str(payload["candidate_key"]),
            ticker=str(payload["ticker"]),
            title=str(payload["title"]),
            summary=str(payload["summary"]),
            material_facts=tuple(str(item) for item in payload["material_facts"]),
            dedupe_facts=tuple(str(item) for item in payload["dedupe_facts"]),
            eligible=bool(payload["eligible"]),
            route=Route(payload["route"]),
            source_evidence=str(payload["source_evidence"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("Stockbit article analysis is malformed") from error


def _channel(runtime: config.RuntimeConfig, route: Route) -> str:
    if route is Route.ID_STOCKS_NEWS:
        return runtime.id_stocks_news_channel_id
    if route is Route.MACRO_NEWS:
        return runtime.macro_news_channel_id
    raise ValueError("excluded Stockbit article has no Discord channel")


def _render_record(record: dict[str, object], article: Article, analysis: Analysis) -> str:
    existing = record.get("rendered")
    if isinstance(existing, str) and existing:
        return existing
    snapshot = get_market_snapshot(analysis.ticker) if analysis.route is Route.ID_STOCKS_NEWS else None
    content = render(article, analysis, snapshot)
    record["rendered"] = content
    return content


def _pending_delivery(value: dict[str, object], now: datetime) -> list[tuple[str, dict[str, object], Article, Analysis]]:
    articles = value["articles"]
    assert isinstance(articles, dict)
    result: list[tuple[str, dict[str, object], Article, Analysis]] = []
    for key, record in articles.items():
        if not isinstance(record, dict) or record.get("phase") != "pending_delivery" or not state.retry_due(record, now):
            continue
        article = state.article_from_record(key, record)
        result.append((key, record, article, _analysis_from_record(record)))
    return sorted(result, key=lambda item: (item[2].published_at, item[0]))


def _drain_delivery(value: dict[str, object], runtime: config.RuntimeConfig, now: datetime) -> int:
    delivered = 0
    for key, record, article, analysis in _pending_delivery(value, now):
        try:
            content = _render_record(record, article, analysis)
            message_id = discord.post_text(
                content,
                _channel(runtime, analysis.route),
                token=runtime.discord_token,
                dry_run=runtime.no_post,
                event_key=key,
                leg="news",
            )
            if runtime.no_post:
                continue
            record["phase"] = "delivered"
            record["delivery"] = {
                "message_id": message_id,
                "channel_id": _channel(runtime, analysis.route),
                "delivered_at": now.isoformat(),
            }
            delivered += 1
        except discord.DiscordRateLimited as error:
            state.mark_delivery_failure(record, now, str(error))
            break
        except Exception as error:
            state.mark_delivery_failure(record, now, _reason(error))
    return delivered


def _heartbeat(runtime: config.RuntimeConfig, now: datetime, stats: Mapping[str, object]) -> None:
    errors = stats.get("errors")
    error_count = len(errors) if isinstance(errors, list) else 0
    pending = stats.get("pending", 0)
    warning = " ⚠️" if error_count else ""
    content = (
        f"🫀 {config.WATCHER_NAME} · {now:%H:%M} WIB · "
        f"{stats.get('fetched', 0)} fetched · {stats.get('queued', 0)} queued · "
        f"{stats.get('delivered', 0)} delivered · {error_count} errors · {pending} pending{warning}"
    )
    discord.post_text(
        content,
        runtime.heartbeat_channel_id,
        token=runtime.discord_token,
        dry_run=runtime.no_post,
        event_key=f"heartbeat:{now:%Y%m%d%H%M}",
        leg="heartbeat",
    )


def run() -> dict[str, object]:
    runtime = config.runtime()
    _assert_no_post_isolated(runtime)
    now = _now()
    with state.run_lock(runtime.state_path):
        value = state.load_state(runtime.state_path, config.FEEDS)
        stats = _fetch_into_state(value, runtime, now)
        delivered = _drain_delivery(value, runtime, now)
        pending_result = state.pending_agent(value, now)
        if pending_result is None:
            payload: dict[str, object] = {"wakeAgent": False, "items": []}
        else:
            key, article = pending_result
            record = _article_record(value, key)
            state.claim_agent(record, now)
            state.save_state(runtime.state_path, value)
            payload = build_wake_payload(article)
        articles = value["articles"]
        pending = sum(
            1
            for record in articles.values()
            if isinstance(record, dict) and record.get("phase") in {"awaiting_agent", "pending_delivery"}
        )
        stats["delivered"] = delivered
        stats["pending"] = pending
        stats["degraded"] = bool(stats["errors"])
        value["last_heartbeat"] = now.isoformat()
        state.save_state(runtime.state_path, value)
        try:
            _heartbeat(runtime, now, stats)
        except Exception as error:
            errors = stats["errors"]
            assert isinstance(errors, list)
            errors.append(f"heartbeat: {_reason(error)}")
        payload.update({"stats": stats})
        return payload


def submit_analysis(payload: object) -> dict[str, object]:
    runtime = config.runtime()
    _assert_no_post_isolated(runtime)
    if not isinstance(payload, Mapping):
        raise ValueError("Stockbit analysis payload must be an object")
    candidate_key = payload.get("candidate_key")
    if not isinstance(candidate_key, str) or not candidate_key:
        raise ValueError("candidate_key must be nonempty text")
    now = _now()
    with state.run_lock(runtime.state_path):
        value = state.load_state(runtime.state_path, config.FEEDS)
        record = _article_record(value, candidate_key)
        article = state.article_from_record(candidate_key, record)
        if record.get("phase") not in {"awaiting_agent"}:
            raise ValueError("Stockbit article is not awaiting agent analysis")
        analysis = validate_submission(article, payload)
        record["analysis"] = analysis_payload(analysis)
        record["agent_lease_until"] = None
        if analysis.route is Route.EXCLUDE:
            record["phase"] = "excluded"
            result = {"wakeAgent": False, "accepted": True, "excluded": True, "candidate_key": candidate_key}
        else:
            record["phase"] = "pending_delivery"
            _render_record(record, article, analysis)
            state.save_state(runtime.state_path, value)
            delivered = _drain_delivery(value, runtime, now)
            result = {
                "wakeAgent": False,
                "accepted": True,
                "excluded": False,
                "candidate_key": candidate_key,
                "delivered": delivered,
                "rendered": record.get("rendered"),
            }
        value["last_heartbeat"] = now.isoformat()
        state.save_state(runtime.state_path, value)
        if runtime.no_post:
            result["no_post"] = True
        return result


def preview(pages: int) -> dict[str, object]:
    if not isinstance(pages, int) or pages < 1 or pages > 20:
        raise ValueError("preview pages must be from 1 to 20")
    runtime = config.runtime()
    feeds: list[dict[str, object]] = []
    for feed in config.FEEDS:
        items: list[Article] = []
        for page in range(1, pages + 1):
            result = fetch_feed(feed, timeout=runtime.request_timeout, page=page)
            if result.not_modified:
                continue
            items.extend(result.articles)
            if not result.articles:
                break
        feeds.append(
            {
                "lane": feed.lane.value,
                "label": feed.label,
                "pages": pages,
                "count": len(items),
                "items": [
                    {
                        "candidate_key": item.key,
                        "published_at": item.published_at.isoformat(),
                        "title": item.source_title,
                        "url": item.url,
                        "source_characters": len(item.source_text),
                    }
                    for item in items
                ],
            }
        )
    return {"preview": True, "feeds": feeds}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    preview_parser = subparsers.add_parser("preview")
    preview_parser.add_argument("--pages", type=int, default=1)
    submit_parser = subparsers.add_parser("submit-analysis")
    submit_parser.add_argument("--json", required=True, dest="payload")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "preview":
            result = preview(arguments.pages)
        elif arguments.command == "submit-analysis":
            result = submit_analysis(json.loads(arguments.payload))
        else:
            result = run()
    except Exception as error:
        print(json.dumps({"wakeAgent": False, "error": _reason(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
