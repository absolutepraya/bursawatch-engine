from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from models import PostKind, Profile, SourceMedia, SourcePost

SOURCE_RATE_LIMIT_COOLDOWN_SECONDS = 3 * 60 * 60
STATE_VERSION = 3
BOARD_PENDING = "pending"


def new_state() -> dict:
    return {
        "version": STATE_VERSION,
        "profiles": {},
        "outbox": [],
        "deliveries": [],
        "cleanup": [],
        "filtered_since_last_heartbeat": 0,
    }


def load_state(path: Path) -> dict:
    if not path.exists(): return new_state()
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict or value.get("version") not in {1, 2, STATE_VERSION} or type(value.get("profiles")) is not dict or type(value.get("outbox")) is not list:
        raise ValueError("x-post-watch state is invalid")
    if value.get("version") in {1, 2}:
        value["version"] = STATE_VERSION
    if "deliveries" not in value:
        value["deliveries"] = []
    if "cleanup" not in value:
        value["cleanup"] = []
    if type(value["deliveries"]) is not list or type(value["cleanup"]) is not list:
        raise ValueError("x-post-watch state is invalid")
    if "filtered_since_last_heartbeat" not in value:
        value["filtered_since_last_heartbeat"] = 0
    if type(value["filtered_since_last_heartbeat"]) is not int or value["filtered_since_last_heartbeat"] < 0:
        raise ValueError("x-post-watch state is invalid")
    legacy_source_retry = False
    for record in value["profiles"].values():
        if type(record) is dict and record.pop("source_retry_until", None) is not None:
            legacy_source_retry = True
    if legacy_source_retry and not isinstance(value.get("source_retry_until"), str):
        value["source_retry_until"] = (
            datetime.now(UTC) + timedelta(seconds=SOURCE_RATE_LIMIT_COOLDOWN_SECONDS)
        ).isoformat()
    # Summary-only events predate title generation. Requeue them as one fresh
    # agent task so the title and summary are produced together before any
    # delivery. This is a schema migration, never a cursor reset or replay.
    for event in value["outbox"]:
        event.setdefault("text_message_ids", [])
        event.setdefault("media_message_ids", [])
        event.setdefault("media_skipped_urls", [])
        event.setdefault("media_errors", [])
        event.setdefault("delivery_at", None)
        event.setdefault("replacement_of", [])
        event.setdefault("board_phase", BOARD_PENDING)
        event.setdefault("board_attempts", 0)
        event.setdefault("board_next_attempt_at", None)
        event.setdefault("board_last_error", None)
        if "summary_phase" in event:
            event.pop("summary_phase", None)
            event.pop("summary_lease_until", None)
            event["title"] = None
            event["summary"] = None
            event["route"] = None
            event["agent_phase"] = "pending"
            event["agent_lease_until"] = None
    return value


def fresh_post_ids(value: dict, profile: Profile, posts: list[SourcePost]) -> set[str]:
    record = value["profiles"].get(profile.id)
    if record is None or record.get("cursor") is None:
        return set()
    cursor = int(record.get("cursor") or 0)
    return {post.post_id for post in posts if int(post.post_id) > cursor}


def source_retry_active(state: dict, now: datetime) -> bool:
    value = state.get("source_retry_until")
    if not isinstance(value, str):
        return False
    try:
        retry_until = datetime.fromisoformat(value)
    except ValueError:
        state.pop("source_retry_until", None)
        return False
    if (retry_until.tzinfo is None) != (now.tzinfo is None):
        state.pop("source_retry_until", None)
        return False
    if retry_until > now:
        return True
    state.pop("source_retry_until", None)
    return False


def set_source_retry(state: dict, now: datetime, retry_after_seconds: int | None) -> None:
    if retry_after_seconds is None or retry_after_seconds <= 0:
        return
    state["source_retry_until"] = (now + timedelta(seconds=retry_after_seconds)).isoformat()


