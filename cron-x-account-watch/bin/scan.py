from __future__ import annotations

import fcntl
import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import discord
import render
import rsshub
import state
import supersession
import article_context
import vision_media
import recovery
import publication_projection
from agent_protocol import (
    normalize_route,
    agent_item,
    build_wake_payload,
    deterministic_route,
    requires_relevance,
    validate_submission,
)
from models import SourcePost


WIB = ZoneInfo("Asia/Jakarta")
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
WATCHER_HEARTBEAT_NAME = "x-post"
BOARD_PENDING = "pending"
BOARD_UNAVAILABLE = "unavailable"
BOARD_RETRY_INITIAL_SECONDS = 60
BOARD_RETRY_CAP_SECONDS = 15 * 60
ROUTE_CAPABILITIES = {
    "id_stocks_news": "company_news",
    "us_stocks_news": "company_news",
    "macro_news": "macro_news",
    "id_stocks_swing": "swing_chart_context",
}
_TICKER_TOKEN = r"[A-Z][A-Z0-9]{1,9}"
_TICKER_COLON_CLAUSE = re.compile(rf"(?<![A-Z0-9])({_TICKER_TOKEN})\s*:\s+\S")
_TICKER_SPACE_CLAUSE = re.compile(rf"^\s*({_TICKER_TOKEN})\s+\S")
_TICKER_SOURCE_TITLE = re.compile(rf"^({_TICKER_TOKEN})(?:\s*:\s*|\s+)(\S.*)$")
_UPPERCASE_TOKEN = re.compile(rf"\b({_TICKER_TOKEN})\b")
_NON_TICKER_UPPERCASE = frozenset(
    {
        "ADX", "ATR", "BB", "DCA", "EMA", "IDR", "IDX", "IHSG", "MACD", "MA",
        "MFI", "OBV", "RSI", "SMA", "SL", "TP", "USD", "VWAP",
        "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    }
)
_SOURCE_BLOCK_TAGS = frozenset({"p", "div", "li"})
_SENSITIVE_VALUE_RE = re.compile(r"(?i)\b(?:token|secret|password|cookie|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+")
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_ABSOLUTE_PATH_RE = re.compile(r"(?<![A-Za-z0-9])(?:~|/(?:Users|home|tmp|var|private|opt|srv|etc))[^\s,;]*")
MAX_REASON_CHARACTERS = 500


class _SourceTextParser(HTMLParser):
    """Extract source-visible text without applying Discord Markdown rules."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag == "br" or tag in _SOURCE_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SOURCE_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def source_visible_text(content_html: str) -> str:
    parser = _SourceTextParser()
    parser.feed(content_html)
    parser.close()
    return "".join(parser.parts)


@dataclass
class RunStats:
    fetched: int = 0
    filtered: int = 0
    queued: int = 0
    delivered: int = 0
    pending: int = 0
    owner_pending: int = 0
    oldest_pending_minutes: int = 0
    degraded: bool = False
    needs_attention: bool = False
    reasons: list[str] = field(default_factory=list)

    def note_empty_profile(self, handle: str) -> None:
        self.degraded = True
        self.needs_attention = True
        self.reasons.append(_sanitize_reason(f"{handle}: empty source feed"))

    def note_source_error(self, reason: str) -> None:
        self.degraded = True
        self.needs_attention = True
        self.reasons.append(_sanitize_reason(reason))

    def tokens(self) -> str:
        return (
            f"{self.fetched} fetched · {self.filtered} filtered · {self.queued} queued · "
            f"{self.delivered} delivered · {len(self.reasons)} errors · "
            f"{self.pending} pending · owner pending {self.owner_pending} · "
            f"oldest {self.oldest_pending_minutes}m"
        )


def state_path() -> Path:
    return state.state_path()


def _sanitize_reason(reason: object) -> str:
    value = " ".join(str(reason).split())
    value = _SENSITIVE_VALUE_RE.sub(
        lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=<redacted>",
        value,
    )
    value = _URL_RE.sub("<external source>", value)
    value = _ABSOLUTE_PATH_RE.sub("<local path>", value)
    return re.sub(r"[\x00-\x1f\x7f]", " ", value)[:MAX_REASON_CHARACTERS].strip()


def config_path() -> Path:
    return Path(os.environ.get("X_POST_WATCH_CONFIG_PATH", str(Path(__file__).resolve().parent.parent / "config" / "watches.json")))


def _prepare_agent_vision(post: SourcePost, storage: Path, dry_run: bool, thread_posts: tuple[SourcePost, ...] | None = None):
    if dry_run:
        return None
    return vision_media.prepare(post, vision_media.default_root(storage), thread_posts=thread_posts)


def _prepare_article_context(thread_posts: tuple[SourcePost, ...] | None, dry_run: bool):
    if dry_run or not thread_posts:
        return None
    return article_context.prepare(thread_posts)


def _cleanup_agent_vision(storage: Path, event: dict) -> None:
    try:
        vision_media.cleanup_event(
            vision_media.default_root(storage),
            str(event["profile_id"]),
            str(event["post_id"]),
        )
    except (vision_media.VisionMediaError, OSError):
        pass


def _control_plane_reporter():
    try:
        from control_plane_client import ControlPlaneReporter

        return ControlPlaneReporter.from_environment("X_POST_WATCH")
    except Exception:
        return None


def _report_control_event(
    reporter,
    run_id: str | None,
    event_id: str,
    *,
    level: str,
    phase: str,
    event_type: str,
    message: str,
    attributes: dict[str, object] | None = None,
) -> None:
    if reporter is None or run_id is None:
        return
    try:
        reporter.event(
            run_id,
            event_id,
            level=level,
            phase=phase,
            event_type=event_type,
            message=message,
            attributes=attributes,
            flush=False,
        )
    except Exception:
        pass


def _finish_control_run(reporter, run_id: str | None, status: str, error: str | None = None) -> None:
    if reporter is None or run_id is None:
        return
    try:
        reporter.finish(run_id, status, error)
    except Exception:
        pass


def format_heartbeat(now: datetime, stats: RunStats) -> str:
    suffix = f" · {stats.reasons[0]}" if stats.reasons else ""
    warning = " ⚠️" if stats.degraded else ""
    return f"🫀 {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · {stats.tokens()}" + suffix + warning


def format_fatal(now: datetime, reason: str) -> str:
    failure = _sanitize_reason(reason)[:180]
    return f"❌ {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · failed: {failure}"


def _next_deliverable_index(value: dict, profiles: dict, now: datetime) -> int | None:
    for index, event in enumerate(value["outbox"]):
        profile = profiles.get(event["profile_id"])
        if profile is None:
            continue
        if (
            state.is_ready(event, now)
            and _board_retry_due(event, now)
            and (not profile.uses_llm or event.get("agent_phase") == "ready")
        ):
            return index
    return None


def _queue_metrics(value: dict, profiles: dict, now: datetime) -> tuple[int, int]:
    """Return active LLM outbox count and oldest ready-event age in minutes."""
    pending = 0
    ages: list[int] = []
    for event in value["outbox"]:
        profile = profiles.get(event.get("profile_id"))
        if profile is None or not profile.uses_llm:
            continue
        if event.get("agent_phase") not in {"pending", "awaiting_agent", "ready"}:
            continue
        pending += 1
        ready_after = event.get("ready_after")
        if not isinstance(ready_after, str):
            continue
        try:
            ready_at = datetime.fromisoformat(ready_after)
        except ValueError:
            continue
        if (ready_at.tzinfo is None) != (now.tzinfo is None) or ready_at > now:
            continue
        ages.append(max(0, int((now - ready_at).total_seconds() // 60)))
    return pending, max(ages, default=0)


def _target_channel(profile, event: dict) -> str:
    if not profile.enable_llm_routing:
        return profile.discord_channels[0].channel_id
    return profile.channel_for(normalize_route(profile, event["route"])).channel_id


def capability_for_route(route_key: str) -> str | None:
    return ROUTE_CAPABILITIES.get(route_key)


def eligible_capability_for_route(route_key: str, enabled_capabilities: frozenset[str]) -> str | None:
    capability = capability_for_route(route_key)
    return capability if capability in enabled_capabilities else None


def _event_route_is_eligible(profile, event: dict) -> bool:
    enabled = event.get("enabled_capabilities")
    if enabled is None:
        return True
    route = event.get("route") if profile.enable_llm_routing else profile.discord_channels[0].key
    return eligible_capability_for_route(route, frozenset(enabled)) is not None


def _event_source_ids(event: dict) -> set[str]:
    return {item.get("post_id") for item in event.get("thread_posts", [event.get("post", {})]) if item.get("post_id")}


def _delivery_media(profile, thread_posts, *, route: str | None = None):
    all_media = []
    seen_media: set[str] = set()

    def append_unique(media_items):
        for media in media_items:
            if media.url not in seen_media:
                seen_media.add(media.url)
                all_media.append(media)

    for thread_post in thread_posts:
        append_unique(thread_post.media)
        append_unique(thread_post.quoted_media)
    if profile.media_policy == "omit_last" and route != "id_stocks_swing":
        return all_media[:-1]
    return all_media


def _board_retry_due(event: dict, now: datetime) -> bool:
    if event.get("board_phase") != BOARD_PENDING:
        return True
    value = event.get("board_next_attempt_at")
    if value is None:
        return True
    if not isinstance(value, str):
        return True
    try:
        retry_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    return (retry_at.tzinfo is None) == (now.tzinfo is None) and retry_at <= now


def _ticker_led_clauses(value: str) -> list[str]:
    """Find ticker-led clauses while accepting source titles without colons."""
    clauses = [match.group(1) for match in _TICKER_COLON_CLAUSE.finditer(value)]
    for line in value.splitlines():
        match = _TICKER_SPACE_CLAUSE.match(line)
        if match and not re.match(rf"^\s*{match.group(1)}\s*:", line):
            clauses.append(match.group(1))
    return clauses


def _leading_ticker(value: str) -> str | None:
    match = _TICKER_SOURCE_TITLE.match(value.strip())
    return match.group(1) if match else None


def _source_title_is_single_ticker(source_title: str, ticker: str) -> bool:
    """Reject a first line that visibly names another ticker as a peer."""
    match = _TICKER_SOURCE_TITLE.fullmatch(source_title)
    if match is None or match.group(1) != ticker:
        return False
    body = match.group(2)
    for token_match in _UPPERCASE_TOKEN.finditer(body):
        token = token_match.group(1)
        if token == ticker or token in _NON_TICKER_UPPERCASE:
            continue
        before = body[:token_match.start()]
        if re.search(r"(?:\b(?:and|atau|dan|dengan|serta|versus|vs)\b|[,&/])\s*$", before, re.IGNORECASE):
            return False
    return True


def board_source_event(event: dict, profile, *, status_date: datetime | None = None) -> dict[str, object] | None:
    """Return the narrow source-only board context for an accepted X Swing event."""
    if event.get("route") != "id_stocks_swing":
        return None
    post = state.deserialize_post(event["post"])
    source_title = next((line.strip() for line in source_visible_text(post.content_html).splitlines() if line.strip()), None)
    if source_title is None or len(source_title) > 100:
        return None
    source_match = _TICKER_SOURCE_TITLE.fullmatch(source_title)
    thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]]))
    source_bundle = "\n".join(source_visible_text(item.content_html) for item in thread_posts)
    clauses = _ticker_led_clauses(source_bundle)
    if source_match is None or len(clauses) != 1:
        return None
    title = event.get("title")
    title_ticker = _leading_ticker(title) if isinstance(title, str) else None
    ticker = source_match.group(1)
    if title_ticker is None or ticker != title_ticker or not _source_title_is_single_ticker(source_title, ticker):
        return None
    all_content = "\n\n".join(
        render.render_post(
            profile,
            post,
            event.get("summary") if profile.enable_llm_summary else None,
            event.get("title"),
            thread_posts,
            bool(event.get("updated_tweet")),
            include_board=False,
            include_status_date=True,
            status_date=status_date,
        )
    )
    normalized_source_title = f"{ticker}: {source_match.group(2).strip()}"
    skipped_media = set(event.get("media_skipped_urls", []))
    source_paths = event.get("source_media_paths", {})
    source_urls = [item.url for item in _delivery_media(profile, thread_posts, route=event.get("route"))] if profile.forward_media else []
    from source_media import reference_id
    usable_urls = [url for url in source_urls if url not in skipped_media]
    media_paths = [source_paths[ref] for url in usable_urls
                   if (ref := reference_id(url)) is not None and ref in source_paths]
    return {
        "event_key": f"x:{profile.id}:{post.post_id}",
        "source": "x",
        "kind": "social",
        "ticker": ticker,
        "published_at": post.published_at.isoformat(),
        "source_url": post.url,
        "all_content": all_content,
        "source_title": normalized_source_title,
        "source_status": None,
        "plan": None,
        "media_path": media_paths[0] if media_paths else None,
        "media_paths": media_paths,
        "media_urls": [url for url in usable_urls if reference_id(url) is None],
    }


def _board_wrapper() -> str:
    return os.environ.get(
        "IDX_SWING_PLAN_BOARD_WRAPPER",
        str(Path.home() / ".hermes" / "scripts" / "bursawatch-dc-swing-board.sh"),
    )


def submit_board_event(payload: dict[str, object], dry_run: bool) -> bool:
    if dry_run:
        print(f"[dry-run] board source event {payload['event_key']}")
        return True
    try:
        completed = subprocess.run(
            [_board_wrapper(), "submit-source-event", "--stdin"],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    try:
        acknowledgement = json.loads(completed.stdout.strip())
    except (TypeError, ValueError):
        return False
    if (
        not isinstance(acknowledgement, dict)
        or set(acknowledgement) not in ({"accepted"}, {"accepted", "board_url"}, {"accepted", "board_url", "board_pending"})
        or type(acknowledgement.get("accepted")) is not bool
        or acknowledgement["accepted"] is not True
    ):
        return False
    board_url = acknowledgement.get("board_url")
    if board_url is not None and (type(board_url) is not str or not board_url):
        return False
    board_pending = acknowledgement.get("board_pending", False)
    if type(board_pending) is not bool:
        return False
    payload["_board_url"] = board_url
    payload["_board_pending"] = board_pending
    return True


def _record_board_failure(event: dict, now: datetime) -> None:
    attempts = int(event.get("board_attempts", 0)) + 1
    delay = min(BOARD_RETRY_INITIAL_SECONDS * (2 ** (attempts - 1)), BOARD_RETRY_CAP_SECONDS)
    event["board_phase"] = BOARD_PENDING
    event["board_attempts"] = attempts
    event["board_next_attempt_at"] = (now + timedelta(seconds=delay)).isoformat()
    event["board_last_error"] = "board source event was not accepted"


def _clear_board_failure(event: dict) -> None:
    event["board_attempts"] = 0
    event["board_next_attempt_at"] = None
    event["board_last_error"] = None


def _thread_extension(profile, old: dict, event: dict) -> bool:
    if profile.thread_handling.mode != "self_chain":
        return False
    if old.get("thread_root_id") != event.get("thread_root_id"):
        return False
    old_ids = set(old.get("source_post_ids", []))
    new_ids = _event_source_ids(event)
    if not old_ids or not old_ids < new_ids:
        return False
    try:
        old_time = datetime.fromisoformat(old["published_at"])
        new_time = datetime.fromisoformat(event["post"]["published_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if (old_time.tzinfo is None) != (new_time.tzinfo is None):
        return False
    delta = new_time - old_time
    return timedelta(0) <= delta <= timedelta(minutes=profile.thread_handling.max_age_minutes)


def _annotate_replacements(value: dict, profile, fresh_ids: set[str], verifier: supersession.EditHistoryVerifier, now: datetime, stats: RunStats) -> None:
    if not fresh_ids:
        return
    for event in value["outbox"]:
        if event.get("profile_id") != profile.id or not (_event_source_ids(event) & fresh_ids):
            continue
        replacement_ids = event.setdefault("replacement_of", [])
        checks = event.setdefault("supersession_checks", {})
        for old in value["deliveries"]:
            old_id = old.get("delivery_id")
            if old.get("profile_id") != profile.id or not old_id:
                continue
            if old.get("superseded_by") or old.get("replacement_pending") or old_id in replacement_ids:
                continue
            if any(item.get("replacement_of") and old_id in item.get("replacement_of", []) for item in value["outbox"]):
                continue
            if _thread_extension(profile, old, event):
                replacement_ids.append(old_id)
                event["updated_tweet"] = True
                continue
            if not supersession.is_candidate(old, event):
                continue
            confirmed = False
            for old_post, new_post in supersession.candidate_pairs(old, event):
                pair_key = f"{old_post.get('post_id')}:{new_post.get('post_id')}"
                previous = checks.get(pair_key)
                if isinstance(previous, dict) and previous.get("status") == "not_superseded":
                    continue
                if isinstance(previous, dict) and previous.get("status") == "unknown":
                    try:
                        checked_at = datetime.fromisoformat(previous["checked_at"])
                        if now - checked_at < timedelta(minutes=15):
                            continue
                    except (KeyError, TypeError, ValueError):
                        pass
                result = verifier.verify(old_post.get("url", ""), old_post.get("post_id", ""), new_post.get("post_id", ""))
                checks[pair_key] = {"status": result.status, "checked_at": now.isoformat()}
                if result.status == "confirmed":
                    confirmed = True
                    break
                if result.status == "unknown":
                    attention_key = f"{old_id}:{pair_key}"
                    attention = event.setdefault("supersession_attention", [])
                    if attention_key not in attention:
                        attention.append(attention_key)
                        stats.note_source_error(f"{profile.id}: {result.reason} for {old_post.get('post_id')} to {new_post.get('post_id')}")
            if confirmed:
                replacement_ids.append(old_id)
                event["updated_tweet"] = True


def _retry_cleanup(value: dict, dry_run: bool, storage: Path, stats: RunStats) -> None:
    if dry_run:
        return
    for item in list(value["cleanup"]):
        remaining: list[str] = []
        for message_id in item.get("message_ids", []):
            try:
                discord.delete_message(item["channel_id"], message_id, dry_run)
            except Exception as exc:
                remaining.append(message_id)
                if isinstance(exc, discord.DeliveryOwnerPending):
                    stats.owner_pending += 1
                else:
                    stats.note_source_error(f"supersession cleanup: {' '.join(str(exc).split())[:140]}")
        item["attempts"] = int(item.get("attempts", 0)) + 1
        if remaining:
            item["message_ids"] = remaining
        else:
            state.finish_cleanup(value, item)
    state.save_state(storage, value)


def _delivery_at(event: dict, now: datetime | None) -> datetime:
    """Return the durable first-delivery instant used by Swing status dates."""
    value = event.get("delivery_at")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return parsed
        except ValueError:
            pass
    current = now or datetime.now(WIB)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("delivery time must include a timezone")
    return current


def _drain_publications(value: dict, dry_run: bool, storage: Path, stats: RunStats, now: datetime) -> None:
    if not publication_projection.enabled():
        return
    result = publication_projection.drain(
        value,
        now,
        dry_run=dry_run,
        persist=lambda: state.save_state(storage, value),
    )
    if result["pending"]:
        stats.note_source_error("Published projection pending")


def _deliver(value: dict, profiles: dict, event_index: int, dry_run: bool, storage: Path, stats: RunStats, now: datetime | None = None) -> bool:
    event = value["outbox"][event_index]
    profile = profiles[event["profile_id"]]
    if not _event_route_is_eligible(profile, event):
        state.suppress_ineligible(value, event)
        state.save_state(storage, value)
        return True
    event.setdefault("board_phase", BOARD_PENDING)
    event.setdefault("board_attempts", 0)
    event.setdefault("board_next_attempt_at", None)
    event.setdefault("board_last_error", None)
    event.setdefault("media_skipped_urls", [])
    event.setdefault("media_errors", [])
    post = state.deserialize_post(event["post"])
    thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]]))
    channel_id = _target_channel(profile, event)
    attempt_at = now or datetime.now(WIB)
    delivery_at = _delivery_at(event, attempt_at)
    messages = render.render_post(
        profile,
        post,
        event.get("summary") if profile.enable_llm_summary else None,
        event.get("title"),
        thread_posts,
        bool(event.get("updated_tweet")),
        include_board=event.get("route") == "id_stocks_swing",
        include_status_date=event.get("route") == "id_stocks_swing",
        status_date=delivery_at if event.get("route") == "id_stocks_swing" else None,
    )
    cards = event.get("news_cards")
    targets = None
    if cards is not None:
        render.news_format.validate_cards(cards)
        messages = [message for card in cards for message in card["messages"]]
        targets = [card["destination"] for card in cards for message in card["messages"]]
        channel_id = targets[0]
    media_url: str | None = None
    try:
        while event["text_index"] < len(messages):
            index = event["text_index"]
            text_channel = targets[index] if targets else channel_id
            nonce_value = discord.nonce(f"{profile.id}:{post.post_id}", f"text:{index}")
            if publication_projection.enabled():
                message_id, operation, receipt = discord.post_text_with_receipt(
                    messages[index], text_channel, dry_run, nonce_value,
                )
                if operation is not None and receipt is not None:
                    event.setdefault("publication_legs", []).append(
                        publication_projection.confirmed_leg(operation, receipt, text=messages[index])
                    )
            else:
                message_id = discord.post_text(messages[index], text_channel, dry_run, nonce_value)
            if message_id is not None:
                event.setdefault("text_message_ids", []).append(message_id)
            event["text_index"] += 1
            if event.get("route") == "id_stocks_swing" and event.get("delivery_at") is None:
                event["delivery_at"] = delivery_at.isoformat()
            state.save_state(storage, value)
            continue
        all_media = _delivery_media(profile, thread_posts, route=event.get("route"))
        while profile.forward_media and event["media_index"] < len(all_media):
            index = event["media_index"]
            media_url = all_media[index].url
            from source_media import reference_id
            ref = reference_id(media_url)
            reference = event.get("source_media_refs", {}).get(ref) if ref else None
            media_arguments = {"source_reference": reference} if ref else {}
            nonce_value = discord.nonce(f"{profile.id}:{post.post_id}", f"media:{index}")
            if publication_projection.enabled():
                message_id, operation, receipt = discord.post_media_with_receipt(
                    media_url, channel_id, dry_run, nonce_value, storage.parent / "media", **media_arguments,
                )
                if operation is not None and receipt is not None:
                    event.setdefault("publication_legs", []).append(
                        publication_projection.confirmed_leg(operation, receipt, text=None)
                    )
            else:
                message_id = discord.post_media(
                    media_url, channel_id, dry_run, nonce_value, storage.parent / "media", **media_arguments,
                )
            if message_id is not None:
                event.setdefault("media_message_ids", []).append(message_id)
            event["media_index"] += 1
            state.save_state(storage, value)
            continue
    except Exception as exc:
        if isinstance(exc, discord.DeliveryOwnerPending):
            stats.owner_pending += 1
            event["last_error"] = "Delivery Owner accepted pending work"
            state.save_state(storage, value)
            return False
        if media_url is not None and isinstance(exc, discord.MediaUnavailable):
            if media_url not in event["media_skipped_urls"]:
                event["media_skipped_urls"].append(media_url)
            event["media_errors"].append({"url": media_url, "status": exc.status_code})
            event["media_index"] += 1
            event["last_error"] = str(exc)
            stats.degraded = True
            stats.needs_attention = True
            stats.reasons.append(_sanitize_reason(event["last_error"]))
            state.save_state(storage, value)
            return True
        event["last_error"] = " ".join(str(exc).split())[:180]
        stats.degraded = True
        stats.needs_attention = True
        stats.reasons.append(_sanitize_reason(event["last_error"]))
        state.save_state(storage, value)
        return False
    delivered_at = attempt_at
    if event.get("route") == "id_stocks_swing" and event.get("delivery_at") is None:
        event["delivery_at"] = delivery_at.isoformat()
    record = state.record_delivery(value, event, channel_id, delivered_at, dry_run)
    if record is not None:
        state.queue_replacement_cleanup(value, record)
    if not dry_run and publication_projection.enabled():
        confirmed_at = event.get("publication_delivery_confirmed_at")
        if not isinstance(confirmed_at, str):
            confirmed_at = datetime.now().astimezone().isoformat()
            event["publication_delivery_confirmed_at"] = confirmed_at
        publication_projection.record_confirmed_event(
            value,
            event,
            profile,
            datetime.fromisoformat(confirmed_at),
        )
    # The All delivery is durable before the owner sees a source event. A
    # retry below must therefore never revisit text, media, routing, or agent
    # work.
    state.save_state(storage, value)
    payload = board_source_event(event, profile, status_date=delivery_at if event.get("route") == "id_stocks_swing" else None)
    if payload is None:
        event["board_phase"] = BOARD_UNAVAILABLE
        value["outbox"].pop(event_index)
        state.save_state(storage, value)
        stats.delivered += 1
        return True
    if not _board_retry_due(event, delivered_at):
        return False
    if not submit_board_event(payload, dry_run):
        _record_board_failure(event, delivered_at)
        stats.degraded = True
        stats.needs_attention = True
        stats.reasons.append(_sanitize_reason(event["board_last_error"]))
        state.save_state(storage, value)
        return False
    if payload.get("_board_pending"):
        _record_board_failure(event, delivered_at)
        stats.degraded = True
        stats.needs_attention = True
        stats.reasons.append("board topic is not materialized yet")
        state.save_state(storage, value)
        return False
    if not discord.edit_board_links(
        channel_id,
        event.get("text_message_ids", []),
        payload.get("_board_url"),
        dry_run,
        event_key=f"{profile.id}:{post.post_id}",
    ):
        _record_board_failure(event, delivered_at)
        stats.degraded = True
        stats.needs_attention = True
        stats.reasons.append("All Swing board link update failed")
        state.save_state(storage, value)
        return False
    _clear_board_failure(event)
    value["outbox"].pop(event_index)
    state.save_state(storage, value)
    stats.delivered += 1
    return True


def run(
    now: datetime | None = None,
    dry_run: bool | None = None,
    queue_only: bool | None = None,
) -> dict[str, object]:
    now = now or datetime.now(WIB)
    dry_run = bool(dry_run) or os.environ.get("X_POST_WATCH_NO_POST") == "1"
    queue_only = (
        os.environ.get("X_POST_WATCH_QUEUE_ONLY") == "1"
        if queue_only is None
        else bool(queue_only)
    )
    storage = state_path()
    storage.parent.mkdir(parents=True, exist_ok=True)
    with (storage.parent / "run.lock").open("w") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return build_wake_payload(None)
        stats = RunStats()
        reporter = None
        run_id = None
        try:
            loaded_config = config.load_watch_config_for_run(config_path())
            watches = loaded_config.config
            if loaded_config.revision is not None:
                reporter = _control_plane_reporter()
                if reporter is not None:
                    run_id = reporter.start_run(
                        loaded_config.revision,
                        scheduler_job_id=os.environ.get(
                            "X_POST_WATCH_SCHEDULER_JOB_ID",
                            "x-post-queue-worker" if queue_only else "x-post-source",
                        ),
                        trigger="queue" if queue_only else "scheduled",
                    )
                    _report_control_event(
                        reporter,
                        run_id,
                        "run-started",
                        level="info",
                        phase="lifecycle",
                        event_type="run.started",
                        message="X watcher run started",
                        attributes={
                            "config_revision": loaded_config.revision,
                            "queue_only": queue_only,
                            "dry_run": dry_run,
                        },
                    )
            value = state.load_state(storage)
            state.prune_deliveries(value, now)
            stats.filtered = state.take_filtered_since_last_heartbeat(value)
            profiles = {profile.id: profile for profile in watches.profiles}
            verifier = supersession.EditHistoryVerifier()
            _retry_cleanup(value, dry_run, storage, stats)
            if not queue_only:
                for profile in watches.profiles:
                    if not profile.enabled: continue
                    try:
                        if state.source_retry_active(value, now):
                            break
                        record = value["profiles"].get(profile.id) or {}
                        posts = rsshub.fetch_profile_items(profile, after_id=record.get("cursor"))
                        stats.fetched += len(posts)
                        empty_feed = not posts and (profile.source not in {"direct_x", "hybrid"} or record.get("cursor") is None)
                        if empty_feed:
                            stats.note_empty_profile(profile.handle)
                        fresh_ids = state.fresh_post_ids(value, profile, posts)
                        queued, observation_reason = state.observe_posts(
                            value, profile, posts,
                            lambda post: rsshub.is_forwardable(profile, post),
                            lambda post: rsshub.is_self_thread_post(profile, post), now,
                        )
                        stats.queued += queued
                        if observation_reason:
                            stats.degraded = True
                            stats.needs_attention = True
                            stats.reasons.append(_sanitize_reason(f"{profile.id}: {observation_reason}"))
                        _annotate_replacements(value, profile, fresh_ids, verifier, now, stats)
                        state.save_state(storage, value)
                        source_reason = observation_reason or ("empty source feed" if empty_feed else None)
                        _report_control_event(
                            reporter,
                            run_id,
                            f"source-fetch-{profile.id}",
                            level="warning" if source_reason else "info",
                            phase="source",
                            event_type="source.fetch.completed",
                            message=f"{profile.id}: fetched {len(posts)} source items",
                            attributes={
                                "profile_id": profile.id,
                                "items": len(posts),
                                "queued": queued,
                                "reason": _sanitize_reason(source_reason) if source_reason else None,
                            },
                        )
                    except rsshub.SourceFetchError as exc:
                        if exc.retry_after_seconds is not None:
                            state.set_source_retry(value, now, exc.retry_after_seconds)
                            state.save_state(storage, value)
                        stats.note_source_error(f"{profile.id}: {exc}")
                        _report_control_event(
                            reporter,
                            run_id,
                            f"source-fetch-{profile.id}",
                            level="warning",
                            phase="source",
                            event_type="source.fetch.failed",
                            message=f"{profile.id}: source fetch failed",
                            attributes={"profile_id": profile.id, "error": _sanitize_reason(exc)},
                        )
            while (event_index := _next_deliverable_index(value, profiles, now)) is not None:
                if not _deliver(value, profiles, event_index, dry_run, storage, stats, now): break
            _retry_cleanup(value, dry_run, storage, stats)
            _drain_publications(value, dry_run, storage, stats, now)
            stats.pending, stats.oldest_pending_minutes = _queue_metrics(value, profiles, now)
            _report_control_event(
                reporter,
                run_id,
                "delivery-drain-completed",
                level="warning" if stats.degraded else "info",
                phase="delivery",
                event_type="delivery.drain.completed",
                message="X watcher delivery drain completed",
                attributes={
                    "queue_only": queue_only,
                    "delivered": stats.delivered,
                    "pending": stats.pending,
                    "owner_pending": stats.owner_pending,
                    "oldest_pending_minutes": stats.oldest_pending_minutes,
                    "reasons": stats.reasons[:10],
                },
            )
            heartbeat_leg = now.astimezone(WIB).strftime("%Y%m%d%H%M")
            event = state.claim_oldest_agent(value, profiles, now)
            state.save_state(storage, value)
            post = state.deserialize_post(event["post"]) if event else None
            thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]])) if event else None
            vision_bundle = None
            article_bundle = None
            if event is not None and post is not None:
                try:
                    claimed_event_key = f"{event['profile_id']}:{event['post_id']}"
                    claimed_lease = event.get("agent_lease_until")
                    # Remote enrichment must not block delivery or the next
                    # minute-level worker. The persisted lease is rechecked
                    # before its contexts are handed to Hermes.
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    try:
                        try:
                            if event.get("source_media_refs") and not dry_run:
                                vision_bundle = vision_media.prepare(
                                    post, vision_media.default_root(storage),
                                    reference_meta=event["source_media_refs"],
                                    thread_posts=thread_posts,
                                )
                            else:
                                vision_bundle = _prepare_agent_vision(post, storage, dry_run, thread_posts)
                            if vision_bundle is not None and vision_bundle.unavailable_count:
                                stats.note_source_error("vision image preparation incomplete")
                        except vision_media.VisionMediaError:
                            if event.get("source_media_refs"):
                                raise
                            stats.note_source_error("vision image preparation failed")
                        try:
                            article_bundle = _prepare_article_context(thread_posts, dry_run)
                            if article_bundle is not None and article_bundle.unavailable_count:
                                stats.note_source_error("linked article retrieval incomplete")
                        except article_context.ArticleFetchError:
                            stats.note_source_error("linked article retrieval failed")
                    finally:
                        fcntl.flock(lock, fcntl.LOCK_EX)
                    value = state.load_state(storage)
                    current_event = state.awaiting_analysis_event(value, claimed_event_key)
                    if current_event.get("agent_lease_until") != claimed_lease:
                        raise ValueError("claimed event lease changed during enrichment")
                    event = current_event
                    post = state.deserialize_post(event["post"])
                    thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]]))
                except ValueError:
                    event = None
                    post = None
                    thread_posts = None
                    vision_bundle = None
                    article_bundle = None
            wake_payload = build_wake_payload(
                agent_item(profiles[event["profile_id"]], post, thread_posts, vision_bundle, article_bundle)
                if event and post else None
            )
            try:
                discord.post_text(
                    format_heartbeat(now, stats),
                    HEARTBEAT_CHANNEL_ID,
                    dry_run,
                    discord.nonce("heartbeat", heartbeat_leg),
                )
            except discord.DeliveryOwnerPending:
                stats.owner_pending += 1
            if event is not None:
                _report_control_event(
                    reporter,
                    run_id,
                    "agent-wake-requested",
                    level="info",
                    phase="agent",
                    event_type="agent.wake.requested",
                    message="X event claimed for agent analysis",
                    attributes={"profile_id": event["profile_id"]},
                )
            _report_control_event(
                reporter,
                run_id,
                "run-completed",
                level="warning" if stats.degraded else "info",
                phase="lifecycle",
                event_type="run.completed",
                message="X watcher run completed",
                attributes={
                    "fetched": stats.fetched,
                    "filtered": stats.filtered,
                    "queued": stats.queued,
                    "delivered": stats.delivered,
                    "pending": stats.pending,
                    "oldest_pending_minutes": stats.oldest_pending_minutes,
                    "degraded": stats.degraded,
                    "reasons": stats.reasons[:10],
                },
            )
            _finish_control_run(reporter, run_id, "degraded" if stats.degraded else "ok")
            return wake_payload
        except Exception as exc:
            reason = _sanitize_reason(exc)
            _report_control_event(
                reporter,
                run_id,
                "run-failed",
                level="fatal",
                phase="lifecycle",
                event_type="run.failed",
                message="X watcher run failed",
                attributes={"error": reason},
            )
            _finish_control_run(reporter, run_id, "failed", reason)
            try: discord.post_text(format_fatal(now, str(exc)), HEARTBEAT_CHANNEL_ID, dry_run, discord.nonce("fatal", now.astimezone(WIB).strftime("%Y%m%d%H%M")))
            except Exception: pass
            raise


def submit_analysis_payload(payload: object, dry_run: bool | None = None) -> dict[str, object]:
    if type(payload) is not dict or not isinstance(payload.get("event_key"), str):
        raise ValueError("analysis submission requires an event_key")
    storage = state_path()
    storage.parent.mkdir(parents=True, exist_ok=True)
    dry_run = bool(dry_run) or os.environ.get("X_POST_WATCH_NO_POST") == "1"
    reporter = None
    run_id = None
    try:
        with (storage.parent / "run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            loaded_config = config.load_watch_config_for_run(config_path())
            watches = loaded_config.config
            if loaded_config.revision is not None:
                reporter = _control_plane_reporter()
                if reporter is not None:
                    run_id = reporter.start_run(
                        loaded_config.revision,
                        scheduler_job_id="x-post-source",
                        trigger="agent_submission",
                    )
                    _report_control_event(
                        reporter,
                        run_id,
                        "agent-submission-started",
                        level="info",
                        phase="agent",
                        event_type="agent.submission.started",
                        message="X agent submission started",
                        attributes={"dry_run": dry_run},
                    )
            value = state.load_state(storage)
            profiles = {profile.id: profile for profile in watches.profiles}
            profile_id = payload["event_key"].partition(":")[0]
            profile = profiles.get(profile_id)
            if profile is None or not profile.uses_llm:
                raise ValueError("analysis profile is not enabled")
            analysis = validate_submission(profile, payload)
            event = state.awaiting_analysis_event(value, analysis["event_key"])
            post = state.deserialize_post(event["post"])
            thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]]))
            if analysis.get("is_relevant") is False:
                state.discard_analysis(value, analysis["event_key"])
                state.save_state(storage, value)
                _cleanup_agent_vision(storage, event)
                _report_control_event(
                    reporter,
                    run_id,
                    "agent-submission-accepted",
                    level="info",
                    phase="agent",
                    event_type="agent.submission.accepted",
                    message="X agent submission accepted as irrelevant",
                    attributes={"is_relevant": False, "delivered": 0},
                )
                _finish_control_run(reporter, run_id, "ok")
                return {"submitted": True, "ignored": True, "delivered": 0}
            news_items = analysis.pop("news_items", None)
            route_override = deterministic_route(profile, post, thread_posts) if news_items is None else None
            if route_override is not None:
                analysis["route"] = route_override
            if news_items is not None:
                allowed = event.get("enabled_capabilities")
                news_items = [item for item in news_items if allowed is None or eligible_capability_for_route(item["route"], frozenset(allowed)) is not None]
                if news_items:
                    analysis.update(news_items[0])
                else:
                    state.suppress_ineligible(value, event)
                    state.save_state(storage, value)
                    _cleanup_agent_vision(storage, event)
                    _finish_control_run(reporter, run_id, "ok")
                    return {"submitted": True, "suppressed": "suppressed_ineligible", "delivered": 0}
            candidate_route = analysis.get("route") if profile.enable_llm_routing else profile.discord_channels[0].key
            if event.get("enabled_capabilities") is not None and eligible_capability_for_route(candidate_route, frozenset(event["enabled_capabilities"])) is None:
                state.suppress_ineligible(value, event)
                state.save_state(storage, value)
                _cleanup_agent_vision(storage, event)
                _report_control_event(
                    reporter, run_id, "agent-submission-accepted", level="info", phase="agent",
                    event_type="agent.submission.accepted", message="X agent submission suppressed by frozen source capability",
                    attributes={"is_relevant": True, "delivered": 0, "outcome": "suppressed_ineligible"},
                )
                _finish_control_run(reporter, run_id, "ok")
                return {"submitted": True, "suppressed": "suppressed_ineligible", "delivered": 0}
            if profile.enable_llm_summary and candidate_route in {"id_stocks_news", "us_stocks_news", "macro_news"}:
                analysis["news_cards"] = render.freeze_news(profile, post, news_items or [{"title": analysis.get("title") or profile.display_name, "summary": analysis["summary"], "route": candidate_route}], updated_tweet=bool(event.get("updated_tweet")))
            state.submit_analysis(value, analysis["event_key"], {key: item for key, item in analysis.items() if key not in {"event_key", "is_relevant"}})
            state.save_state(storage, value)
            _cleanup_agent_vision(storage, event)
            stats = RunStats()
            now = datetime.now(WIB)
            while (event_index := _next_deliverable_index(value, profiles, now)) is not None:
                if not _deliver(value, profiles, event_index, dry_run, storage, stats, now):
                    break
            _retry_cleanup(value, dry_run, storage, stats)
            _drain_publications(value, dry_run, storage, stats, now)
            _report_control_event(
                reporter,
                run_id,
                "agent-submission-accepted",
                level="info",
                phase="agent",
                event_type="agent.submission.accepted",
                message="X agent submission accepted",
                attributes={"is_relevant": True, "delivered": stats.delivered},
            )
            _report_control_event(
                reporter,
                run_id,
                "agent-delivery-drain-completed",
                level="warning" if stats.degraded else "info",
                phase="delivery",
                event_type="delivery.drain.completed",
                message="X agent delivery drain completed",
                attributes={
                    "delivered": stats.delivered,
                    "reasons": stats.reasons[:10],
                },
            )
            _finish_control_run(reporter, run_id, "degraded" if stats.degraded else "ok")
            return {"submitted": True, "delivered": stats.delivered}
    except Exception as exc:
        reason = _sanitize_reason(exc)
        rejected = isinstance(exc, ValueError)
        _report_control_event(
            reporter,
            run_id,
            "agent-submission-rejected" if rejected else "agent-submission-failed",
            level="warning" if rejected else "fatal",
            phase="agent",
            event_type="agent.submission.rejected" if rejected else "agent.submission.failed",
            message="X agent submission rejected" if rejected else "X agent submission failed",
            attributes={"reason" if rejected else "error": reason},
        )
        _finish_control_run(reporter, run_id, "degraded" if rejected else "failed", reason)
        raise


def recover_missing_source(urls: list[str], *, apply: bool = False) -> dict[str, object]:
    if not 1 <= len(urls) <= 10:
        raise ValueError("recovery requires one to ten explicit X status URLs")
    if apply and os.environ.get("X_POST_WATCH_RECOVERY_APPLY") != "1":
        raise ValueError("recovery apply requires X_POST_WATCH_RECOVERY_APPLY=1")
    if apply and os.environ.get("X_POST_WATCH_NO_POST") == "1":
        raise ValueError("recovery apply is unavailable in no-post mode")
    storage = state_path()
    loaded = config.load_watch_config_for_run(config_path())
    observed_at = datetime.now(WIB)
    cached_payloads = {}

    def fetch(profile, post_id):
        key = (profile.id, post_id)
        if key not in cached_payloads:
            cached_payloads[key] = recovery.fetch_public_detail(profile, post_id)
        return cached_payloads[key]

    rows = recovery.preview(state.load_state(storage), loaded.config.profiles, urls, observed_at, fetch)
    if apply:
        storage.parent.mkdir(parents=True, exist_ok=True)
        with (storage.parent / "run.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            current = config.load_watch_config_for_run(config_path())
            if current != loaded:
                raise ValueError("X configuration changed during recovery preview")
            value = state.load_state(storage)
            rows = recovery.preview(value, current.config.profiles, urls, observed_at, fetch)
            if any(row.status != "eligible" for row in rows):
                raise ValueError("recovery preview changed or contains ineligible posts")
            created = recovery.apply(value, rows, observed_at)
            if created != len(rows):
                raise ValueError("recovery could not queue every eligible post")
            state.save_state(storage, value)
    else:
        created = 0
    return {
        "applied": apply,
        "queued": created,
        "posts": [
            {
                "profile_id": row.profile.id,
                "post_id": row.post.post_id,
                "published_at": row.post.published_at.isoformat(),
                "media_count": len(row.post.media),
                "status": row.status,
            }
            for row in rows
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    submit = subparsers.add_parser("submit-analysis")
    submit.add_argument("--json", required=True, dest="payload")
    recover = subparsers.add_parser("recover-missing")
    recover.add_argument("--status-url", action="append", required=True, dest="urls")
    recover.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.command == "submit-analysis":
            result = submit_analysis_payload(json.loads(arguments.payload))
        elif arguments.command == "recover-missing":
            result = recover_missing_source(arguments.urls, apply=arguments.apply)
        else:
            result = run()
    except Exception as exc:
        print(json.dumps({"wakeAgent": False, "error": " ".join(str(exc).split())[:180]}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False))
