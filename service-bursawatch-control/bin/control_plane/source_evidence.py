"""Safe immutable evidence views; no work, intake, or delivery authority."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import re
from typing import Any

MAX_CANDIDATES = 1000
MAX_BATCH = 100
MAX_TEXT = 12000
# Capture cannot precede its cutoff, so a capture up to this many seconds after
# it counts as on time. Keep identical to lib-bursawatch-control's client.
CAPTURE_GRACE_SECONDS = 120
# The capture instant is the database server's clock, which can read a few seconds behind the
# host that asks for the capture. A capture this close before the cutoff is still on time.
EARLY_TOLERANCE_SECONDS = 15
_HEX = re.compile(r'[0-9a-f]{64}\Z')


def timestamp(value: object) -> str:
    if type(value) is not str:
        raise ValueError('timestamp must be a timezone-aware ISO string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('timezone missing')
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        raise ValueError('timestamp must be a timezone-aware ISO string') from None


def window(previous_cutoff: str, cutoff: str, limit: int) -> tuple[str, str]:
    lower, upper = timestamp(previous_cutoff), timestamp(cutoff)
    if lower >= upper or type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError('source window or candidate limit is invalid')
    return lower, upper


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def version_ref(key: str, version: int, payload_hash: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([key, version, payload_hash], separators=(',', ':')).encode()).decode().rstrip('=')


def references(values: object) -> list[tuple[str, int, str]]:
    if type(values) is not list or not 1 <= len(values) <= MAX_BATCH or any(type(ref) is not str or len(ref) > 256 for ref in values):
        raise ValueError('immutable version batch is invalid')
    decoded = []
    for ref in values:
        try:
            key, version, payload_hash = json.loads(base64.b64decode(ref + '=' * (-len(ref) % 4), altchars=b'-_', validate=True))
            if not (type(key) is str and _HEX.fullmatch(key) and type(version) is int and version > 0
                    and type(payload_hash) is str and _HEX.fullmatch(payload_hash)
                    and ref == version_ref(key, version, payload_hash)):
                raise ValueError('invalid reference')
        except (ValueError, TypeError, UnicodeError):
            raise ValueError('immutable version reference is invalid') from None
        decoded.append((key, version, payload_hash))
    if len({(key, version) for key, version, _ in decoded}) != len(decoded):
        raise ValueError('immutable version references must be unique')
    return decoded


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        elif tag in {'br', 'p', 'div'} and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _text(envelope: dict[str, Any]) -> tuple[str, bool]:
    payload = envelope['payload']
    parts = []
    if type(payload.get('text')) is str:
        parts.append(payload['text'])
    article = payload.get('article')
    if type(article) is dict:
        parts.extend(article[field] for field in ('source_title', 'source_text') if type(article.get(field)) is str)
    posts = payload.get('thread_posts')
    if type(posts) is not list:
        posts = [payload.get('post')]
    for post in posts:
        if type(post) is dict:
            for field in ('content_html', 'quoted_content_html'):
                if type(post.get(field)) is str:
                    parser = _VisibleText()
                    parser.feed(post[field])
                    parts.append(''.join(parser.parts))
    text = '\n'.join(parts).strip()
    # Stockbit intake already bounds source_text at 12k; equality is uncertain.
    upstream_truncated = type(article) is dict and type(article.get('source_text')) is str and len(article['source_text']) >= MAX_TEXT
    return text[:MAX_TEXT], len(text) > MAX_TEXT or upstream_truncated or payload.get('text_truncated') is True


def evidence(row: dict[str, Any]) -> dict[str, Any]:
    envelope = row['envelope']
    accepted = row['created_at']
    accepted = timestamp(accepted.isoformat() if isinstance(accepted, datetime) else accepted)
    text, truncated = _text(envelope)
    payload_hash = digest(envelope)
    result = {
        'event_key': row['event_key'], 'version': row['version'], 'kind': row['kind'],
        'accepted_at': accepted, 'published_at': timestamp(envelope['published_at']),
        'observed_at': timestamp(envelope['observed_at']),
        **{field: envelope[field] for field in ('endpoint_id', 'publisher_id', 'platform', 'source_url', 'parser_version', 'content_hash')},
        # The current strict envelope carries no verified original publisher.
        'original_publisher_id': None, 'origin_status': 'unknown',
        'payload_hash': payload_hash, 'text': text, 'text_truncated': truncated,
        'content_unavailable': not bool(text), 'media_refs': envelope['media_refs'],
    }
    result['evidence_hash'] = digest(result)
    result['version_ref'] = version_ref(row['event_key'], row['version'], payload_hash)
    return result


def manifest(rows: list[dict[str, Any]], lower: str, upper: str, limit: int,
             captured_at: datetime, history_available_from: str | None) -> dict[str, Any]:
    captured = captured_at.astimezone(timezone.utc).isoformat()
    gap = (captured_at - datetime.fromisoformat(upper)).total_seconds()
    capture_status = 'late' if gap > CAPTURE_GRACE_SECONDS else 'early' if gap < -EARLY_TOLERANCE_SECONDS else 'on_time'
    history = timestamp(history_available_from) if history_available_from is not None else None
    history_status = 'unknown' if history is None else 'available' if history <= lower else 'unavailable'
    items = []
    for row in rows[:limit]:
        record = evidence(row)
        items.append({key: value for key, value in record.items() if key not in {'text', 'media_refs'}})
    result = {
        'api_version': 1, 'previous_cutoff': lower, 'cutoff': upper,
        'captured_at': captured, 'capture_status': capture_status, 'capture_gap_seconds': gap,
        'history_available_from': history, 'history_status': history_status,
        'overflow': len(rows) > limit, 'candidate_limit': limit,
        'complete': capture_status == 'on_time' and history_status == 'available' and len(rows) <= limit,
        'items': items,
    }
    result['manifest_hash'] = digest(result)
    return result
