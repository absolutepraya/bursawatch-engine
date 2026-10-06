from dataclasses import replace
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import sqlite3

import pytest

from chart_img_client import ChartImgConfig, ChartImgError
from chart_img_client.cache import ChartImgClient, RenderCache
from chart_img_client.transport import HttpResponse, ProviderTransport, UrllibTransport
from test_models_config import CUTOFF, png, request


def store(tmp_path):
    cache = RenderCache(tmp_path / 'chart.sqlite')
    cache.initialize()
    return cache


def client(cache, http, now=CUTOFF):
    return ChartImgClient(cache, ProviderTransport(ChartImgConfig('fake-key'), http), clock=lambda: now)


def success(req):
    return HttpResponse(200, {'Content-Type': 'image/png'}, png())


def test_cache_only_miss_never_calls_http_and_hits_reuse_immutable_bytes(tmp_path):
    cache = store(tmp_path)
    def forbidden(req):
        pytest.fail('cache-only invoked HTTP')
    local = client(cache, forbidden)
    with pytest.raises(ChartImgError) as caught:
        local.render(request(), cache_only=True)
    assert caught.value.code == 'cache_miss'
    artifact = client(cache, success).render(request(), cache_only=False)
    assert local.render(request(), cache_only=True) == artifact
    assert local.render(request(), cache_only=False) == artifact
    assert cache.allowance(now=CUTOFF)['used'] == 1
    with pytest.raises(ChartImgError) as caught:
        client(cache, forbidden, CUTOFF + timedelta(days=1)).render(request(), cache_only=False, max_age_seconds=60)
    assert caught.value.code == 'stale_cache'
    assert local.render(request(), cache_only=True).data == artifact.data


def test_revisions_cutoffs_and_provider_options_require_distinct_fetches(tmp_path):
    cache = store(tmp_path)
    first = client(cache, success).render(request(), cache_only=False)
    second = client(cache, success, CUTOFF + timedelta(seconds=1)).render(replace(request(), layout_revision='v2'), cache_only=False)
    assert first.request.identity != second.request.identity
    assert cache.allowance(now=CUTOFF + timedelta(seconds=1))['used'] == 2


def test_one_second_and_rolling_24_hour_allowances_are_shared(tmp_path):
    cache = store(tmp_path)
    other = RenderCache(cache.path)
    for index in range(50):
        now = CUTOFF + timedelta(seconds=index)
        client(cache if index % 2 else other, success, now).render(replace(request(), profile_revision=f'p{index}'), cache_only=False)
        if index == 0:
            with pytest.raises(ChartImgError) as caught:
                client(other, success, now + timedelta(milliseconds=999)).render(replace(request(), profile_revision='too-fast'), cache_only=False)
            assert caught.value.code == 'rate_limited'
            assert caught.value.retry_at == CUTOFF + timedelta(seconds=1)
    with pytest.raises(ChartImgError) as caught:
        client(other, success, CUTOFF + timedelta(hours=23)).render(replace(request(), profile_revision='over-budget'), cache_only=False)
    assert caught.value.code == 'allowance_exhausted'
    assert caught.value.retry_at == CUTOFF + timedelta(days=1)
    assert client(other, success, CUTOFF + timedelta(days=1)).render(replace(request(), profile_revision='next-window'), cache_only=False)


def test_two_consumers_coordinate_one_fetch_without_holding_network_transaction(tmp_path):
    cache = store(tmp_path)
    entered, release = Event(), Event()
    def delayed(req):
        entered.set()
        assert release.wait(5)
        return success(req)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client(cache, delayed).render, request(), cache_only=False)
        assert entered.wait(5)
        try:
            with pytest.raises(ChartImgError) as caught:
                client(RenderCache(cache.path), success).render(request(), cache_only=False)
            assert caught.value.code == 'render_in_progress'
            assert cache.allowance(now=CUTOFF)['used'] == 1
        finally:
            release.set()
        artifact = first.result(timeout=5)
    assert client(cache, delayed).render(request(), cache_only=False).sha256 == artifact.sha256


