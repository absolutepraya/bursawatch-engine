from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo

import config
import discord
import state
from agent_protocol import analysis_payload, build_wake_payload, validate_submission
from market_data import get_market_snapshot
from models import Analysis, Article, Route, StockbitWatchConfig
from render import render
from rss import fetch_feed
from control_plane_runtime import ControlPlaneRun


WIB = ZoneInfo("Asia/Jakarta")
LOGGER = logging.getLogger(__name__)
REPORT_COUNTS = ("fetched", "queued", "bootstrapped", "not_modified", "pending", "delivered")


def _now() -> datetime:
    return datetime.now(WIB)


def _reason(error: object) -> str:
    value = " ".join(str(error).split())
    return value[:300]


def _report_attributes(stats: Mapping[str, object], no_post: bool) -> dict[str, object]:
    attributes: dict[str, object] = {key: int(stats.get(key, 0)) for key in REPORT_COUNTS}
    attributes["no_post"] = no_post
    errors = stats.get("errors")
    if isinstance(errors, list) and errors:
        attributes["errors"] = ["Stockbit run encountered an error"] * len(errors)
    return attributes


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


def _fetch_into_state(
    value: dict[str, object], runtime: config.RuntimeConfig, now: datetime, watch_config: StockbitWatchConfig
) -> dict[str, object]:
    stats: dict[str, object] = {
        "fetched": 0,
        "queued": 0,
        "bootstrapped": 0,
        "not_modified": 0,
        "errors": [],
    }
    enabled_lanes = {setting.lane for setting in watch_config.feeds if setting.enabled}
    for feed in config.FEEDS:
        record = _feed_status(value, feed.lane.value)
        if feed.lane not in enabled_lanes:
            record["enabled"] = False
            continue
        resuming = record["enabled"] is False
        if resuming:
            record["etag"] = None
            record["last_modified"] = None
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
                if resuming:
                    raise RuntimeError("unconditional resume returned not modified")
                stats["not_modified"] = int(stats["not_modified"]) + 1
                continue
            articles = list(result.articles)
            stats["fetched"] = int(stats["fetched"]) + len(articles)
            if not articles:
                errors = stats["errors"]
                assert isinstance(errors, list)
                errors.append(f"{feed.label}: empty RSS feed")
                continue
            if resuming:
                state.set_cursor(record, max(articles, key=lambda item: (item.published_at, item.guid)))
                record["enabled"] = True
                stats["bootstrapped"] = int(stats["bootstrapped"]) + 1
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


def _preflight_pending_delivery(value: dict[str, object]) -> None:
    articles = value["articles"]
    assert isinstance(articles, dict)
    for record in articles.values():
        if isinstance(record, dict) and record.get("phase") == "pending_delivery":
            _analysis_from_record(record)


def _snapshot(loaded: config.LoadedStockbitConfig) -> dict[str, object]:
    watch = loaded.config
    return {
        "revision": loaded.revision,
        "additional_prompt_instruction": watch.additional_prompt_instruction,
        "id_stocks_news_channel_id": watch.id_stocks_news_channel_id,
        "macro_news_channel_id": watch.macro_news_channel_id,
    }


def _bound_snapshot(record: Mapping[str, object]) -> Mapping[str, object] | None:
    snapshot = record.get("config_snapshot")
    return snapshot if isinstance(snapshot, Mapping) else None


def _channel(record: Mapping[str, object], route: Route) -> str:
    snapshot = _bound_snapshot(record)
    if snapshot is None:
        raise ValueError("Stockbit article has no bound configuration")
    if route is Route.ID_STOCKS_NEWS:
        return str(snapshot["id_stocks_news_channel_id"])
    if route is Route.MACRO_NEWS:
        return str(snapshot["macro_news_channel_id"])
    raise ValueError("excluded Stockbit article has no Discord channel")


def _bind_legacy_delivery(value: dict[str, object], loaded: config.LoadedStockbitConfig) -> bool:
    articles = value["articles"]
    assert isinstance(articles, dict)
    changed = False
    for record in articles.values():
        if isinstance(record, dict) and record.get("phase") == "pending_delivery" and _bound_snapshot(record) is None:
            record["config_snapshot"] = _snapshot(loaded)
            changed = True
    return changed


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
        if (
            not isinstance(record, dict)
            or record.get("phase") != "pending_delivery"
            or _bound_snapshot(record) is None
            or not state.retry_due(record, now)
        ):
            continue
        article = state.article_from_record(key, record)
        result.append((key, record, article, _analysis_from_record(record)))
    return sorted(result, key=lambda item: (item[2].published_at, item[0]))


