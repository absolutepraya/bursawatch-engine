"""Fixed-origin, no-redirect HTTP with bounded response handling and safe errors."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import time
import math
from typing import Callable, Mapping
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import ChartImgConfig
from .models import ChartImgError, ImageArtifact, RenderRequest, aware, canonical, validate_image

ORIGIN = 'https://api.chart-img.com'


@dataclass(frozen=True)
class HttpRequest:
    url: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    timeout_seconds: float
    max_bytes: int

    def __post_init__(self):
        if (not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds)
                or not 0 < self.timeout_seconds <= 90 or type(self.max_bytes) is not int
                or not 0 < self.max_bytes <= 8_000_000 or not isinstance(self.body, bytes)
                or len(self.body) > 64_000):
            raise ChartImgError('invalid_request')


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    final_url: str | None = field(default=None, repr=False)


def _allowed_url(url: str) -> bool:
    import re
    return isinstance(url, str) and re.fullmatch(
        r'https://api\.chart-img\.com/v2/tradingview/(advanced-chart|layout-chart/[A-Za-z0-9_-]{1,100})', url) is not None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """Callable adapter. No retries. Inject open_url only for controlled tests."""
    def __init__(self, *, open_url=None, monotonic: Callable[[], float] = time.monotonic):
        self._open = open_url or build_opener(_NoRedirect()).open
        self._monotonic = monotonic

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not _allowed_url(request.url):
            raise ChartImgError('invalid_request')
        raw = None
        failure = None
        result = None
        try:
            deadline = self._monotonic() + request.timeout_seconds
            req = Request(request.url, data=request.body, headers=dict(request.headers), method='POST')
            try:
                raw = self._open(req, timeout=request.timeout_seconds)
            except HTTPError as error:
                raw = error  # Close even error bodies without exposing or reading them.
            status = raw.status if hasattr(raw, 'status') else raw.code
            headers = {key: raw.headers.get(key, '') for key in ('Content-Type', 'Retry-After')}
            final_url = raw.geturl()
            body = bytearray()
            if status == 200:
                while True:
                    remaining = deadline - self._monotonic()
                    if remaining <= 0:
                        raise ChartImgError('deadline_exceeded')
                    # read1 performs at most one socket read rather than waiting to
                    # fill the whole byte limit. Update the socket deadline when
                    # the standard urllib response exposes its socket.
                    sock = getattr(getattr(getattr(raw, 'fp', None), 'raw', None), '_sock', None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    chunk = raw.read1(min(64_000, request.max_bytes + 1 - len(body)))
                    if self._monotonic() > deadline:
                        raise ChartImgError('deadline_exceeded')
                    if not chunk:
                        break
                    body.extend(chunk)
                    if len(body) > request.max_bytes:
                        raise ChartImgError('response_too_large')
            result = HttpResponse(status, headers, bytes(body), final_url)
        except ChartImgError as error:
            failure = error.code
        except Exception:
            failure = 'transport_failed'
        finally:
            if raw is not None:
                try:
                    raw.close()
                except Exception:
                    # A safely observed 429 still establishes a provider-wide
                    # throttle even if response cleanup fails.
                    if result is None or result.status != 429:
                        failure = 'transport_failed'
        if failure:
            raise ChartImgError(failure) from None
        return result


def _retry_at(value: str, now: datetime) -> datetime | None:
    try:
        if value.strip().isdigit():
            return now + timedelta(seconds=int(value.strip()))
        parsed = aware(parsedate_to_datetime(value))
        return parsed if parsed >= now else None
    except Exception:
        return None


class ProviderTransport:
    """Provider request/validation boundary; callers coordinate allowance via store."""
    def __init__(self, config: ChartImgConfig, http: Callable[[HttpRequest], HttpResponse]):
        self._config = config
        self._http = http

    @property
    def timeout_seconds(self) -> float:
        return self._config.timeout_seconds

    def render(self, request: RenderRequest, *, now: datetime, clock=None) -> ImageArtifact:
        now = aware(now)
        req = HttpRequest(ORIGIN + request.endpoint,
                          {'x-api-key': self._config.api_key, 'Content-Type': 'application/json', 'Accept': 'image/png'},
                          canonical(request.payload).encode(), self._config.timeout_seconds, self._config.max_bytes)
        try:
            response = self._http(req)
        except ChartImgError as error:
            code = error.code if error.code in {'transport_failed', 'response_too_large', 'deadline_exceeded'} else 'transport_failed'
            raise ChartImgError(code) from None
        except Exception:
            raise ChartImgError('transport_failed') from None
        now = aware(clock()) if clock is not None else now
        try:
            status = response.status
            headers = {str(k).lower(): v for k, v in response.headers.items()}
            if 300 <= status < 400 or response.final_url not in {None, req.url}:
                raise ChartImgError('redirect_rejected')
            if status in {401, 403}:
                raise ChartImgError('authentication_failed')
            if status == 429:
                raise ChartImgError('throttled', retry_at=_retry_at(headers.get('retry-after', ''), now))
            if status != 200:
                raise ChartImgError('provider_failed')
            return validate_image(response.body, headers.get('content-type', ''), request, now,
                                  max_bytes=self._config.max_bytes)
        except ChartImgError:
            raise
        except Exception:
            raise ChartImgError('invalid_response') from None
