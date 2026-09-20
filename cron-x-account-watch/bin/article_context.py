from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import urllib3
from urllib3 import HTTPConnectionPool, HTTPSConnectionPool

from models import SourcePost


MAX_ARTICLE_URLS = 12
MAX_PARALLEL_FETCHES = 4
MAX_REDIRECTS = 5
MAX_URL_CHARACTERS = 2_048
MAX_DOWNLOAD_BYTES = 1_000_000
MAX_ARTICLE_CHARACTERS = 4_000
REQUEST_TIMEOUT_SECONDS = 8
PREPARATION_TIMEOUT_SECONDS = 20
_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})
_BLOCK_TAGS = frozenset({"article", "main", "p", "div", "section", "h1", "h2", "h3", "li", "br"})


class ArticleFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArticleSource:
    requested_url: str
    final_url: str
    title: str
    text: str
    truncated: bool


@dataclass(frozen=True)
class ArticleBundle:
    sources: tuple[ArticleSource, ...]
    attempted_count: int
    unavailable_count: int


@dataclass(frozen=True)
class _ResolvedUrl:
    url: str
    scheme: str
    hostname: str
    port: int
    request_target: str
    host_header: str
    connect_ip: str


class _PinnedResponse:
    """Response wrapper that closes the exact-IP urllib3 pool it owns."""

    def __init__(self, response, pool) -> None:
        self._response = response
        self._pool = pool
        self.status_code = response.status
        self.headers = response.headers

    def iter_content(self, chunk_size: int):
        yield from self._response.stream(chunk_size, decode_content=True)

    def iter_content_with_deadline(self, chunk_size: int, deadline: float):
        chunks = self._response.stream(chunk_size, decode_content=True)
        while True:
            try:
                socket_handle = self._response._fp.fp.raw._sock
                socket_handle.settimeout(_remaining_timeout(deadline))
                yield next(chunks)
            except StopIteration:
                return
            except (AttributeError, OSError) as exc:
                raise ArticleFetchError("linked article response is invalid") from exc

    def close(self) -> None:
        self._response.release_conn()
        self._pool.close()


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self._title: list[str] = []
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK_TAGS:
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._text.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        if not self._ignored_depth and not self._in_title:
            self._text.append(data)

    @property
    def title(self) -> str:
        return _clean_text(" ".join(self._title), 240)

    @property
    def raw_text(self) -> str:
        return _clean_text(" ".join(self._text), MAX_DOWNLOAD_BYTES)


