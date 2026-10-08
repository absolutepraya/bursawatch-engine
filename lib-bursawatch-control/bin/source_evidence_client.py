"""Read-only immutable source evidence client, using only the standard library."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from control_plane_client import ControlPlaneContractError, ControlPlaneUnavailable

_HEX = re.compile(r'[0-9a-f]{64}\Z')
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# Keep identical to service-bursawatch-control's source_evidence module.
CAPTURE_GRACE_SECONDS = 120
EARLY_TOLERANCE_SECONDS = 15  # must equal the Control Plane's tolerance for the database clock offset
_ITEM_FIELDS = {'event_key', 'version', 'kind', 'accepted_at', 'published_at', 'observed_at',
                'endpoint_id', 'publisher_id', 'platform', 'source_url', 'parser_version',
                'content_hash', 'payload_hash', 'original_publisher_id', 'origin_status',
                'text_truncated', 'content_unavailable', 'evidence_hash', 'version_ref'}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('source timestamp requires a timezone')
    return parsed.astimezone(timezone.utc).isoformat()


def _reference(value: object) -> tuple[str, int, str]:
    if type(value) is not str or len(value) > 256:
        raise ValueError('source reference is invalid')
    decoded = json.loads(base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True))
    key, version, payload_hash = decoded
    if (type(key) is not str or not _HEX.fullmatch(key) or type(version) is not int or version < 1
            or type(payload_hash) is not str or not _HEX.fullmatch(payload_hash)):
        raise ValueError('source reference identity is invalid')
    canonical = base64.urlsafe_b64encode(json.dumps(decoded, separators=(',', ':')).encode()).decode().rstrip('=')
    if canonical != value:
        raise ValueError('source reference is not canonical')
    return key, version, payload_hash


def _validate_item(item: Any, *, full: bool) -> None:
    if type(item) is not dict or set(item) != _ITEM_FIELDS | ({'text', 'media_refs'} if full else set()):
        raise ValueError('source evidence fields are invalid')
    if _reference(item['version_ref']) != (item['event_key'], item['version'], item['payload_hash']):
        raise ValueError('source evidence identity does not match reference')
    if item['kind'] not in {'original', 'correction', 'tombstone'}:
        raise ValueError('source evidence kind is invalid')
    for field in ('content_hash', 'payload_hash', 'evidence_hash'):
        if type(item[field]) is not str or not _HEX.fullmatch(item[field]):
            raise ValueError('source evidence hash is invalid')
    for field in ('accepted_at', 'published_at', 'observed_at'):
        if _timestamp(item[field]) != item[field]:
            raise ValueError('source evidence timestamp is not canonical')
    for field in ('endpoint_id', 'publisher_id', 'parser_version'):
        if type(item[field]) is not str or not 1 <= len(item[field]) <= 256:
            raise ValueError('source evidence provenance is invalid')
    url = urlparse(item['source_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('source evidence URL is invalid')
    if item['platform'] not in {'telegram', 'x', 'instagram', 'whatsapp', 'rss'}:
        raise ValueError('source evidence platform is invalid')
    if item['origin_status'] != 'unknown' or item['original_publisher_id'] is not None:
        raise ValueError('unsupported original publisher provenance')
    if type(item['text_truncated']) is not bool or type(item['content_unavailable']) is not bool:
        raise ValueError('source evidence content flags are invalid')
    if full:
        if type(item['text']) is not str or len(item['text']) > 12000 or type(item['media_refs']) is not list or len(item['media_refs']) > 16:
            raise ValueError('source evidence content bounds are invalid')
        if _digest({key: value for key, value in item.items() if key not in {'evidence_hash', 'version_ref'}}) != item['evidence_hash']:
            raise ValueError('source evidence content integrity mismatch')


class SourceEvidenceClient:
    """Capture once, persist the manifest in owner state, then read explicit refs.

    A failed capture is never silently retried because a retry observes a newer
    committed state. Recovery uses the persisted manifest and identical refs.
    No method has intake, claim, publication, delivery, or scheduler authority.
    """
    def __init__(self, base_url: str, token: str, *, timeout: float = 5.0,
                 opener: Callable[..., Any] = urlopen) -> None:
        parsed = urlparse(base_url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError('source evidence Control Plane URL is invalid')
        if type(token) is not str or not token.strip():
            raise ValueError('source evidence reader credential is required')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError('source evidence timeout is invalid')
        self.base_url, self.token, self.timeout, self.opener = base_url.rstrip('/'), token, float(timeout), opener

    def _request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(self.base_url + path, data=json.dumps(payload, separators=(',', ':'), allow_nan=False).encode(),
                          headers={'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json', 'Accept': 'application/json'},
                          method='POST')
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise ControlPlaneUnavailable(f'source evidence Control Plane returned HTTP {exc.code}') from None
        except (OSError, URLError, TimeoutError):
            raise ControlPlaneUnavailable('source evidence Control Plane request failed') from None
        try:
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ValueError('response exceeds size bound')
            result = json.loads(raw)
            if type(result) is not dict:
                raise ValueError('response must be an object')
            return result
        except (ValueError, TypeError, UnicodeError):
            raise ControlPlaneContractError('source evidence response is invalid') from None

    def capture_window(self, previous_cutoff: str, cutoff: str, limit: int = 1000) -> dict[str, Any]:
        lower, upper = _timestamp(previous_cutoff), _timestamp(cutoff)
        if lower >= upper or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('source evidence window or candidate limit is invalid')
        result = self._request('/v1/source-evidence/capture', {'previous_cutoff': lower, 'cutoff': upper, 'limit': limit})
        try:
            if (set(result) != {'api_version', 'previous_cutoff', 'cutoff', 'captured_at', 'capture_status', 'capture_gap_seconds',
                               'history_available_from', 'history_status', 'overflow', 'candidate_limit', 'complete', 'items', 'manifest_hash'}
                    or result['api_version'] != 1 or result['previous_cutoff'] != lower or result['cutoff'] != upper
                    or result['candidate_limit'] != limit or type(result['items']) is not list or len(result['items']) > limit
                    or _digest({key: value for key, value in result.items() if key != 'manifest_hash'}) != result['manifest_hash']):
                raise ValueError('capture manifest integrity mismatch')
            captured = _timestamp(result['captured_at'])
            gap = (datetime.fromisoformat(captured) - datetime.fromisoformat(upper)).total_seconds()
            timing = 'late' if gap > CAPTURE_GRACE_SECONDS else 'early' if gap < -EARLY_TOLERANCE_SECONDS else 'on_time'
            history = result['history_available_from']
            history_status = 'unknown' if history is None else 'available' if _timestamp(history) <= lower else 'unavailable'
            if (result['capture_status'] != timing or result['capture_gap_seconds'] != gap or result['history_status'] != history_status
                    or type(result['overflow']) is not bool or type(result['complete']) is not bool
                    or result['complete'] != (timing == 'on_time' and history_status == 'available' and not result['overflow'])):
                raise ValueError('capture availability metadata is invalid')
            identities = set()
            ordering = []
            for item in result['items']:
                _validate_item(item, full=False)
                if (item['kind'] == 'tombstone' or not lower < item['published_at'] <= upper
                        or item['accepted_at'] > upper or item['observed_at'] > upper or item['event_key'] in identities):
                    raise ValueError('capture contains ineligible or duplicate versions')
                identities.add(item['event_key'])
                ordering.append((item['published_at'], item['event_key'], item['version']))
            if ordering != sorted(ordering):
                raise ValueError('capture order is invalid')
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise ControlPlaneContractError('source evidence capture manifest is invalid') from None
        return result

    def read_versions(self, version_refs: list[str]) -> list[dict[str, Any]]:
        if type(version_refs) is not list or not 1 <= len(version_refs) <= 100:
            raise ValueError('source evidence batch must contain 1 to 100 references')
        identities = [_reference(ref)[:2] for ref in version_refs]
        if len(set(identities)) != len(identities):
            raise ValueError('source evidence batch references must be unique')
        result = self._request('/v1/source-evidence/versions', {'version_refs': version_refs})
        try:
            if (set(result) != {'api_version', 'items'} or result['api_version'] != 1 or type(result['items']) is not list
                    or len(result['items']) != len(version_refs)):
                raise ValueError('source evidence batch is incomplete')
            for ref, item in zip(version_refs, result['items'], strict=True):
                _validate_item(item, full=True)
                if item['version_ref'] != ref:
                    raise ValueError('source evidence batch identity or order changed')
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            raise ControlPlaneContractError('source evidence immutable batch is invalid') from None
        return result['items']
