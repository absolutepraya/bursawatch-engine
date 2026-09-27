"""Explicit, bounded recovery of source posts skipped by an X feed gap."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import requests

import direct_x
import state
from models import PostKind, Profile, SourcePost
from rsshub import SourceFetchError


STATUS_PATH = re.compile(r"/([A-Za-z0-9_]{1,15})/status/(\d+)")
MAX_AGE = timedelta(hours=24)
FXTWEET_USER_AGENT = "Bursawatch-X-Account-Watch/1.0"


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
        try:
            return direct_x._payload(session, profile, post_id)
        except SourceFetchError as primary_error:
            try:
                return _fxtwitter_payload(session, profile, post_id)
            except SourceFetchError as fallback_error:
                raise SourceFetchError(
                    f"public X status detail unavailable via VxTwitter ({primary_error}) "
                    f"and FixTweet ({fallback_error})"
                ) from fallback_error


def _media_urls(value: object) -> list[str]:
    if type(value) is not dict:
        return []
    items = value.get("all")
    if type(items) is not list:
        items = []
        for key in ("photos", "videos"):
            candidates = value.get(key)
            if type(candidates) is list:
                items.extend(candidates)
    urls: list[str] = []
    for item in items:
        if type(item) is dict:
            url = item.get("url")
            if type(url) is str and url.startswith("https://") and url not in urls:
                urls.append(url)
    return urls


def _x_status_url(value: object) -> str | None:
    if type(value) is not str:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        return None
    if not re.fullmatch(r"/[A-Za-z0-9_]{1,15}/status/\d+", parsed.path):
        return None
    return f"https://x.com{parsed.path}"


def _fxtwitter_payload(session: requests.Session, profile: Profile, post_id: str) -> dict[str, object]:
    url = f"https://api.fxtwitter.com/{profile.handle}/status/{post_id}"
    try:
        response = session.get(url, timeout=30, headers={"User-Agent": FXTWEET_USER_AGENT})
    except requests.Timeout as exc:
        raise SourceFetchError("FixTweet status request timed out") from exc
    except requests.RequestException as exc:
        raise SourceFetchError("FixTweet status request failed") from exc
    if response.status_code >= 400:
        raise SourceFetchError(f"FixTweet status HTTP {response.status_code}")
    try:
        value = response.json()
    except ValueError as exc:
        raise SourceFetchError("FixTweet status returned malformed JSON") from exc
    if type(value) is not dict or value.get("code") != 200 or type(value.get("tweet")) is not dict:
        raise SourceFetchError("FixTweet status returned an invalid object")

    tweet = value["tweet"]
    if str(tweet.get("id")) != post_id:
        raise SourceFetchError("FixTweet status returned a mismatched post id")
    author = tweet.get("author")
    author_handle = author.get("screen_name") if type(author) is dict else None
    quote = tweet.get("quote")
    normalized_quote = None
    quote_url = None
    if type(quote) is dict:
        normalized_quote = {
            "text": quote.get("text"),
            "mediaURLs": _media_urls(quote.get("media")),
        }
        quote_url = _x_status_url(quote.get("url"))

    return {
        "tweetID": str(tweet["id"]),
        "date_epoch": tweet.get("created_timestamp"),
        "text": tweet.get("text"),
        "user_screen_name": author_handle,
        "replyingTo": tweet.get("replying_to"),
        "replyingToID": tweet.get("replying_to_status"),
        "mediaURLs": _media_urls(tweet.get("media")),
        "qrtURL": quote_url,
        "qrt": normalized_quote,
    }


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
