from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from models import PostKind, Profile, SourceMedia, SourcePost


def new_state() -> dict:
    return {"version": 1, "profiles": {}, "outbox": [], "filtered_since_last_heartbeat": 0}


def load_state(path: Path) -> dict:
    if not path.exists(): return new_state()
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict or value.get("version") != 1 or type(value.get("profiles")) is not dict or type(value.get("outbox")) is not list:
        raise ValueError("x-post-watch state is invalid")
    if "filtered_since_last_heartbeat" not in value:
        value["filtered_since_last_heartbeat"] = 0
    if type(value["filtered_since_last_heartbeat"]) is not int or value["filtered_since_last_heartbeat"] < 0:
        raise ValueError("x-post-watch state is invalid")
    # Summary-only events predate title generation. Requeue them as one fresh
    # agent task so the title and summary are produced together before any
    # delivery. This is a schema migration, never a cursor reset or replay.
    for event in value["outbox"]:
        if "summary_phase" in event:
            event.pop("summary_phase", None)
            event.pop("summary_lease_until", None)
            event["title"] = None
            event["summary"] = None
            event["route"] = None
            event["agent_phase"] = "pending"
            event["agent_lease_until"] = None
    return value


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
        "post": serialize_post(latest),
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
