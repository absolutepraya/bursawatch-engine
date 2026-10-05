from datetime import timedelta
import json
from urllib.error import HTTPError

import pytest

from chart_img_client import ChartImgConfig, ChartImgError
from chart_img_client.transport import HttpRequest, HttpResponse, ProviderTransport, UrllibTransport
from test_models_config import CUTOFF, png, request


def test_explicit_fake_transport_authenticates_only_fixed_origin_and_decodes():
    observed = []
    def fake(req):
        observed.append(req)
        return HttpResponse(200, {'Content-Type': 'image/png'}, png())
    transport = ProviderTransport(ChartImgConfig('fake-key'), fake)
    artifact = transport.render(request(), now=CUTOFF)
    assert artifact.width == 800
    assert observed[0].url == 'https://api.chart-img.com/v2/tradingview/layout-chart/public123'
    assert observed[0].headers['x-api-key'] == 'fake-key'
    assert json.loads(observed[0].body)['interval'] == '1D'
    assert observed[0].timeout_seconds == 30
    assert 'fake-key' not in repr(observed[0])


@pytest.mark.parametrize('response,code', [
    (HttpResponse(302, {'Location': 'https://evil/?key=secret'}, b''), 'redirect_rejected'),
    (HttpResponse(401, {}, b'secret auth error'), 'authentication_failed'),
    (HttpResponse(503, {}, b'secret'), 'provider_failed'),
    (HttpResponse(200, {'Content-Type': 'image/png'}, png(), final_url='https://evil/'), 'redirect_rejected'),
    (HttpResponse(200, {'Content-Type': 'image/png'}, b'<html>secret</html>'), 'invalid_image'),
])
def test_provider_failures_are_typed_and_never_echo_response(response, code):
    provider = ProviderTransport(ChartImgConfig('fake-key'), lambda req: response)
    with pytest.raises(ChartImgError) as caught:
        provider.render(request(), now=CUTOFF)
    assert caught.value.code == code
    assert caught.value.__cause__ is None
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize('retry_after,expected', [('7', CUTOFF + timedelta(seconds=7)),
                                               ('Mon, 05 Oct 2026 00:31:00 GMT', CUTOFF + timedelta(seconds=60)),
                                               ('broken', None), ('-1', None), ('', None)])
def test_throttle_retry_after_has_explicit_unknown_state(retry_after, expected):
    provider = ProviderTransport(ChartImgConfig('fake-key'),
                                 lambda req: HttpResponse(429, {'Retry-After': retry_after}, b'secret'))
    with pytest.raises(ChartImgError) as caught:
        provider.render(request(), now=CUTOFF)
    assert caught.value.code == 'throttled'
    assert caught.value.retry_at == expected


@pytest.mark.parametrize('failure', ['open', 'read', 'close'])
def test_direct_http_boundary_sanitizes_open_read_and_close_errors(failure):
    class Raw:
        status = 200
        headers = {'Content-Type': 'image/png'}
        def geturl(self):
            return 'https://api.chart-img.com/v2/tradingview/advanced-chart'
        def read1(self, count):
            if failure == 'read':
                raise OSError('secret raw read credential')
            return b''
        def close(self):
            if failure == 'close':
                raise OSError('secret close credential')
    def opener(req, timeout):
        if failure == 'open':
            raise OSError('secret raw open credential')
        return Raw()
    direct = UrllibTransport(open_url=opener)
    req = HttpRequest('https://api.chart-img.com/v2/tradingview/advanced-chart',
                      {'x-api-key': 'secret'}, b'{}', 5, 100)
    with pytest.raises(ChartImgError) as caught:
        direct(req)
    assert caught.value.code == 'transport_failed'
    assert caught.value.__cause__ is None
    assert 'secret' not in str(caught.value)


def test_direct_reader_is_bounded_and_closed_on_oversize():
    closed = []
    class Raw:
        status = 200
        headers = {}
        def geturl(self):
            return 'https://api.chart-img.com/v2/tradingview/advanced-chart'
        def read1(self, count):
            return b'x' * count
        def close(self):
            closed.append(True)
    req = HttpRequest('https://api.chart-img.com/v2/tradingview/advanced-chart', {}, b'{}', 5, 100)
    with pytest.raises(ChartImgError) as caught:
        UrllibTransport(open_url=lambda req, timeout: Raw())(req)
    assert caught.value.code == 'response_too_large'
    assert closed == [True]


def test_direct_transport_rejects_untrusted_request_url_before_open():
    def forbidden(*args, **kwargs):
        pytest.fail('untrusted request invoked network')
    with pytest.raises(ChartImgError):
        UrllibTransport(open_url=forbidden)(HttpRequest('https://evil/', {}, b'{}', 5, 100))


def test_direct_http_error_does_not_read_or_follow_redirect():
    closed = []
    class ErrorBody:
        def read(self, *args):
            pytest.fail('provider error body must not be read')
        def close(self):
            closed.append(True)
    def opener(req, timeout):
        raise HTTPError(req.full_url, 302, 'secret', {'Location': 'https://evil/'}, ErrorBody())
    response = UrllibTransport(open_url=opener)(HttpRequest(
        'https://api.chart-img.com/v2/tradingview/advanced-chart', {}, b'{}', 5, 100))
    assert response.status == 302
    assert response.body == b''
    assert closed == [True]


@pytest.mark.parametrize('timeout,limit', [(0, 100), (91, 100), (float('nan'), 100),
                                         (5, -1), (5, 8_000_001)])
def test_direct_request_limits_cannot_disable_bounding(timeout, limit):
    with pytest.raises(ChartImgError):
        HttpRequest('https://api.chart-img.com/v2/tradingview/advanced-chart', {}, b'{}', timeout, limit)


def test_total_deadline_is_checked_after_open_and_before_read():
    times = iter([0, 6])
    closed = []
    class Raw:
        status = 200
        headers = {}
        def geturl(self):
            return 'https://api.chart-img.com/v2/tradingview/advanced-chart'
        def read1(self, count):
            pytest.fail('expired transport performed body read')
        def close(self):
            closed.append(True)
    with pytest.raises(ChartImgError) as caught:
        UrllibTransport(open_url=lambda req, timeout: Raw(), monotonic=lambda: next(times))(
            HttpRequest('https://api.chart-img.com/v2/tradingview/advanced-chart', {}, b'{}', 5, 100))
    assert caught.value.code == 'deadline_exceeded'
    assert closed == [True]