def _drain_delivery(
    value: dict[str, object], runtime: config.RuntimeConfig, now: datetime,
    errors: list[str] | None = None,
) -> int:
    delivered = 0
    for key, record, article, analysis in _pending_delivery(value, now):
        try:
            content = _render_record(record, article, analysis)
            if runtime.no_post:
                continue
            channel_id = _channel(record, analysis.route)
            message_id = discord.post_text(
                content,
                channel_id,
                dry_run=False,
                event_key=key,
                leg="news",
            )
            record["phase"] = "delivered"
            record["delivery"] = {
                "message_id": message_id,
                "channel_id": channel_id,
                "delivered_at": now.isoformat(),
            }
            delivered += 1
        except discord.DeliveryOwnerPending:
            # The service accepted this operation. Its durable retry schedule
            # is authoritative, so keep the source item pending without
            # advancing a second local retry clock.
            break
        except discord.DiscordRateLimited as error:
            state.mark_delivery_failure(record, now, str(error))
            if errors is not None:
                errors.append("Stockbit delivery failed")
            break
        except Exception as error:
            state.mark_delivery_failure(record, now, _reason(error))
            if errors is not None:
                errors.append("Stockbit delivery failed")
    return delivered


def _heartbeat(runtime: config.RuntimeConfig, now: datetime, stats: Mapping[str, object]) -> None:
    if runtime.no_post:
        return
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
        config.HEARTBEAT_CHANNEL_ID,
        dry_run=False,
        event_key=f"heartbeat:{now:%Y%m%d%H%M}",
        leg="heartbeat",
    )


def run() -> dict[str, object]:
    runtime = config.runtime()
    _assert_no_post_isolated(runtime)
    try:
        loaded = config.load_watch_config_for_run()
    except Exception:
        LOGGER.warning("Stockbit live configuration is unavailable or invalid")
        loaded = None
    now = _now()
    control_run = None
    if loaded is not None and not runtime.no_post:
        control_run = ControlPlaneRun.begin(
            "STOCKBIT_SNIPS", loaded.revision,
            scheduler_job_id=config.WATCHER_ID, trigger="scheduled",
        )
        control_run.event(
            "run-started", level="info", phase="lifecycle", event_type="run.started",
            message="Stockbit scheduled run started", attributes={"no_post": False},
        )
    try:
        result = _run_once(runtime, loaded, now)
    except Exception:
        if control_run is not None:
            control_run.event(
                "run-failed", level="error", phase="lifecycle", event_type="run.failed",
                message="Stockbit scheduled run failed", attributes={"no_post": False, "errors": ["Stockbit run failed"]},
            )
            control_run.finish("failed", "Stockbit scheduled run failed")
        raise
    if control_run is not None:
        stats = result["stats"]
        assert isinstance(stats, Mapping)
        degraded = bool(stats.get("degraded"))
        control_run.event(
            "run-completed", level="warning" if degraded else "info", phase="lifecycle",
            event_type="run.completed", message="Stockbit scheduled run completed",
            attributes=_report_attributes(stats, runtime.no_post),
        )
        control_run.finish("degraded" if degraded else "ok")
    return result