class _LinkParser(HTMLParser):
    """Collect authored text URLs and explicit link destinations, not media."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def _append(self, value: str) -> None:
        normalized = value.rstrip(_TRAILING_URL_PUNCTUATION)
        if normalized and normalized not in self.urls:
            self.urls.append(normalized)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and isinstance(value, str) and value.startswith(("http://", "https://")):
                self._append(value)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        for match in _URL_RE.finditer(data):
            self._append(match.group(0))


def _clean_text(value: str, limit: int) -> str:
    return " ".join(unescape(value).split())[:limit].strip()


def _normalise_url(value: str) -> str:
    raw = value.strip().rstrip(_TRAILING_URL_PUNCTUATION)
    if not raw or len(raw) > MAX_URL_CHARACTERS:
        raise ArticleFetchError("linked article URL is invalid")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise ArticleFetchError("linked article URL is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ArticleFetchError("linked article URL is invalid")
    allowed_ports = {"http": {None, 80}, "https": {None, 443}}
    if parsed.username or parsed.password or port not in allowed_ports[parsed.scheme]:
        raise ArticleFetchError("linked article URL is invalid")
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme, host, parsed.path or "/", parsed.query, ""))


def _resolve_public_url(value: str) -> _ResolvedUrl:
    normalized = _normalise_url(value)
    parsed = urlsplit(normalized)
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise ArticleFetchError("linked article URL is not publicly reachable") from None
        resolved = {entry[4][0] for entry in addresses}
        if not resolved:
            raise ArticleFetchError("linked article URL is not publicly reachable")
        try:
            if not all(ipaddress.ip_address(candidate).is_global for candidate in resolved):
                raise ArticleFetchError("linked article URL is not publicly reachable")
        except ValueError:
            raise ArticleFetchError("linked article URL is not publicly reachable") from None
        connect_ip = sorted(resolved)[0]
    else:
        if not address.is_global:
            raise ArticleFetchError("linked article URL is not publicly reachable")
        connect_ip = str(address)
    host_header = f"[{hostname}]" if ":" in hostname else hostname
    request_target = parsed.path or "/"
    if parsed.query:
        request_target = f"{request_target}?{parsed.query}"
    return _ResolvedUrl(
        url=normalized,
        scheme=parsed.scheme,
        hostname=hostname,
        port=port,
        request_target=request_target,
        host_header=host_header,
        connect_ip=connect_ip,
    )


def _request(endpoint: _ResolvedUrl, timeout: float) -> _PinnedResponse:
    pool = (
        HTTPSConnectionPool(
            endpoint.connect_ip,
            port=endpoint.port,
            assert_hostname=endpoint.hostname,
            server_hostname=endpoint.hostname,
            retries=False,
        )
        if endpoint.scheme == "https"
        else HTTPConnectionPool(endpoint.connect_ip, port=endpoint.port, retries=False)
    )
    try:
        response = pool.urlopen(
            "GET",
            endpoint.request_target,
            headers={"Host": endpoint.host_header, "User-Agent": "BursaWatch-Article-Context/1.0"},
            preload_content=False,
            redirect=False,
            retries=False,
            timeout=timeout,
        )
    except (OSError, urllib3.exceptions.HTTPError) as exc:
        pool.close()
        raise ArticleFetchError("linked article request failed") from exc
    return _PinnedResponse(response, pool)


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ArticleFetchError("linked article retrieval timed out")
    return min(REQUEST_TIMEOUT_SECONDS, remaining)


def _fetch_article(requested_url: str, requester=_request, deadline: float | None = None) -> ArticleSource:
    deadline = deadline if deadline is not None else time.monotonic() + PREPARATION_TIMEOUT_SECONDS
    current_url = _normalise_url(requested_url)
    for _ in range(MAX_REDIRECTS + 1):
        response = None
        try:
            endpoint = _resolve_public_url(current_url)
            response = requester(endpoint, _remaining_timeout(deadline))
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not isinstance(location, str) or not location.strip():
                    raise ArticleFetchError("linked article redirect is invalid")
                current_url = _normalise_url(urljoin(endpoint.url, location))
                continue
            if not 200 <= response.status_code < 300:
                raise ArticleFetchError("linked article request failed")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in _CONTENT_TYPES:
                raise ArticleFetchError("linked article is not HTML")
            encoding = getattr(response, "encoding", None) or "utf-8"
            parser = _VisibleTextParser()
            parser.feed(_read_response(response, deadline).decode(encoding, errors="replace"))
            parser.close()
            raw_text = parser.raw_text
            if not raw_text:
                raise ArticleFetchError("linked article has no readable text")
            text = raw_text[:MAX_ARTICLE_CHARACTERS].rstrip()
            return ArticleSource(
                requested_url=_normalise_url(requested_url),
                final_url=endpoint.url,
                title=parser.title,
                text=text,
                truncated=len(raw_text) > len(text),
            )
        finally:
            if response is not None:
                response.close()
    raise ArticleFetchError("linked article redirected too many times")


def _extract_urls(content_html: str) -> tuple[str, ...]:
    parser = _LinkParser()
    parser.feed(content_html)
    parser.close()
    return tuple(parser.urls)


def candidate_urls(thread_posts: tuple[SourcePost, ...]) -> tuple[str, ...]:
    urls: list[str] = []
    for post in thread_posts:
        for url in _extract_urls(post.content_html):
            if url not in urls:
                urls.append(url)
    return tuple(urls[:MAX_ARTICLE_URLS])


def _read_response(response, deadline: float) -> bytes:
    try:
        content_length = response.headers.get("content-length")
        if content_length is not None and int(content_length) > MAX_DOWNLOAD_BYTES:
            raise ArticleFetchError("linked article is too large")
    except ValueError as exc:
        raise ArticleFetchError("linked article response is invalid") from exc
    body = bytearray()
    bounded_chunks = getattr(response, "iter_content_with_deadline", None)
    chunks = (
        bounded_chunks(64 * 1024, deadline)
        if callable(bounded_chunks)
        else response.iter_content(chunk_size=64 * 1024)
    )
    for chunk in chunks:
        if time.monotonic() >= deadline:
            raise ArticleFetchError("linked article retrieval timed out")
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > MAX_DOWNLOAD_BYTES:
            raise ArticleFetchError("linked article is too large")
    return bytes(body)


def prepare(thread_posts: tuple[SourcePost, ...], requester=_request) -> ArticleBundle:
    urls = candidate_urls(thread_posts)
    if not urls:
        return ArticleBundle((), 0, 0)
    deadline = time.monotonic() + PREPARATION_TIMEOUT_SECONDS
    sources: list[ArticleSource | None] = [None] * len(urls)
    unavailable_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_FETCHES, len(urls))) as executor:
        futures = {
            executor.submit(_fetch_article, url, requester, deadline): index
            for index, url in enumerate(urls)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                sources[index] = future.result()
            # Linked context is optional. A malformed or unavailable one URL must
            # never prevent the watcher from processing its claimed X event.
            except Exception:
                unavailable_count += 1
    return ArticleBundle(tuple(source for source in sources if source is not None), len(urls), unavailable_count)
