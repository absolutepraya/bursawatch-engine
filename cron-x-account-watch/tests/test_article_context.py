from datetime import UTC, datetime

import article_context
import pytest
from models import PostKind, SourcePost


class Response:
    def __init__(self, status_code: int, content: bytes = b"", headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._content = content
        self.headers = headers or {"content-type": "text/html"}
        self.encoding = "utf-8"
        self.closed = False

    def iter_content(self, chunk_size: int):
        assert chunk_size == 64 * 1024
        yield self._content

    def close(self):
        self.closed = True


class Requester:
    def __init__(self, *responses: Response):
        self.responses = list(responses)
        self.urls: list[str] = []
        self.endpoints = []

    def __call__(self, endpoint, timeout: float):
        assert 0 < timeout <= article_context.REQUEST_TIMEOUT_SECONDS
        self.urls.append(endpoint.url)
        self.endpoints.append(endpoint)
        return self.responses.pop(0)


def source_post(content_html: str) -> SourcePost:
    return SourcePost(
        "kutekians",
        "102",
        "https://x.com/Kutekians/status/102",
        datetime.now(UTC),
        content_html,
        PostKind.NORMAL,
        None,
        None,
        (),
        (),
    )


def allow_public_dns(monkeypatch):
    monkeypatch.setattr(
        article_context.socket,
        "getaddrinfo",
        lambda _host, port, **_kwargs: [(None, None, None, None, ("93.184.216.34", port))],
    )


def test_candidate_urls_uses_every_distinct_authored_thread_link_in_source_order():
    root = source_post(
        'One <a href="https://example.com/one">link</a> and https://example.com/two.'
        '<img src="https://images.example/attachment.jpg">'
    )
    latest = source_post('Duplicate https://example.com/one and https://example.com/three')

    assert article_context.candidate_urls((root, latest)) == (
        "https://example.com/one",
        "https://example.com/two",
        "https://example.com/three",
    )


def test_prepare_extracts_visible_article_text_with_a_pinned_public_connection(monkeypatch):
    allow_public_dns(monkeypatch)
    requester = Requester(
        Response(
            200,
            b"<html><head><title>Market update</title><script>ignore me</script></head><body><main><p>First fact.</p><p>Second fact.</p></main></body></html>",
        )
    )

    bundle = article_context.prepare((source_post("https://example.com/article"),), requester)

    assert requester.urls == ["https://example.com/article"]
    assert requester.endpoints[0].connect_ip == "93.184.216.34"
    assert requester.endpoints[0].hostname == "example.com"
    assert requester.endpoints[0].host_header == "example.com"
    assert bundle.attempted_count == 1
    assert bundle.unavailable_count == 0
    assert bundle.sources[0].title == "Market update"
    assert bundle.sources[0].text == "First fact. Second fact."
    assert "ignore me" not in bundle.sources[0].text


def test_prepare_validates_each_redirect_before_reading_the_final_article(monkeypatch):
    allow_public_dns(monkeypatch)
    requester = Requester(
        Response(302, headers={"location": "https://news.example/article"}),
        Response(200, b"<title>Final</title><p>Final source text.</p>"),
    )

    bundle = article_context.prepare((source_post("https://example.com/start"),), requester)

    assert requester.urls == ["https://example.com/start", "https://news.example/article"]
    assert [endpoint.hostname for endpoint in requester.endpoints] == ["example.com", "news.example"]
    assert bundle.sources[0].requested_url == "https://example.com/start"
    assert bundle.sources[0].final_url == "https://news.example/article"
    assert bundle.sources[0].text == "Final source text."


def test_prepare_rejects_private_network_urls_without_attempting_a_request():
    requester = Requester()

    bundle = article_context.prepare((source_post("http://127.0.0.1/private"),), requester)

    assert requester.urls == []
    assert bundle.sources == ()
    assert bundle.attempted_count == 1
    assert bundle.unavailable_count == 1


def test_prepare_rejects_cross_scheme_standard_ports_without_attempting_a_request():
    requester = Requester()

    bundle = article_context.prepare((source_post("https://example.com:80/article"),), requester)

    assert requester.urls == []
    assert bundle.sources == ()
    assert bundle.attempted_count == 1
    assert bundle.unavailable_count == 1


def test_read_response_rejects_an_expired_aggregate_deadline(monkeypatch):
    monkeypatch.setattr(article_context.time, "monotonic", lambda: 10.0)

    with pytest.raises(article_context.ArticleFetchError, match="timed out"):
        article_context._read_response(Response(200, b"Source text."), 10.0)


def test_candidate_urls_is_bounded_for_one_agent_event():
    links = " ".join(f"https://example.com/{index}" for index in range(article_context.MAX_ARTICLE_URLS + 1))

    urls = article_context.candidate_urls((source_post(links),))

    assert len(urls) == article_context.MAX_ARTICLE_URLS
    assert urls[0] == "https://example.com/0"
    assert urls[-1] == f"https://example.com/{article_context.MAX_ARTICLE_URLS - 1}"
