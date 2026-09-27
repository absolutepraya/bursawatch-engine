"""Explicit, bounded recovery of source posts skipped by an X feed gap."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from collections.abc import Callable, Iterable

import requests

import direct_x
import state
from models import PostKind, Profile, SourcePost


STATUS_PATH = re.compile(r"/([A-Za-z0-9_]{1,15})/status/(\d+)")
MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class RecoveryRow:
    profile: Profile
    post: SourcePost
    status: str


def parse_status_url(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    match = STATUS_PATH.fullmatch(parts.path)
    if parts.scheme != "https" or parts.netloc not in {"x.com", "www.x.com"} or not match or parts.fragment:
        raise ValueError("invalid X status URL")
    return match.group(1), match.group(2)


def fetch_public_detail(profile: Profile, post_id: str) -> dict[str, object]:
    with requests.Session() as session:
        session.trust_env = False
        session.proxies.clear()
        return direct_x._payload(session, profile, post_id)


def _known_status(value: dict, profile: Profile, post_id: str) -> str | None:
    if any(
        event.get("profile_id") == profile.id
        and post_id in {item.get("post_id") for item in event.get("thread_posts", [event.get("post", {})])}
        for event in value["outbox"]
    ):
        return "already_queued"
    if any(
        record.get("profile_id") == profile.id
        and post_id in record.get("source_post_ids", [record.get("post_id")])
        for record in value["deliveries"]
    ):
        return "already_delivered"
    cursor = (value["profiles"].get(profile.id) or {}).get("cursor")
    if cursor is None or int(post_id) > int(cursor):
        return "await_normal_poll"
    return None


def preview(
    value: dict,
    profiles: Iterable[Profile],
    urls: Iterable[str],
    now: datetime,
    fetch: Callable[[Profile, str], dict[str, object]] = fetch_public_detail,
) -> list[RecoveryRow]:
    by_handle = {profile.handle.casefold(): profile for profile in profiles if profile.enabled}
    seen: set[tuple[str, str]] = set()
    rows: list[RecoveryRow] = []
    for url in urls:
        handle, post_id = parse_status_url(url)
        key = (handle.casefold(), post_id)
        if key in seen:
            raise ValueError("duplicate X status URL")
        seen.add(key)
        profile = by_handle.get(handle.casefold())
        if profile is None:
            raise ValueError("X status account is not enabled in the current configuration")
        payload = fetch(profile, post_id)
        if str(payload.get("tweetID")) != post_id:
            raise ValueError("X status returned a mismatched post id")
        post = direct_x._source_post(profile, payload)
        author = payload.get("user_screen_name")
        if type(author) is not str or author.casefold() != profile.handle.casefold():
            status = "author_mismatch"
        elif post.kind is PostKind.REPLY:
            status = "reply_requires_review"
        elif post.published_at > now or now - post.published_at > MAX_AGE:
            status = "expired"
        elif now - post.published_at < timedelta(minutes=profile.thread_handling.settle_minutes):
            status = "settling"
        else:
            status = _known_status(value, profile, post_id) or "eligible"
        rows.append(RecoveryRow(profile, post, status))
    return rows


def apply(value: dict, rows: Iterable[RecoveryRow], now: datetime) -> int:
    created = 0
    for row in rows:
        if row.status != "eligible" or _known_status(value, row.profile, row.post.post_id):
            continue
        if state._event_for_thread(value, row.profile, (row.post,), now, 0):
            value["outbox"][-1]["recovery"] = {
                "kind": "source_gap", "applied_at": now.isoformat(),
                "source_url": row.post.url,
            }
            created += 1
    return created
