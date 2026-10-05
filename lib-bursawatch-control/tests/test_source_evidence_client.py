"""Fail closed on changed frozen identities, payloads and incomplete responses."""
from io import BytesIO
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
from control_plane_client import ControlPlaneContractError, ControlPlaneUnavailable


def checksum(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def record():
    result = {'event_key': 'a' * 64, 'version': 1, 'kind': 'original',
        'accepted_at': '2026-10-05T00:20:00+00:00', 'published_at': '2026-10-04T09:00:00+00:00',
        'observed_at': '2026-10-05T00:19:00+00:00', 'endpoint_id': 'rss:stockbit',
        'publisher_id': 'stockbit', 'platform': 'rss', 'source_url': 'https://example.com/news',
        'parser_version': 'parser-1', 'content_hash': 'b' * 64, 'payload_hash': 'c' * 64,
        'original_publisher_id': None, 'origin_status': 'unknown', 'text': 'source',
        'text_truncated': False, 'content_unavailable': False, 'media_refs': []}
    result['evidence_hash'] = checksum(result)
    result['version_ref'] = base64.urlsafe_b64encode(json.dumps(['a' * 64, 1, 'c' * 64], separators=(',', ':')).encode()).decode().rstrip('=')
    return result


def capture(gap=121, status='late', complete=False):
    from datetime import datetime, timedelta
    captured = (datetime.fromisoformat('2026-10-05T00:30:00+00:00') + timedelta(seconds=gap)).isoformat()
    result = {'api_version': 1, 'previous_cutoff': '2026-10-02T00:30:00+00:00',
        'cutoff': '2026-10-05T00:30:00+00:00', 'captured_at': captured,
        'capture_status': status, 'capture_gap_seconds': gap, 'history_available_from': None,
        'history_status': 'unknown', 'overflow': False, 'candidate_limit': 1000,
        'complete': complete, 'items': [{k: v for k, v in record().items() if k not in {'text', 'media_refs'}}]}
    result['manifest_hash'] = checksum(result)
    return result


class Response:
    def __init__(self, body):
        self.body = BytesIO(json.dumps(body).encode())
    def __enter__(self):
        return self
    def __exit__(self, *_):
        pass
    def read(self, size=-1):
        return self.body.read(size)


def client(opener):
    assert importlib.util.find_spec('source_evidence_client') is not None, 'missing immutable source evidence client'
    from source_evidence_client import SourceEvidenceClient
    return SourceEvidenceClient('http://127.0.0.1:9120', 'reader-secret', opener=opener)


def test_capture_validates_window_and_keeps_late_incomplete_metadata():
    requests = []
    def opener(request, timeout):
        requests.append(request)
        return Response(capture())
    result = client(opener).capture_window('2026-10-02T00:30:00Z', '2026-10-05T00:30:00Z')
    assert result['capture_status'] == 'late' and result['complete'] is False
    assert requests[0].full_url.endswith('/v1/source-evidence/capture')
    assert json.loads(requests[0].data)['previous_cutoff'] == '2026-10-02T00:30:00+00:00'
    assert requests[0].get_header('Authorization') == 'Bearer reader-secret'


@pytest.mark.parametrize('gap,status', [(0, 'on_time'), (3, 'on_time'), (120, 'on_time'), (121, 'late')])
def test_capture_grace_window_matches_service_and_keeps_gap(gap, status):
    response = capture(gap=gap, status=status)
    result = client(lambda request, timeout: Response(response)).capture_window('2026-10-02T00:30:00Z', '2026-10-05T00:30:00Z')
    assert result['capture_status'] == status and result['capture_gap_seconds'] == gap


def test_capture_rejects_on_time_claim_beyond_grace_and_late_within_grace():
    from control_plane_client import ControlPlaneContractError
    for gap, status in ((121, 'on_time'), (3, 'late')):
        response = capture(gap=gap, status=status)
        with pytest.raises(ControlPlaneContractError):
            client(lambda request, timeout: Response(response)).capture_window('2026-10-02T00:30:00Z', '2026-10-05T00:30:00Z')


def test_grace_constant_is_identical_in_service_and_client():
    import re
    from source_evidence_client import CAPTURE_GRACE_SECONDS
    service = (Path(__file__).resolve().parents[2] / 'service-bursawatch-control/bin/control_plane/source_evidence.py').read_text()
    assert re.search(rf'^CAPTURE_GRACE_SECONDS = {CAPTURE_GRACE_SECONDS}$', service, re.M)


@pytest.mark.parametrize('mutation', ['hash', 'window', 'ref', 'ceiling'])
def test_capture_rejects_wrong_window_refs_ceiling_and_manifest_integrity(mutation):
    response = capture()
    if mutation == 'hash':
        response['complete'] = True
    elif mutation == 'window':
        response['cutoff'] = '2026-10-04T00:30:00+00:00'
        response['manifest_hash'] = checksum({k: v for k, v in response.items() if k != 'manifest_hash'})
    elif mutation == 'ref':
        response['items'][0]['version_ref'] = 'bad'
        response['manifest_hash'] = checksum({k: v for k, v in response.items() if k != 'manifest_hash'})
    else:
        response['candidate_limit'] = 1
        response['manifest_hash'] = checksum({k: v for k, v in response.items() if k != 'manifest_hash'})
    instance = client(lambda *_args, **_kwargs: Response(response))
    with pytest.raises(ControlPlaneContractError):
        instance.capture_window('2026-10-02T00:30:00Z', '2026-10-05T00:30:00Z')


def test_batch_keeps_exact_ref_order_and_checks_safe_evidence_hash():
    source = record()
    result = client(lambda *_args, **_kwargs: Response({'api_version': 1, 'items': [source]})).read_versions([source['version_ref']])
    assert result[0]['text'] == 'source'
    source['text'] = 'changed'
    with pytest.raises(ControlPlaneContractError):
        client(lambda *_args, **_kwargs: Response({'api_version': 1, 'items': [source]})).read_versions([source['version_ref']])


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'identity', 'hash'])
def test_batch_rejects_partial_extra_and_changed_identity(mutation):
    source = record()
    ref = source['version_ref']
    if mutation == 'identity':
        source['event_key'] = 'd' * 64
    if mutation == 'hash':
        source['payload_hash'] = 'd' * 64
    items = [] if mutation == 'missing' else [source, source] if mutation == 'extra' else [source]
    with pytest.raises(ControlPlaneContractError):
        client(lambda *_args, **_kwargs: Response({'api_version': 1, 'items': items})).read_versions([ref])


def test_transport_error_is_sanitized_and_capture_is_not_silently_retried():
    calls = []
    def opener(*args, **kwargs):
        calls.append(1)
        raise OSError('reader-secret echoed')
    with pytest.raises(ControlPlaneUnavailable) as exc:
        client(opener).capture_window('2026-10-02T00:30:00Z', '2026-10-05T00:30:00Z')
    assert 'reader-secret' not in str(exc.value)
    assert calls == [1]