@pytest.mark.parametrize('error_code', ['transport_failed', 'deadline_exceeded'])
def test_uncertain_transport_attempts_are_charged_and_need_audited_resolution(tmp_path, error_code):
    cache = store(tmp_path)
    def uncertain(req):
        raise ChartImgError(error_code)
    with pytest.raises(ChartImgError):
        client(cache, uncertain).render(request(), cache_only=False)
    assert cache.allowance(now=CUTOFF)['used'] == 1
    with pytest.raises(ChartImgError) as caught:
        client(cache, success, CUTOFF + timedelta(seconds=2)).render(request(), cache_only=False)
    assert caught.value.code == 'outcome_unknown'
    attempt_id = cache.unresolved()[0]['attempt_id']
    with pytest.raises(ChartImgError):
        cache.resolve_unknown(attempt_id, now=CUTOFF + timedelta(seconds=2), evidence_ref='')
    cache.resolve_unknown(attempt_id, now=CUTOFF + timedelta(seconds=2), evidence_ref='review:writer-stopped')
    assert client(cache, success, CUTOFF + timedelta(seconds=2)).render(request(), cache_only=False)
    assert cache.allowance(now=CUTOFF + timedelta(seconds=2))['used'] == 2  # Never refunds.
    assert cache.audit_log()[0]['evidence_ref'] == 'review:writer-stopped'


def test_abandoned_lease_becomes_unknown_without_automatic_second_request(tmp_path):
    cache = store(tmp_path)
    cache.reserve(request(), now=CUTOFF, lease_seconds=31)
    with pytest.raises(ChartImgError) as caught:
        client(cache, success, CUTOFF + timedelta(seconds=32)).render(request(), cache_only=False)
    assert caught.value.code == 'outcome_unknown'
    assert cache.allowance(now=CUTOFF)['used'] == 1
    cache.resolve_unknown(cache.unresolved()[0]['attempt_id'], now=CUTOFF + timedelta(seconds=32),
                          evidence_ref='review:expired-writer-stopped')
    assert client(cache, success, CUTOFF + timedelta(seconds=32)).render(request(), cache_only=False)


def test_unknown_throttle_blocks_all_consumers_until_explicit_safe_recovery(tmp_path):
    cache = store(tmp_path)
    with pytest.raises(ChartImgError):
        client(cache, lambda req: HttpResponse(429, {}, b'')).render(request(), cache_only=False)
    attempt_id = cache.unresolved()[0]['attempt_id']
    for seconds in (1, 86401):
        with pytest.raises(ChartImgError) as caught:
            client(cache, success, CUTOFF + timedelta(seconds=seconds)).render(replace(request(), profile_revision='other'), cache_only=False)
        assert caught.value.code == 'throttle_unknown'
    with pytest.raises(ChartImgError):
        cache.resolve_unknown(attempt_id, now=CUTOFF + timedelta(hours=23), evidence_ref='review:cooldown')
    cache.resolve_unknown(attempt_id, now=CUTOFF + timedelta(days=1), evidence_ref='review:cooldown-and-writer-stopped')
    assert client(cache, success, CUTOFF + timedelta(days=1)).render(request(), cache_only=False)
    assert cache.audit_log()[0]['attempt_id'] == attempt_id


def test_multiple_unknown_throttles_keep_global_gate_until_each_is_resolved(tmp_path):
    cache = store(tmp_path)
    first = cache.reserve(request(), now=CUTOFF)
    second_request = replace(request(), profile_revision='second')
    second = cache.reserve(second_request, now=CUTOFF + timedelta(seconds=1))
    cache.fail(first, ChartImgError('throttled'), now=CUTOFF + timedelta(seconds=2))
    cache.fail(second, ChartImgError('throttled'), now=CUTOFF + timedelta(seconds=3))
    after_cooldown = CUTOFF + timedelta(days=1, seconds=4)
    cache.resolve_unknown(second, now=after_cooldown, evidence_ref='review:second-writer-stopped')
    assert {row['attempt_id'] for row in cache.unresolved()} == {first}
    third_request = replace(request(), profile_revision='third')
    with pytest.raises(ChartImgError) as caught:
        client(cache, success, after_cooldown).render(third_request, cache_only=False)
    assert caught.value.code == 'throttle_unknown'
    assert cache.allowance(now=after_cooldown)['used'] == 0
    cache.resolve_unknown(first, now=after_cooldown, evidence_ref='review:first-writer-stopped')
    assert client(cache, success, after_cooldown).render(third_request, cache_only=False)
    assert {row['attempt_id'] for row in cache.audit_log()} == {first, second}


@pytest.mark.parametrize('retry_after,blocked_code', [('10', 'throttled'), ('', 'throttle_unknown')])
def test_close_failure_after_429_keeps_provider_wide_gate(tmp_path, retry_after, blocked_code):
    cache = store(tmp_path)
    class Raw:
        status = 429
        headers = {'Retry-After': retry_after}
        def geturl(self):
            return 'https://api.chart-img.com/v2/tradingview/layout-chart/public123'
        def close(self):
            raise OSError('private cleanup detail')
    provider = ProviderTransport(ChartImgConfig('fake-key'), UrllibTransport(open_url=lambda req, timeout: Raw()))
    with pytest.raises(ChartImgError) as caught:
        ChartImgClient(cache, provider, clock=lambda: CUTOFF).render(request(), cache_only=False)
    assert caught.value.code == 'throttled'
    with pytest.raises(ChartImgError) as blocked:
        client(cache, success, CUTOFF + timedelta(seconds=2)).render(
            replace(request(), profile_revision='other'), cache_only=False)
    assert blocked.value.code == blocked_code
    assert cache.allowance(now=CUTOFF + timedelta(seconds=2))['used'] == 1


