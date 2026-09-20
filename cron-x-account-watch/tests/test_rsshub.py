from datetime import datetime

import pytest
import requests

import rsshub
from models import PostKind


def item(url="https://x.com/Kutekians/status/102", links=None, html="Market <strong>note</strong><img src='https://img.example/1.jpg'>"):
    return {"url": url, "date_published": "2026-07-28T01:00:00Z", "content_html": html, "_extra": {"links": links or []}}


def test_quote_item_keeps_quoted_url_and_is_forwardable(profile_payload, config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = rsshub.parse_feed({"items": [item(links=[{"type": "quote", "url": "https://x.com/original/status/101", "content_html": "Original quote<img src='https://img.example/quoted.jpg'>"}])]}, profile)[0]
    assert post.kind is PostKind.QUOTE
    assert post.quoted_url == "https://x.com/original/status/101"
    assert rsshub.is_forwardable(profile, post) is True
    assert [media.url for media in post.media] == ["https://img.example/1.jpg"]
    assert [media.url for media in post.quoted_media] == ["https://img.example/quoted.jpg"]


@pytest.mark.parametrize(("relation", "expected"), [({"type": "reply", "url": "https://x.com/a/status/1"}, PostKind.REPLY), ({"type": "repost", "url": "https://x.com/a/status/1"}, PostKind.REPOST)])
def test_reply_and_repost_are_skipped_by_default(config_path, relation, expected):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = rsshub.parse_feed({"items": [item(links=[relation])]}, profile)[0]
    assert post.kind is expected
    assert rsshub.is_forwardable(profile, post) is False


def test_self_reply_keeps_its_parent_url_for_thread_collection(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = rsshub.parse_feed({"items": [item(links=[{"type": "reply", "url": "https://x.com/Kutekians/status/101"}])]}, profile)[0]
    assert post.kind is PostKind.REPLY
    assert post.related_url == "https://x.com/Kutekians/status/101"
    assert rsshub.is_self_thread_post(profile, post) is True


def test_conflicting_or_invalid_quote_relation_is_ambiguous(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    post = rsshub.parse_feed({"items": [item(links=[{"type": "quote", "content_html": "missing URL"}, {"type": "reply", "url": "https://x.com/a/status/1"}])]}, profile)[0]
    assert post.kind is PostKind.AMBIGUOUS


def test_article_only_post_is_ignored_but_authored_post_quoting_article_keeps_only_preview_media(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    article = rsshub.parse_feed({"items": [item(html="https://x.com/i/article/2082002180039651328")]}, profile)[0]
    authored = rsshub.parse_feed({"items": [item(html="My authored take<div class=\"rsshub-quote\">Different Author: https://x.com/i/article/2082002180039651328<img src='https://img.example/article.jpg'></div>", links=[{"type": "quote", "url": "https://x.com/rickyho_1989/status/101", "content_html": "Different Author: https://x.com/i/article/2082002180039651328"}])]}, profile)[0]
    assert article.kind is PostKind.ARTICLE
    assert rsshub.is_forwardable(profile, article) is False
    assert authored.kind is PostKind.NORMAL
    assert authored.content_html == "My authored take"
    assert authored.quoted_content_html is None
    assert authored.quoted_article_url == "https://x.com/i/article/2082002180039651328"
    assert authored.quoted_article_label == "Different Author"
    assert [media.url for media in authored.quoted_media] == ["https://img.example/article.jpg"]


class Response:
    def __init__(self, status, payload=None): self.status_code, self.payload = status, payload
    def json(self):
        if isinstance(self.payload, Exception): raise self.payload
        return self.payload


class Session:
    def __init__(self, response=None, error=None): self.response, self.error = response, error
    def get(self, url, timeout):
        assert timeout == 30
        if self.error: raise self.error
        return self.response


def test_fetch_sanitizes_auth_and_timeout(config_path):
    profile = __import__("config").load_watch_config(config_path).profiles[0]
    with pytest.raises(rsshub.SourceFetchError, match="HTTP 403: authentication rejected"):
        rsshub.fetch_profile_items(profile, Session(Response(403)))
    with pytest.raises(rsshub.SourceFetchError, match="timed out"):
        rsshub.fetch_profile_items(profile, Session(error=requests.Timeout("cookie=secret")))