def _delivery_id(event: dict) -> str:
    return f"{event['profile_id']}:{event['post_id']}"


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def prune_deliveries(value: dict, now: datetime, retention_days: int = 90) -> None:
    cutoff = now - timedelta(days=retention_days)
    pending = {item.get("old_delivery_id") for item in value["cleanup"] if isinstance(item, dict)}
    kept: list[dict] = []
    for record in value["deliveries"]:
        delivered_at = _parse_time(record.get("delivered_at"))
        if delivered_at is None or delivered_at >= cutoff or record.get("delivery_id") in pending:
            kept.append(record)
    value["deliveries"] = kept


def delivery_by_id(value: dict, delivery_id: str) -> dict | None:
    return next((item for item in value["deliveries"] if item.get("delivery_id") == delivery_id), None)


def pending_cleanup_for(value: dict, delivery_id: str) -> bool:
    return any(item.get("old_delivery_id") == delivery_id for item in value["cleanup"])


def record_delivery(value: dict, event: dict, channel_id: str, delivered_at: datetime, dry_run: bool) -> dict | None:
    if dry_run:
        return None
    delivery_id = _delivery_id(event)
    existing = delivery_by_id(value, delivery_id)
    if existing is not None:
        return existing
    thread_posts = event.get("thread_posts") or [event["post"]]
    record = {
        "delivery_id": delivery_id,
        "profile_id": event["profile_id"],
        "thread_root_id": event.get("thread_root_id", event["post_id"]),
        "post_id": event["post_id"],
        "source_post_ids": [item["post_id"] for item in thread_posts],
        "source_urls": [item["url"] for item in thread_posts],
        "thread_posts": thread_posts,
        "published_at": event["post"].get("published_at"),
        "channel_id": channel_id,
        "text_message_ids": list(event.get("text_message_ids", [])),
        "media_message_ids": list(event.get("media_message_ids", [])),
        "media_skipped_urls": list(event.get("media_skipped_urls", [])),
        "media_errors": list(event.get("media_errors", [])),
        "delivered_at": delivered_at.isoformat(),
        "superseded_by": None,
        "replacement_of": list(event.get("replacement_of", [])),
        "replacement_pending": False,
    }
    value["deliveries"].append(record)
    return record


def queue_replacement_cleanup(value: dict, new_record: dict) -> None:
    for old_id in new_record.get("replacement_of", []):
        old = delivery_by_id(value, old_id)
        if old is None or old.get("superseded_by") or pending_cleanup_for(value, old_id):
            continue
        message_ids = list(old.get("text_message_ids", [])) + list(old.get("media_message_ids", []))
        old["replacement_pending"] = True
        if not message_ids:
            old["superseded_by"] = new_record["delivery_id"]
            old["replacement_pending"] = False
            continue
        value["cleanup"].append({
            "old_delivery_id": old_id,
            "replacement_delivery_id": new_record["delivery_id"],
            "channel_id": old["channel_id"],
            "message_ids": message_ids,
            "attempts": 0,
        })


def finish_cleanup(value: dict, item: dict) -> None:
    old = delivery_by_id(value, item["old_delivery_id"])
    if old is not None:
        old["superseded_by"] = item["replacement_delivery_id"]
        old["replacement_pending"] = False
    value["cleanup"].remove(item)


