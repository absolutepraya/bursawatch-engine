from __future__ import annotations

import html
import re
from datetime import UTC, datetime

import requests

from models import PostKind, Profile, SourceMedia, SourcePost
from rsshub import SourceFetchError


TWEET_ID_RE = re.compile(r'data-tweet-id="(\d+)"')
USER_AGENT = "Mozilla/5.0 (X-post-watch; +https://x.com/)"


def _tweet_ids(document: str) -> list[str]:
    return list(dict.fromkeys(TWEET_ID_RE.findall(document)))


def _get(session: requests.Session, url: str) -> requests.Response:
    try:
        response = session.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    except requests.Timeout as exc:
        raise SourceFetchError("direct X feed timed out") from exc
    except requests.RequestException as exc:
        raise SourceFetchError("direct X feed request failed") from exc
    if response.status_code >= 400:
        raise SourceFetchError(f"direct X feed HTTP {response.status_code}")
    return response


def _post_url(handle: str, post_id: str) -> str:
    return f"https://x.com/{handle}/status/{post_id}"


def _content_html(text: object) -> str:
    if type(text) is not str:
        raise SourceFetchError("direct X feed contains invalid post text")
    return html.escape(text, quote=False).replace("\n", "<br>")


def _media(payload: dict[str, object]) -> tuple[SourceMedia, ...]:
    urls = payload.get("mediaURLs", [])
    if type(urls) is not list:
        return ()
    seen: set[str] = set()
    result: list[SourceMedia] = []
    for url in urls:
        if type(url) is str and url.startswith("https://") and url not in seen:
            seen.add(url)
            result.append(SourceMedia(url=url, index=len(result)))
    return tuple(result)


def _published_at(payload: dict[str, object]) -> datetime:
    value = payload.get("date_epoch")
    if type(value) in {int, float}:
        return datetime.fromtimestamp(value, tz=UTC)
    raise SourceFetchError("direct X feed contains invalid post date")


def _source_post(profile: Profile, payload: dict[str, object]) -> SourcePost:
    post_id = payload.get("tweetID")
    if type(post_id) not in {str, int} or not str(post_id).isdigit():
        raise SourceFetchError("direct X feed contains an invalid post id")
    post_id = str(post_id)
    parent_id = payload.get("replyingToID")
    parent_handle = payload.get("replyingTo") or profile.handle
    if type(parent_id) not in {str, int} or not str(parent_id).isdigit():
        parent_id = None
    if type(parent_handle) is not str or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", parent_handle):
        parent_handle = profile.handle
    quoted_url = payload.get("qrtURL")
    if type(quoted_url) is not str or not quoted_url.startswith("https://x.com/"):
        quoted_url = None
    quoted_text = payload.get("qrt")
    if type(quoted_text) is dict:
        quoted_text = quoted_text.get("text")
    if type(quoted_text) is not str:
        quoted_text = None
    kind = PostKind.QUOTE if quoted_url else PostKind.REPLY if parent_id else PostKind.NORMAL
    return SourcePost(
        profile_id=profile.id,
        post_id=post_id,
        url=_post_url(profile.handle, post_id),
        published_at=_published_at(payload),
        content_html=_content_html(payload.get("text", "")),
        kind=kind,
        quoted_url=quoted_url,
        quoted_content_html=_content_html(quoted_text) if quoted_text else None,
        media=_media(payload),
        quoted_media=(),
        related_url=_post_url(parent_handle, str(parent_id)) if parent_id else None,
    )


def _payload(session: requests.Session, profile: Profile, post_id: str) -> dict[str, object]:
    response = _get(session, f"https://api.vxtwitter.com/{profile.handle}/status/{post_id}")
    try:
        value = response.json()
    except ValueError as exc:
        raise SourceFetchError("direct X status returned malformed JSON") from exc
    if type(value) is not dict:
        raise SourceFetchError("direct X status returned an invalid object")
    return value


def fetch_profile_items(profile: Profile, session: requests.Session | None = None, after_id: str | None = None) -> list[SourcePost]:
    client = session or requests.Session()
    profile_response = _get(client, profile.profile_url)
    visible_ids = _tweet_ids(profile_response.text)[: profile.max_items_per_poll]
    payloads = {post_id: _payload(client, profile, post_id) for post_id in visible_ids}
    fresh_ids = [post_id for post_id in visible_ids if after_id is None or int(post_id) > int(after_id)]
    if not fresh_ids:
        return sorted((_source_post(profile, payload) for payload in payloads.values()), key=lambda post: int(post.post_id))

    if after_id is None:
        return [_source_post(profile, payloads[post_id]) for post_id in fresh_ids]

    conversations: list[str] = []
    for post_id in fresh_ids:
        payload = payloads[post_id]
        conversation_id = payload.get("conversationID")
        if type(conversation_id) not in {str, int} or not str(conversation_id).isdigit():
            conversation_id = post_id
        conversation_id = str(conversation_id)
        if conversation_id not in conversations:
            conversations.append(conversation_id)

    result: dict[str, SourcePost] = {}
    for conversation_id in conversations:
        response = _get(client, _post_url(profile.handle, conversation_id))
        thread_ids = _tweet_ids(response.text) or [conversation_id]
        for post_id in thread_ids:
            payload = payloads.setdefault(post_id, _payload(client, profile, post_id))
            author = payload.get("user_screen_name")
            if type(author) is not str:
                author = profile.handle
            if author.lower() != profile.handle.lower():
                continue
            post = _source_post(profile, payload)
            result[post.post_id] = post
    return sorted(result.values(), key=lambda post: int(post.post_id))
