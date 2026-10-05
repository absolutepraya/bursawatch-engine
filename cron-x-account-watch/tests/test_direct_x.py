import requests
import pytest

import direct_x
from models import PostKind


class Response:
    def __init__(self, status_code, *, text="", payload=None, headers=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class ProxySession:
    def __init__(self, *outcomes):
        self.proxies = {}
        self.outcomes = list(outcomes)
        self.urls = []

    def get(self, url, timeout, headers=None):
        assert timeout == 30
        self.urls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Session:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout, headers=None):
        assert timeout == 30
        self.urls.append(url)
        if url == "https://x.com/Kutekians":
            return Response(200, text='<article data-tweet-id="101"></article>')
        if url == "https://x.com/Kutekians/status/101":
            return Response(200, text='<article data-tweet-id="101"></article><article data-tweet-id="102"></article>')
        if url == "https://api.vxtwitter.com/Kutekians/status/101":
            return Response(200, payload={
                "tweetID": "101",
                "tweetURL": "https://twitter.com/Kutekians/status/101",
                "date_epoch": 1787137418,
                "text": "Root context",
                "mediaURLs": ["https://pbs.twimg.com/media/root.jpg"],
                "replyingTo": None,
                "replyingToID": None,
                "user_screen_name": "Kutekians",
            })
        if url == "https://api.vxtwitter.com/Kutekians/status/102":
            return Response(200, payload={
                "tweetID": "102",
                "tweetURL": "https://twitter.com/Kutekians/status/102",
                "date_epoch": 1787137419,
                "text": "Continuation",
                "mediaURLs": [],
                "replyingTo": "Kutekians",
                "replyingToID": "101",
                "user_screen_name": "Kutekians",
            })
        raise AssertionError(f"unexpected URL: {url}")


class ModernProfileSession(Session):
    def get(self, url, timeout, headers=None):
        if url == "https://x.com/Kutekians":
            return Response(
                200,
                text=(
                    '<a href="/i/status/999">quoted post</a>'
                    '<a href="/Kutekians/status/101">own post</a>'
                    '<a href="/other/status/202">other post</a>'
                ),
            )
        return super().get(url, timeout, headers=headers)