def test_known_throttle_honors_global_retry_after_and_counts_attempt(tmp_path):
    cache = store(tmp_path)
    with pytest.raises(ChartImgError):
        client(cache, lambda req: HttpResponse(429, {'Retry-After': '10'}, b'')).render(request(), cache_only=False)
    with pytest.raises(ChartImgError) as caught:
        client(cache, success, CUTOFF + timedelta(seconds=9)).render(replace(request(), profile_revision='other'), cache_only=False)
    assert caught.value.code == 'throttled'
    assert caught.value.retry_at == CUTOFF + timedelta(seconds=10)
    assert client(cache, success, CUTOFF + timedelta(seconds=10)).render(request(), cache_only=False)
    assert cache.allowance(now=CUTOFF + timedelta(seconds=10))['used'] == 2


def test_cache_corruption_fails_closed_without_provider_repair(tmp_path):
    cache = store(tmp_path)
    client(cache, success).render(request(), cache_only=False)
    with sqlite3.connect(cache.path) as db:
        db.execute('UPDATE artifacts SET data=?', (b'corrupted',))
    def forbidden(req):
        pytest.fail('corrupt immutable image was silently rerendered')
    with pytest.raises(ChartImgError) as caught:
        client(cache, forbidden).render(request(), cache_only=False)
    assert caught.value.code == 'cache_corrupt'


def test_constructor_does_not_create_or_open_store(tmp_path):
    path = tmp_path / 'not-created.sqlite'
    cache = RenderCache(path)
    ChartImgClient(cache)
    assert not path.exists()


def test_cache_database_with_uri_characters_and_missing_cache_only_never_creates(tmp_path):
    path = tmp_path / 'chart?store.sqlite'
    cache = RenderCache(path)
    with pytest.raises(ChartImgError) as caught:
        ChartImgClient(cache).render(request(), cache_only=True)
    assert caught.value.code == 'cache_unavailable'
    assert not path.exists()
    cache.initialize()
    assert client(cache, success).render(request(), cache_only=False)
    assert path.exists()


def test_retrieval_provenance_uses_response_completion_time(tmp_path):
    cache = store(tmp_path)
    now = [CUTOFF]
    def slow_success(req):
        now[0] += timedelta(seconds=9)
        return success(req)
    owner = ChartImgClient(cache, ProviderTransport(ChartImgConfig('fake-key'), slow_success), clock=lambda: now[0])
    artifact = owner.render(request(), cache_only=False)
    assert artifact.retrieved_at == CUTOFF + timedelta(seconds=9)


def test_retry_after_is_relative_to_response_receipt(tmp_path):
    cache = store(tmp_path)
    now = [CUTOFF]
    def slow_throttle(req):
        now[0] += timedelta(seconds=9)
        return HttpResponse(429, {'Retry-After': '10'}, b'')
    owner = ChartImgClient(cache, ProviderTransport(ChartImgConfig('fake-key'), slow_throttle), clock=lambda: now[0])
    with pytest.raises(ChartImgError) as caught:
        owner.render(request(), cache_only=False)
    assert caught.value.retry_at == CUTOFF + timedelta(seconds=19)


def test_default_cache_only_miss_never_invokes_transport_or_charges_allowance(tmp_path):
    cache = store(tmp_path)
    def forbidden(req):
        pytest.fail('default render contacted provider')
    with pytest.raises(ChartImgError) as caught:
        client(cache, forbidden).render(request())
    assert caught.value.code == 'cache_miss'
    assert cache.allowance(now=CUTOFF)['used'] == 0
    assert cache.unresolved() == []


@pytest.mark.parametrize('value', [None, 0, ''])
def test_only_explicit_boolean_false_can_select_network_mode(tmp_path, value):
    cache = store(tmp_path)
    def forbidden(req):
        pytest.fail('non-boolean mode invoked HTTP')
    with pytest.raises(ChartImgError) as caught:
        client(cache, forbidden).render(request(), cache_only=value)
    assert caught.value.code == 'invalid_request'
    assert cache.allowance(now=CUTOFF)['used'] == 0
