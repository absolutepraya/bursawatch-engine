from __future__ import annotations

import html
import logging
import os
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests

from models import PostKind, Profile, SourceMedia, SourcePost
from rsshub import SourceFetchError


TWEET_ID_RE = re.compile(r'data-tweet-id="(\d+)"')
STATUS_URL_RE = re.compile(r'(?:https://(?:www\.)?x\.com/|/)([A-Za-z0-9_]{1,15})/status/(\d+)')
USER_AGENT = "Mozilla/5.0 (X-post-watch; +https://x.com/)"
RATE_LIMIT_COOLDOWN_SECONDS = 3 * 60 * 60
PRIMARY_PROXY_ENV = "X_POST_WATCH_PROXY_PRIMARY"
FALLBACK_PROXY_ENV = "X_POST_WATCH_PROXY_FALLBACK"
RECOVERABLE_PROXY_STATUS_CODES = {403, 407, 429} | set(range(500, 600))
LOGGER = logging.getLogger(__name__)


def _valid_proxy_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.port is not None
    except ValueError:
        return False


class _ProxySession:
    def __init__(self, proxy_urls: tuple[str, str]) -> None:
        self._sessions = []
        for proxy_url in proxy_urls:
            session = requests.Session()
            session.trust_env = False
            session.proxies.update({"http": proxy_url, "https": proxy_url})
            self._sessions.append(session)
        self._active_index = 0
        self.attempt_statuses: list[int | None] = []
        self.attempted_routes: list[int] = []
        self.used_fallback = False

    def _switch_to_fallback(self) -> None:
        if self._active_index == 0:
            self._active_index = 1
            self.used_fallback = True
            LOGGER.info("direct X fallback proxy used")

    def get(self, url: str, timeout: int, headers: dict[str, str] | None = None) -> requests.Response:
        self.attempt_statuses = []
        self.attempted_routes = []
        for index in range(self._active_index, len(self._sessions)):
            self.attempted_routes.append(index)
            try:
                response = self._sessions[index].get(url, timeout=timeout, headers=headers)
            except requests.RequestException:
                self.attempt_statuses.append(None)
                if index == 0:
                    self._switch_to_fallback()
                    continue
                raise

            self.attempt_statuses.append(response.status_code)
            if response.status_code in RECOVERABLE_PROXY_STATUS_CODES and index == 0:
                self._switch_to_fallback()
                continue
            return response

        raise requests.RequestException("direct X proxy request failed")


def _configured_session() -> _ProxySession:
    primary = os.environ.get(PRIMARY_PROXY_ENV, "").strip()
    fallback = os.environ.get(FALLBACK_PROXY_ENV, "").strip()
    if not primary or not fallback or not _valid_proxy_url(primary) or not _valid_proxy_url(fallback):
        raise SourceFetchError("direct X proxy configuration is missing or invalid")
    return _ProxySession((primary, fallback))


def _tweet_ids(document: str, handle: str | None = None) -> list[str]:
    ids: list[str] = []
    if handle is not None:
        ids.extend(
            post_id
            for author, post_id in STATUS_URL_RE.findall(document)
            if author.casefold() == handle.casefold()
        )
    ids.extend(TWEET_ID_RE.findall(document))
    return list(dict.fromkeys(ids))


def _get(session: requests.Session, url: str) -> requests.Response:
    try:
        response = session.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    except requests.Timeout as exc:
        raise SourceFetchError("direct X feed timed out") from exc
    except requests.RequestException as exc:
        raise SourceFetchError("direct X feed request failed") from exc
    if response.status_code >= 400:
        if response.status_code == 429:
            statuses = getattr(session, "attempt_statuses", ())
            attempted_routes = getattr(session, "attempted_routes", ())
            if not attempted_routes or len(attempted_routes) >= 2 and all(status == 429 for status in statuses):
                raise SourceFetchError(
                    "direct X feed HTTP 429 (three-hour cooldown)",
                    retry_after_seconds=RATE_LIMIT_COOLDOWN_SECONDS,
                )
            raise SourceFetchError("direct X feed HTTP 429")
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
    quoted_payload = payload.get("qrt")
    quoted_text = quoted_payload
    quoted_media = _media(quoted_payload) if type(quoted_payload) is dict else ()
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
        quoted_media=quoted_media,
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
    if str(value.get("tweetID")) != post_id:
        raise SourceFetchError("direct X status returned a mismatched post id")
    return value