def test_fetches_and_expands_a_same_author_thread(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    posts = direct_x.fetch_profile_items(profile, Session(), after_id=100)

    assert [post.post_id for post in posts] == ["101", "102"]
    assert [post.kind for post in posts] == [PostKind.NORMAL, PostKind.REPLY]
    assert posts[1].related_url == "https://x.com/Kutekians/status/101"
    assert posts[0].content_html == "Root context"
    assert [media.url for media in posts[0].media] == ["https://pbs.twimg.com/media/root.jpg"]


def test_direct_x_uses_public_detail_and_keeps_normal_post_when_status_page_is_blocked(config_path, monkeypatch):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class ProfileProxy:
        def get(self, url, timeout, headers=None):
            if url == profile.profile_url:
                return Response(200, text='<a href="/Kutekians/status/101">post</a>')
            return Response(403)

    class PublicDetail:
        trust_env = True
        proxies = {"https": "http://unwanted-proxy"}
        def __init__(self):
            self.urls = []
        def get(self, url, timeout, headers=None):
            self.urls.append(url)
            return Response(200, payload={
                "tweetID": "101", "conversationID": "101", "date_epoch": 1787137418,
                "text": "A market fact", "mediaURLs": [], "user_screen_name": "Kutekians",
            })
        def close(self):
            pass

    detail = PublicDetail()
    monkeypatch.setattr(direct_x, "_configured_session", ProfileProxy)
    monkeypatch.setattr(direct_x.requests, "Session", lambda: detail)

    posts = direct_x.fetch_profile_items(profile, after_id="100")

    assert [post.post_id for post in posts] == ["101"]
    assert posts[0].content_html == "A market fact"
    assert detail.trust_env is False
    assert detail.proxies == {}
    assert detail.urls == ["https://api.vxtwitter.com/Kutekians/status/101"]


def test_direct_x_recovers_same_author_parent_when_status_page_is_blocked(config_path, monkeypatch):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class ProfileProxy:
        def get(self, url, timeout, headers=None):
            if url == profile.profile_url:
                return Response(200, text='<a href="/Kutekians/status/102">reply</a>')
            return Response(403)

    class PublicDetail:
        def __init__(self):
            self.trust_env = True
            self.proxies = {"https": "http://unwanted-proxy"}
        def get(self, url, timeout, headers=None):
            post_id = url.rsplit("/", 1)[-1]
            return Response(200, payload={
                "tweetID": post_id, "conversationID": "101", "date_epoch": 1787137418 + int(post_id),
                "text": "Root context" if post_id == "101" else "Reply context",
                "replyingToID": "101" if post_id == "102" else None,
                "replyingTo": "Kutekians" if post_id == "102" else None,
                "mediaURLs": [], "user_screen_name": "Kutekians",
            })
        def close(self):
            pass

    monkeypatch.setattr(direct_x, "_configured_session", ProfileProxy)
    monkeypatch.setattr(direct_x.requests, "Session", PublicDetail)

    posts = direct_x.fetch_profile_items(profile, after_id="101")

    assert [post.post_id for post in posts] == ["101", "102"]
    assert posts[1].related_url == "https://x.com/Kutekians/status/101"


def test_direct_x_recovers_intermediate_self_replies_when_status_page_is_blocked(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class BlockedThreadSession(Session):
        def get(self, url, timeout, headers=None):
            if url == profile.profile_url:
                return Response(200, text='<a href="/Kutekians/status/103">reply</a>')
            if url.startswith("https://x.com/Kutekians/status/"):
                return Response(403)
            post_id = url.rsplit("/", 1)[-1]
            return Response(200, payload={
                "tweetID": post_id, "conversationID": "101", "date_epoch": 1787137418 + int(post_id),
                "text": f"Part {post_id}", "replyingToID": str(int(post_id) - 1) if post_id != "101" else None,
                "replyingTo": "Kutekians" if post_id != "101" else None,
                "mediaURLs": [], "user_screen_name": "Kutekians",
            })

    posts = direct_x.fetch_profile_items(profile, BlockedThreadSession(), after_id="102")

    assert [post.post_id for post in posts] == ["101", "102", "103"]


def test_direct_x_keeps_fresh_reply_when_thread_page_is_partial(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class PartialThreadSession(Session):
        def get(self, url, timeout, headers=None):
            if url == profile.profile_url:
                return Response(200, text='<a href="/Kutekians/status/103">reply</a>')
            if url.startswith("https://x.com/Kutekians/status/"):
                return Response(200, text='<a href="/Kutekians/status/101">root only</a>')
            post_id = url.rsplit("/", 1)[-1]
            return Response(200, payload={
                "tweetID": post_id, "conversationID": "101", "date_epoch": 1787137418 + int(post_id),
                "text": f"Part {post_id}", "replyingToID": str(int(post_id) - 1) if post_id != "101" else None,
                "replyingTo": "Kutekians" if post_id != "101" else None,
                "mediaURLs": [], "user_screen_name": "Kutekians",
            })

    posts = direct_x.fetch_profile_items(profile, PartialThreadSession(), after_id="102")

    assert [post.post_id for post in posts] == ["101", "102", "103"]


def test_direct_x_does_not_import_unrelated_same_author_posts_from_status_page(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class MixedThreadSession(Session):
        def get(self, url, timeout, headers=None):
            if url == profile.profile_url:
                return Response(200, text='<a href="/Kutekians/status/101">new post</a>')
            if url == "https://x.com/Kutekians/status/101":
                return Response(200, text=(
                    '<a href="/Kutekians/status/101">main post</a>'
                    '<a href="/Kutekians/status/202">sidebar post</a>'
                ))
            post_id = url.rsplit("/", 1)[-1]
            return Response(200, payload={
                "tweetID": post_id, "conversationID": post_id,
                "date_epoch": 1787137418, "text": "Separate post",
                "user_screen_name": "Kutekians", "mediaURLs": [],
            })

    posts = direct_x.fetch_profile_items(profile, MixedThreadSession(), after_id="100")

    assert [post.post_id for post in posts] == ["101"]


def test_direct_x_bootstrap_excludes_other_authors_even_in_profile_markup(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class MixedProfileSession(Session):
        def get(self, url, timeout, headers=None):
            if url == profile.profile_url:
                return Response(200, text=(
                    '<article data-tweet-id="202"></article>'
                    '<a href="/other/status/202">quote</a>'
                    '<a href="/Kutekians/status/101">own post</a>'
                ))
            if url.endswith("/202"):
                return Response(200, payload={
                    "tweetID": "202", "date_epoch": 1787137418, "text": "Not ours",
                    "user_screen_name": "other", "mediaURLs": [],
                })
            return super().get(url, timeout, headers=headers)

    posts = direct_x.fetch_profile_items(profile, MixedProfileSession())

    assert [post.post_id for post in posts] == ["101"]


def test_direct_x_head_uses_newest_own_status_id_without_detail_requests(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class ProfileOnlySession:
        def __init__(self):
            self.urls = []

        def get(self, url, timeout, headers=None):
            assert timeout == 30
            self.urls.append(url)
            return Response(200, text=(
                '<a href="/Kutekians/status/101">old own post</a>'
                '<article data-tweet-id="999999"></article>'
                '<a href="/other/status/999999">other post</a>'
                '<a href="https://x.com/kutekians/status/103">new own post</a>'
            ))

    session = ProfileOnlySession()
    assert direct_x.fetch_profile_head_id(profile, session) == "103"
    assert session.urls == [profile.profile_url]


def test_direct_x_head_fails_closed_without_own_status_links(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class EmptyProfileSession:
        def get(self, url, timeout, headers=None):
            return Response(200, text='<a href="/other/status/999">not ours</a>')

    with pytest.raises(direct_x.SourceFetchError, match="no own status links"):
        direct_x.fetch_profile_head_id(profile, EmptyProfileSession())


def test_direct_x_keeps_quoted_tweet_media_for_vision_context(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = direct_x._source_post(profile, {
        "tweetID": "103",
        "date_epoch": 1787137420,
        "text": "My view",
        "mediaURLs": ["https://pbs.twimg.com/media/authored.jpg"],
        "qrtURL": "https://x.com/other/status/99",
        "qrt": {
            "text": "Quoted context",
            "mediaURLs": ["https://pbs.twimg.com/media/quoted.jpg"],
        },
    })

    assert post.kind is PostKind.QUOTE
    assert [media.url for media in post.media] == ["https://pbs.twimg.com/media/authored.jpg"]
    assert [media.url for media in post.quoted_media] == ["https://pbs.twimg.com/media/quoted.jpg"]


def test_discovers_posts_from_current_profile_status_links(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    posts = direct_x.fetch_profile_items(profile, ModernProfileSession(), after_id=100)

    assert [post.post_id for post in posts] == ["101", "102"]


def test_does_not_fetch_status_details_when_no_new_thread_exists(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    session = Session()

    posts = direct_x.fetch_profile_items(profile, session, after_id=101)

    assert posts == []
    assert session.urls == ["https://x.com/Kutekians"]


def test_skips_profile_ids_already_supplied_by_rsshub(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    session = Session()

    posts = direct_x.fetch_profile_items(profile, session, after_id="100", skip_ids={"101"})

    assert posts == []
    assert session.urls == ["https://x.com/Kutekians"]


def test_missing_status_links_are_a_source_error(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class EmptyProfileSession(Session):
        def get(self, url, timeout, headers=None):
            if url == "https://x.com/Kutekians":
                return Response(200, text="<html>signed-out shell</html>")
            return super().get(url, timeout, headers=headers)

    try:
        direct_x.fetch_profile_items(profile, EmptyProfileSession(), after_id="101")
    except direct_x.SourceFetchError as exc:
        assert str(exc) == "direct X profile returned no status links"
    else:
        raise AssertionError("expected a source fetch error")


def test_429_requests_three_hour_cooldown(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]

    class RateLimitedSession(Session):
        def get(self, url, timeout, headers=None):
            if url == "https://x.com/Kutekians":
                return Response(429)
            return super().get(url, timeout, headers=headers)

    try:
        direct_x.fetch_profile_items(profile, RateLimitedSession(), after_id=None)
    except direct_x.SourceFetchError as exc:
        assert str(exc) == "direct X feed HTTP 429 (three-hour cooldown)"
        assert exc.retry_after_seconds == 3 * 60 * 60
    else:
        raise AssertionError("expected a source fetch error")


def test_proxy_session_retries_a_transport_failure_through_fallback(monkeypatch):
    primary = ProxySession(requests.ConnectionError("primary unavailable"))
    fallback = ProxySession(Response(200, text="ok"))
    sessions = iter([primary, fallback])
    monkeypatch.setattr(direct_x.requests, "Session", lambda: next(sessions))
    monkeypatch.setenv(direct_x.PRIMARY_PROXY_ENV, "http://primary.example:3010")
    monkeypatch.setenv(direct_x.FALLBACK_PROXY_ENV, "http://fallback.example:443")

    client = direct_x._configured_session()
    response = direct_x._get(client, "https://x.com/wavetiga")

    assert response.status_code == 200
    assert primary.urls == ["https://x.com/wavetiga"]
    assert fallback.urls == ["https://x.com/wavetiga"]
    assert primary.proxies == {
        "http": "http://primary.example:3010",
        "https": "http://primary.example:3010",
    }
    assert fallback.proxies == {
        "http": "http://fallback.example:443",
        "https": "http://fallback.example:443",
    }
    assert next(sessions, None) is None


def test_proxy_session_stays_on_fallback_for_the_rest_of_the_poll(monkeypatch):
    primary = ProxySession(Response(503))
    fallback = ProxySession(Response(200, text="first"), Response(200, text="second"))
    sessions = iter([primary, fallback])
    monkeypatch.setattr(direct_x.requests, "Session", lambda: next(sessions))
    monkeypatch.setenv(direct_x.PRIMARY_PROXY_ENV, "http://primary.example:3010")
    monkeypatch.setenv(direct_x.FALLBACK_PROXY_ENV, "http://fallback.example:443")

    client = direct_x._configured_session()
    assert direct_x._get(client, "https://x.com/wavetiga").text == "first"
    assert direct_x._get(client, "https://api.vxtwitter.com/wavetiga/status/1").text == "second"

    assert primary.urls == ["https://x.com/wavetiga"]
    assert fallback.urls == [
        "https://x.com/wavetiga",
        "https://api.vxtwitter.com/wavetiga/status/1",
    ]


def test_proxy_session_only_cools_down_when_both_routes_are_rate_limited(monkeypatch):
    primary = ProxySession(Response(429))
    fallback = ProxySession(Response(429))
    sessions = iter([primary, fallback])
    monkeypatch.setattr(direct_x.requests, "Session", lambda: next(sessions))
    monkeypatch.setenv(direct_x.PRIMARY_PROXY_ENV, "http://primary.example:3010")
    monkeypatch.setenv(direct_x.FALLBACK_PROXY_ENV, "http://fallback.example:443")

    client = direct_x._configured_session()
    with pytest.raises(direct_x.SourceFetchError) as error:
        direct_x._get(client, "https://x.com/wavetiga")

    assert str(error.value) == "direct X feed HTTP 429 (three-hour cooldown)"
    assert error.value.retry_after_seconds == 3 * 60 * 60


def test_rate_limit_on_already_active_fallback_does_not_start_global_cooldown(monkeypatch):
    primary = ProxySession(Response(503))
    fallback = ProxySession(Response(200, text="first"), Response(429))
    sessions = iter([primary, fallback])
    monkeypatch.setattr(direct_x.requests, "Session", lambda: next(sessions))
    monkeypatch.setenv(direct_x.PRIMARY_PROXY_ENV, "http://primary.example:3010")
    monkeypatch.setenv(direct_x.FALLBACK_PROXY_ENV, "http://fallback.example:443")

    client = direct_x._configured_session()
    assert direct_x._get(client, "https://x.com/wavetiga").text == "first"

    with pytest.raises(direct_x.SourceFetchError) as error:
        direct_x._get(client, "https://api.vxtwitter.com/wavetiga/status/1")

    assert str(error.value) == "direct X feed HTTP 429"
    assert error.value.retry_after_seconds is None


def test_missing_proxy_configuration_fails_closed(config_path, monkeypatch):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    monkeypatch.delenv(direct_x.PRIMARY_PROXY_ENV, raising=False)
    monkeypatch.delenv(direct_x.FALLBACK_PROXY_ENV, raising=False)

    with pytest.raises(direct_x.SourceFetchError, match="proxy configuration"):
        direct_x.fetch_profile_items(profile)
