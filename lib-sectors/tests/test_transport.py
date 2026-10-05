import io
from urllib.error import HTTPError
import pytest
import sectors_client
from sectors_client import Config, RequestIdentity, AuthenticationFailure, AllowanceExhausted, Throttled, TransportFailure, UncertainOutcome


@pytest.fixture
def transport_class():
    return sectors_client.HTTPTransport


class Response(io.BytesIO):
    status = 200
    headers = {}
    def geturl(self):
        return 'https://api.sectors.app/v2/close/?date=2026-10-02'


def config(tmp_path, **changes):
    return Config(store_path=tmp_path / 'cache.sqlite3', caller='morning', billing_window='oct', caller_limit=40, api_key='private-key', **changes)


def test_fixed_origin_raw_key_user_agent_timeout_and_json(transport_class, tmp_path):
    observed = []
    def open_(request, timeout):
        observed.append((request.full_url, dict(request.header_items()), timeout))
        return Response(b'{"results":[]}')
    t = transport_class(config(tmp_path), opener=open_)
    assert t.get(RequestIdentity('/v2/close/', {'date':'2026-10-02'})) == {'results': []}
    url, headers, timeout = observed[0]
    assert url.startswith('https://api.sectors.app/')
    assert headers['Authorization'] == 'private-key'
    assert headers['User-agent'] == 'Bursawatch-Sectors/1.0'
    assert timeout == 15


@pytest.mark.parametrize('status,error', [(301,TransportFailure),(302,TransportFailure),(401,AuthenticationFailure),(403,AuthenticationFailure),(402,AllowanceExhausted),(429,Throttled),(503,TransportFailure)])
def test_status_failures_never_expose_provider_body(transport_class,tmp_path,status,error):
    def open_(request, timeout):
        raise HTTPError(request.full_url,status,'private-key',{'Retry-After':'3'},io.BytesIO(b'private-key'))
    with pytest.raises(error) as exc:
        transport_class(config(tmp_path),opener=open_).get(RequestIdentity('/v2/close/',{'date':'2026-10-02'}))
    assert 'private-key' not in str(exc.value)
    assert exc.value.__context__ is None or exc.value.__suppress_context__
    if status == 429:
        assert exc.value.retry_after == 3


def test_quota_error_code_is_distinct_from_temporary_429(transport_class,tmp_path):
    def open_(request, timeout):
        raise HTTPError(request.full_url,429,'quota',{},io.BytesIO(b'{"code":"insufficient_credits"}'))
    with pytest.raises(AllowanceExhausted):
        transport_class(config(tmp_path),opener=open_).get(RequestIdentity('/v2/close/',{'date':'2026-10-02'}))


def test_size_invalid_json_redirect_and_uncertain_network_are_safe(transport_class,tmp_path):
    identity = RequestIdentity('/v2/close/',{'date':'2026-10-02'})
    for data in [b'xxxxxxxxx',b'{invalid']:
        with pytest.raises(TransportFailure):
            transport_class(config(tmp_path,max_bytes=8),opener=lambda *a,**kw:Response(data)).get(identity)
    r = Response(b'{}')
    r.geturl = lambda:'https://evil.test/'
    with pytest.raises(TransportFailure):
        transport_class(config(tmp_path),opener=lambda *a,**kw:r).get(identity)
    def timeout(*a,**kw):
        raise TimeoutError('private-key')
    with pytest.raises(UncertainOutcome) as exc:
        transport_class(config(tmp_path),opener=timeout).get(identity)
    assert 'private-key' not in str(exc.value)


def test_default_opener_refuses_redirect_before_second_request(transport_class,tmp_path):
    t = transport_class(config(tmp_path))
    from urllib.request import Request
    redirect = next(h for h in t.opener.handlers if type(h).__name__ == '_RefuseRedirect')
    assert redirect.redirect_request(Request('https://api.sectors.app'), None, 302, '', {}, 'https://evil.test/') is None


def test_unrepresentable_cooldown_remains_unknown_without_overflow(transport_class,tmp_path):
    def open_(request, timeout):
        raise HTTPError(request.full_url,429,'throttle',{'Retry-After':'999999999999999999'},io.BytesIO(b'{}'))
    with pytest.raises(Throttled) as error:
        transport_class(config(tmp_path),opener=open_).get(RequestIdentity('/v2/close/',{'date':'2026-10-02'}))
    assert error.value.retry_after is None


@pytest.mark.parametrize('failure', ['read', 'close'])
def test_http_error_body_and_cleanup_failures_are_sanitized(transport_class,tmp_path,failure):
    class BrokenBody:
        failed_close = False
        def read(self, *args):
            if failure == 'read':
                raise RuntimeError('SYNTHETIC_SECRET')
            return b'{}'
        def close(self):
            if failure == 'close' and not self.failed_close:
                self.failed_close = True
                raise RuntimeError('SYNTHETIC_SECRET')
    def open_(request,timeout):
        raise HTTPError(request.full_url,429,'private provider details',{},BrokenBody())
    with pytest.raises(UncertainOutcome) as error:
        transport_class(config(tmp_path),opener=open_).get(RequestIdentity('/v2/close/',{'date':'2026-10-02'}))
    assert 'SYNTHETIC_SECRET' not in str(error.value)
    assert error.value.__suppress_context__