def _same_author(payload: dict[str, object], profile: Profile) -> bool:
    author = payload.get("user_screen_name")
    if type(author) is not str or not author:
        raise SourceFetchError("direct X status has no author identity")
    return author.casefold() == profile.handle.casefold()


def fetch_profile_items(profile: Profile, session: requests.Session | None = None, after_id: str | None = None, skip_ids: set[str] | None = None) -> list[SourcePost]:
    client = session or _configured_session()
    detail_client = session or requests.Session()
    if session is None:
        detail_client.trust_env = False
        detail_client.proxies.clear()
    try:
        profile_response = _get(client, profile.profile_url)
        visible_ids = _tweet_ids(profile_response.text, profile.handle)[: profile.max_items_per_poll]
        if not visible_ids:
            raise SourceFetchError("direct X profile returned no status links")
        fresh_ids = [
            post_id for post_id in visible_ids
            if (after_id is None or int(post_id) > int(after_id)) and post_id not in (skip_ids or set())
        ]
        if not fresh_ids:
            return []

        payloads = {post_id: _payload(detail_client, profile, post_id) for post_id in fresh_ids}

        if after_id is None:
            return [
                _source_post(profile, payloads[post_id])
                for post_id in fresh_ids if _same_author(payloads[post_id], profile)
            ]

        conversations: list[str] = []
        for post_id in fresh_ids:
            payload = payloads[post_id]
            if not _same_author(payload, profile):
                continue
            conversation_id = payload.get("conversationID")
            if type(conversation_id) not in {str, int} or not str(conversation_id).isdigit():
                conversation_id = post_id
            conversation_id = str(conversation_id)
            if conversation_id not in conversations:
                conversations.append(conversation_id)

        result: dict[str, SourcePost] = {}
        for conversation_id in conversations:
            try:
                response = _get(client, _post_url(profile.handle, conversation_id))
                thread_ids = _tweet_ids(response.text, profile.handle) or [conversation_id]
            except SourceFetchError as error:
                if error.retry_after_seconds is not None:
                    raise
                thread_ids = [conversation_id]
            thread_ids = list(dict.fromkeys(thread_ids + [
                post_id for post_id in fresh_ids
                if str(payloads[post_id].get("conversationID")) == conversation_id
            ]))
            seen = set(thread_ids)
            for fresh_id in tuple(thread_ids):
                current_id = fresh_id
                for _ in range(profile.thread_handling.max_posts):
                    current = payloads.get(current_id)
                    if current is None:
                        current = _payload(detail_client, profile, current_id)
                        payloads[current_id] = current
                    if not _same_author(current, profile):
                        break
                    parent_id = current.get("replyingToID")
                    parent_author = current.get("replyingTo")
                    if type(parent_id) not in {str, int} or not str(parent_id).isdigit():
                        break
                    if type(parent_author) is not str or parent_author.casefold() != profile.handle.casefold():
                        break
                    parent_id = str(parent_id)
                    if parent_id in seen:
                        break
                    seen.add(parent_id)
                    thread_ids.append(parent_id)
                    current_id = parent_id
            for post_id in thread_ids:
                if post_id not in payloads:
                    payloads[post_id] = _payload(detail_client, profile, post_id)
                payload = payloads[post_id]
                if not _same_author(payload, profile):
                    continue
                post_conversation = payload.get("conversationID")
                if (
                    type(post_conversation) in {str, int}
                    and str(post_conversation).isdigit()
                    and str(post_conversation) != conversation_id
                ):
                    continue
                post = _source_post(profile, payload)
                result[post.post_id] = post
        return sorted(result.values(), key=lambda post: int(post.post_id))
    finally:
        if session is None:
            detail_client.close()