def _run_once(
    runtime: config.RuntimeConfig, loaded: config.LoadedStockbitConfig | None, now: datetime
) -> dict[str, object]:
    with state.run_lock(runtime.state_path):
        value = state.load_state(runtime.state_path, config.FEEDS)
        _preflight_pending_delivery(value)
        if loaded is None:
            stats: dict[str, object] = {
                "fetched": 0, "queued": 0, "bootstrapped": 0, "not_modified": 0,
                "errors": ["Stockbit live configuration is unavailable or invalid"],
            }
            previous_state = json.dumps(value, sort_keys=True)
        else:
            stats = _fetch_into_state(value, runtime, now, loaded.config)
            if _bind_legacy_delivery(value, loaded):
                state.save_state(runtime.state_path, value)
        errors = stats["errors"]
        assert isinstance(errors, list)
        delivered = _drain_delivery(value, runtime, now, errors)
        if runtime.no_post:
            pending_result = None
        elif loaded is None:
            articles = value["articles"]
            assert isinstance(articles, dict)
            bound = {key: record for key, record in articles.items() if isinstance(record, dict) and _bound_snapshot(record)}
            pending_result = state.pending_agent({"articles": bound}, now)
        else:
            pending_result = state.pending_agent(value, now)
        if pending_result is None:
            payload: dict[str, object] = {"wakeAgent": False, "items": []}
        else:
            key, article = pending_result
            record = _article_record(value, key)
            if _bound_snapshot(record) is None:
                assert loaded is not None
                record["config_snapshot"] = _snapshot(loaded)
            state.claim_agent(record, now)
            state.save_state(runtime.state_path, value)
            snapshot = _bound_snapshot(record)
            assert snapshot is not None
            payload = build_wake_payload(article, str(snapshot["additional_prompt_instruction"]))
        articles = value["articles"]
        pending = sum(
            1
            for record in articles.values()
            if isinstance(record, dict) and record.get("phase") in {"awaiting_agent", "pending_delivery"}
        )
        stats["delivered"] = delivered
        stats["pending"] = pending
        stats["degraded"] = bool(stats["errors"])
        if loaded is not None:
            value["last_heartbeat"] = now.isoformat()
            state.save_state(runtime.state_path, value)
        elif json.dumps(value, sort_keys=True) != previous_state:
            state.save_state(runtime.state_path, value)
        try:
            _heartbeat(runtime, now, stats)
        except Exception:
            errors = stats["errors"]
            assert isinstance(errors, list)
            errors.append("heartbeat delivery failed")
        stats["degraded"] = bool(stats["errors"])
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
        _preflight_pending_delivery(value)
        record = _article_record(value, candidate_key)
        article = state.article_from_record(candidate_key, record)
        if record.get("phase") not in {"awaiting_agent"}:
            raise ValueError("Stockbit article is not awaiting agent analysis")
        analysis = validate_submission(article, payload)
        if _bound_snapshot(record) is None:
            record["config_snapshot"] = _snapshot(config.load_watch_config_for_run())
        elif runtime.no_post:
            try:
                config.load_watch_config_for_run()
            except Exception:
                pass
        snapshot = _bound_snapshot(record)
        assert snapshot is not None
        control_run = None
        if not runtime.no_post:
            control_run = ControlPlaneRun.begin(
                "STOCKBIT_SNIPS", int(snapshot["revision"]),
                scheduler_job_id=config.WATCHER_ID, trigger="agent_submission",
            )
            control_run.event(
                "submission-started", level="info", phase="lifecycle", event_type="submission.started",
                message="Stockbit agent submission started", attributes={"no_post": False},
            )
        delivery_errors: list[str] = []
        try:
            result = _submit_bound_analysis(value, record, article, analysis, runtime, now, delivery_errors)
        except Exception:
            if control_run is not None:
                control_run.event(
                    "submission-failed", level="error", phase="lifecycle", event_type="submission.failed",
                    message="Stockbit agent submission failed",
                    attributes={"no_post": False, "errors": ["Stockbit submission failed"]},
                )
                control_run.finish("failed", "Stockbit agent submission failed")
            raise
        if control_run is not None:
            delivery_failed = bool(delivery_errors) or (
                analysis.route is not Route.EXCLUDE and record.get("phase") == "pending_delivery"
            )
            control_run.event(
                "submission-completed", level="warning" if delivery_failed else "info",
                phase="lifecycle", event_type="submission.completed",
                message="Stockbit agent submission completed",
                attributes={
                    "delivered": int(result.get("delivered", 0)), "no_post": False,
                    **({"errors": delivery_errors or ["Stockbit delivery failed"]} if delivery_failed else {}),
                },
            )
            control_run.finish("degraded" if delivery_failed else "ok")
        return result


def _submit_bound_analysis(
    value: dict[str, object], record: dict[str, object], article: Article, analysis: Analysis,
    runtime: config.RuntimeConfig, now: datetime, delivery_errors: list[str],
) -> dict[str, object]:
    record["analysis"] = analysis_payload(analysis)
    record["agent_lease_until"] = None
    if analysis.route is Route.EXCLUDE:
        record["phase"] = "excluded"
        result = {"wakeAgent": False, "accepted": True, "excluded": True, "candidate_key": article.key}
    else:
        record["phase"] = "pending_delivery"
        _render_record(record, article, analysis)
        state.save_state(runtime.state_path, value)
        delivered = _drain_delivery(value, runtime, now, delivery_errors)
        result = {
            "wakeAgent": False,
            "accepted": True,
            "excluded": False,
            "candidate_key": article.key,
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