def save_state(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def serialize_post(post: SourcePost) -> dict:
    value = asdict(post)
    value["published_at"] = post.published_at.isoformat()
    value["kind"] = post.kind.value
    return value


def deserialize_post(value: dict) -> SourcePost:
    return SourcePost(
        profile_id=value["profile_id"], post_id=value["post_id"], url=value["url"],
        published_at=datetime.fromisoformat(value["published_at"]), content_html=value["content_html"],
        kind=PostKind(value["kind"]), quoted_url=value["quoted_url"], quoted_content_html=value["quoted_content_html"],
        media=tuple(SourceMedia(**media) for media in value["media"]),
        quoted_media=tuple(SourceMedia(**media) for media in value["quoted_media"]),
        related_url=value.get("related_url"),
        quoted_article_url=value.get("quoted_article_url"),
        quoted_article_label=value.get("quoted_article_label"),
    )


def _post_from_thread(post: SourcePost) -> SourcePost:
    """A self-quote is a continuation, not an external quote card."""
    if post.kind is PostKind.QUOTE:
        return SourcePost(
            profile_id=post.profile_id, post_id=post.post_id, url=post.url,
            published_at=post.published_at, content_html=post.content_html,
            kind=post.kind, quoted_url=None, quoted_content_html=None,
            media=post.media, quoted_media=(), related_url=post.related_url,
            quoted_article_url=post.quoted_article_url, quoted_article_label=post.quoted_article_label,
        )
    return post


def _self_chain(profile: Profile, post: SourcePost, by_id: dict[str, SourcePost], is_self_thread: callable) -> tuple[SourcePost, ...]:
    if profile.thread_handling.mode != "self_chain":
        return (post,)
    chain = [post]
    current = post
    seen = {post.post_id}
    while is_self_thread(current) and current.related_url:
        parent_id = current.related_url.rsplit("/", 1)[-1]
        parent = by_id.get(parent_id)
        if parent is None or parent.post_id in seen:
            break
        chain.append(parent)
        seen.add(parent.post_id)
        current = parent
    chain.reverse()
    return tuple(_post_from_thread(item) if is_self_thread(item) else item for item in chain[-profile.thread_handling.max_posts:])


def _within_thread_age(profile: Profile, posts: tuple[SourcePost, ...]) -> tuple[SourcePost, ...]:
    if not posts:
        return posts
    newest = posts[-1].published_at
    minimum = newest - timedelta(minutes=profile.thread_handling.max_age_minutes)
    recent = tuple(post for post in posts if post.published_at >= minimum)
    return recent or (posts[-1],)


def _event_for_thread(state: dict, profile: Profile, thread: tuple[SourcePost, ...], now: datetime, settle_minutes: int) -> bool:
    root_id = thread[0].post_id
    latest = thread[-1]
    serialized = [serialize_post(post) for post in thread]
    is_multi_post_chain = len(thread) > 1
    immediate = now.isoformat()
    deadline = (now + timedelta(minutes=settle_minutes)).isoformat()
    existing = next((event for event in state["outbox"] if event.get("profile_id") == profile.id and event.get("thread_root_id") == root_id), None)
    if existing is not None:
        if existing.get("agent_phase") not in {None, "pending"}:
            return False
        if existing.get("post_id") == latest.post_id and existing.get("thread_posts") == serialized:
            return False
        existing.update({
            "post_id": latest.post_id,
            "post": serialize_post(latest),
            "thread_posts": serialized,
        })
        if is_multi_post_chain:
            def existing_ready_after() -> datetime:
                ready_after = existing.get("ready_after")
                if not isinstance(ready_after, str):
                    return now
                try:
                    parsed = datetime.fromisoformat(ready_after)
                except ValueError:
                    return now
                return parsed if (parsed.tzinfo is None) == (now.tzinfo is None) else now

            existing["ready_after"] = min(existing_ready_after(), now).isoformat()
        return False
    event = {
        "profile_id": profile.id,
        "post_id": latest.post_id,
        "thread_root_id": root_id,
        "thread_posts": serialized,
        "ready_after": immediate if is_multi_post_chain else deadline,
        "text_index": 0,
        "media_index": 0,
        "media_skipped_urls": [],
        "media_errors": [],
        "delivery_at": None,
        "post": serialize_post(latest),
        "board_phase": BOARD_PENDING,
        "board_attempts": 0,
        "board_next_attempt_at": None,
        "board_last_error": None,
    }
    if profile.uses_llm:
        event.update({"title": None, "summary": None, "route": None, "agent_phase": "pending", "agent_lease_until": None})
    state["outbox"].append(event)
    return True


def observe_posts(state: dict, profile: Profile, posts: list[SourcePost], forwardable: callable, is_self_thread: callable | None = None, now: datetime | None = None) -> tuple[int, str | None]:
    is_self_thread = is_self_thread or (lambda post: False)
    defer = now is not None
    if now is None:
        now = datetime.now(posts[0].published_at.tzinfo) if posts else datetime.now()
    record = state["profiles"].get(profile.id)
    ordered = sorted(posts, key=lambda post: int(post.post_id))
    if record is None:
        state["profiles"][profile.id] = {"cursor": ordered[-1].post_id if ordered else None}
        return 0, None
    if record.get("cursor") is None:
        record["cursor"] = ordered[-1].post_id if ordered else None
        return 0, None
    cursor = int(record.get("cursor") or 0)
    fresh = [post for post in ordered if int(post.post_id) > cursor]
    if any(post.kind.value == "ambiguous" for post in fresh):
        return 0, "ambiguous relation metadata"
    by_id = {post.post_id: post for post in posts}
    created = 0
    candidates: dict[str, tuple[SourcePost, ...]] = {}
    for post in fresh:
        if not forwardable(post) and not is_self_thread(post):
            continue
        thread = _within_thread_age(profile, _self_chain(profile, post, by_id, is_self_thread))
        # A timeline can expose a root and its later continuation together.
        # Keep the latest complete chain for that root, never the first item.
        candidates[thread[0].post_id] = thread
    for thread in candidates.values():
        settle_minutes = profile.thread_handling.settle_minutes if defer and profile.thread_handling.mode == "self_chain" else 0
        created += int(_event_for_thread(state, profile, thread, now, settle_minutes))
    if fresh: record["cursor"] = fresh[-1].post_id
    return created, None


def is_ready(event: dict, now: datetime) -> bool:
    ready_after = event.get("ready_after")
    if ready_after is None:
        return True
    if not isinstance(ready_after, str):
        return False
    try:
        return datetime.fromisoformat(ready_after) <= now
    except ValueError:
        return False


def expire_agent_leases(value: dict, now: datetime) -> None:
    for event in value["outbox"]:
        if event.get("agent_phase") != "awaiting_agent":
            continue
        lease = event.get("agent_lease_until")
        if not isinstance(lease, str):
            event["agent_phase"] = "pending"
            event["agent_lease_until"] = None
            continue
        try:
            expired = datetime.fromisoformat(lease) <= now
        except ValueError:
            expired = True
        if expired:
            event["agent_phase"] = "pending"
            event["agent_lease_until"] = None


def claim_oldest_agent(value: dict, profiles: dict[str, Profile], now: datetime) -> dict | None:
    expire_agent_leases(value, now)
    for event in value["outbox"]:
        profile = profiles.get(event.get("profile_id"))
        if profile and profile.uses_llm and event.get("agent_phase") == "pending" and is_ready(event, now):
            event["agent_phase"] = "awaiting_agent"
            event["agent_lease_until"] = (now + timedelta(minutes=15)).isoformat()
            return event
    return None


def submit_analysis(value: dict, event_key: str, analysis: dict[str, str]) -> dict:
    event = awaiting_analysis_event(value, event_key)
    event.update(analysis)
    event["agent_phase"] = "ready"
    event["agent_lease_until"] = None
    return event


def awaiting_analysis_event(value: dict, event_key: str) -> dict:
    profile_id, separator, post_id = event_key.partition(":")
    if not separator or not profile_id or not post_id:
        raise ValueError("event_key is invalid")
    for event in value["outbox"]:
        if event.get("profile_id") == profile_id and event.get("post_id") == post_id:
            if event.get("agent_phase") != "awaiting_agent":
                raise ValueError("analysis event is not awaiting the agent")
            return event
    raise ValueError("analysis event is not in durable state")


def discard_analysis(value: dict, event_key: str) -> None:
    event = awaiting_analysis_event(value, event_key)
    value["outbox"].remove(event)
    value["filtered_since_last_heartbeat"] += 1


def take_filtered_since_last_heartbeat(value: dict) -> int:
    filtered = value["filtered_since_last_heartbeat"]
    value["filtered_since_last_heartbeat"] = 0
    return filtered
