"""Frozen Source Inbox research corpus, owned independently of source capture."""
from collections import Counter
from datetime import datetime
import re
from typing import Protocol
from .calendar import aware
from .store import FreezeConflict, digest, stamp


IHSG_ALIASES = re.compile(r'\b(?:IHSG|JKSE|JCI|Jakarta\s+Composite\s+Index|IDX\s+Composite)\b', re.IGNORECASE)


class SourceReader(Protocol):
    """Implemented by lib-bursawatch-control's stdlib SourceEvidenceClient."""
    def capture_window(self, previous_cutoff: str, cutoff: str, limit: int = 1000) -> dict: ...
    def read_versions(self, version_refs: list[str]) -> list[dict]: ...


def _valid_media(entries):
    if not isinstance(entries, list) or len(entries) > 16:
        return False
    seen, total = set(), 0
    types = {'image': {'image/jpeg','image/png','image/gif','image/webp','image/avif'},
             'video': {'video/mp4','video/quicktime','video/webm'},
             'document': {'application/pdf','application/zip','text/plain'},
             'audio': {'audio/mpeg','audio/wav','audio/ogg','audio/flac','audio/mp4'}}
    for entry in entries:
        if (type(entry) is not dict or set(entry) != {'ref','sha256','kind','content_type','size_bytes','filename','durable'}
                or entry['durable'] is not True or type(entry['ref']) is not str
                or re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', entry['ref']) is None or entry['ref'] in seen
                or type(entry['sha256']) is not str or re.fullmatch('[0-9a-f]{64}', entry['sha256']) is None
                or type(entry['kind']) is not str or entry['kind'] not in {'image','video','document','audio'}
                or type(entry['content_type']) is not str or entry['content_type'] not in types[entry['kind']]
                or type(entry['filename']) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',entry['filename']) is None
                or type(entry['size_bytes']) is not int or not 0 < entry['size_bytes'] <= 8*1024*1024):
            return False
        seen.add(entry['ref'])
        total += entry['size_bytes']
    return total <= 25*1024*1024


def select_evidence(rows: list[dict]) -> dict:
    """Deterministic, extractive corpus with shared publisher caps across routes.

    No copied/unknown-origin record establishes an independent opinion. Selection
    omissions from the final 30-item bound differ from upstream corpus overflow.
    """
    selected, omissions, reasons = [], Counter(), set()
    publishers, stories = Counter(), set()
    def recent_key(row):
        value = row.get('published_at') or row['observed_at']
        instant = aware(datetime.fromisoformat(value.replace('Z', '+00:00')))
        return (-instant.timestamp(), row['event_key'], row['version_ref'])

    for row in sorted(rows, key=recent_key):
        if row.get('kind') == 'tombstone':
            omissions['tombstone'] += 1
            continue
        text = row.get('text')
        if row.get('content_unavailable') or not isinstance(text, str) or not text.strip():
            # A photo-only or empty item has nothing to quote. It is omitted and counted, and it
            # does not stop the outlook from using the items that do carry text.
            omissions['content_unavailable'] += 1
            continue
        if IHSG_ALIASES.search(text) is None:
            omissions['irrelevant'] += 1
            continue
        if row.get('text_truncated'):
            reasons.add('truncated_content')
        normalized = ' '.join(text.casefold().split())
        keys = {('text', normalized), ('content_hash', row.get('content_hash'))}
        if keys & stories:
            omissions['copied_story'] += 1
            continue
        # Count copies even when the representative is omitted by publisher/total caps.
        stories.update(keys)
        verified = row.get('origin_status') == 'verified' and bool(row.get('original_publisher_id'))
        publisher = row.get('original_publisher_id') if verified else row.get('publisher_id')
        if not publisher:
            publisher = 'unknown'
            reasons.add('missing_publisher')
        if publishers[publisher] >= 3:
            omissions['publisher_cap'] += 1
            continue
        if len(selected) >= 30:
            omissions['evidence_cap'] += 1
            continue
        media = row.get('media_refs', [])
        if not _valid_media(media):
            reasons.add('invalid_media_metadata')
            media = []
        selected.append({
            'evidence_id': row['evidence_hash'], 'version_ref': row['version_ref'],
            'evidence_hash': row['evidence_hash'], 'event_key': row['event_key'], 'version': row['version'],
            'publisher_id': publisher, 'collecting_publisher_id': row.get('publisher_id'),
            'original_publisher_id': row.get('original_publisher_id') if verified else None,
            'origin_status': 'verified' if verified else 'unknown', 'independent_opinion': False,
            'platform': row['platform'], 'endpoint_id': row['endpoint_id'], 'source_url': row['source_url'],
            'accepted_at': row['accepted_at'], 'published_at': row['published_at'], 'observed_at': row['observed_at'],
            'text': text, 'text_truncated': row.get('text_truncated', False), 'media_refs': media,
        })
        publishers[publisher] += 1
    return {'items': selected, 'omissions': dict(omissions), 'degraded_reasons': sorted(reasons)}


PARTIAL_HISTORY_MIN_HOURS = 6


def _partial_history_span(manifest, cutoff):
    """Hours of source history before the cutoff when the store began inside the window.

    While the store holds less than a full window, a long enough partial window is accepted
    and noted. A store that began only just before the cutoff is still treated as incomplete.
    """
    if manifest.get('history_status') != 'unavailable' or not manifest.get('history_available_from'):
        return None
    try:
        start = aware(datetime.fromisoformat(manifest['history_available_from'].replace('Z', '+00:00')))
        hours = (aware(datetime.fromisoformat(cutoff.replace('Z', '+00:00'))) - start).total_seconds() / 3600
    except (ValueError, TypeError, AttributeError):
        return None
    return hours if hours >= PARTIAL_HISTORY_MIN_HOURS else None


def freeze_source_evidence(store, run_id: str, client: SourceReader, *, previous_cutoff: str,
                           lease, now: datetime):
    """Persist capture first; recover only its immutable versions, never recapture.

    Integrity/transport gaps freeze an honest facts-only outcome. The original
    source_manifest remains durable even if a read fails after process recovery.
    """
    run = store.get_run(run_id)
    previous = stamp(aware(datetime.fromisoformat(previous_cutoff.replace('Z','+00:00'))))
    if previous >= run.freeze_at:
        raise ValueError('previous verified session cutoff must precede current cutoff')
    frozen = store.get_frozen(run_id, 'source_manifest')
    if frozen is None:
        # Capture is not idempotent: even an ambiguous transport failure must
        # not trigger a new database snapshot with a different visible corpus.
        try:
            manifest = client.capture_window(previous, run.freeze_at)
        except Exception:
            manifest = {'status':'unavailable', 'previous_cutoff':previous, 'cutoff':run.freeze_at}
        frozen = store.freeze(run_id, 'source_manifest', manifest, lease=lease, now=now)
    manifest = frozen.payload
    if manifest.get('previous_cutoff') != previous or manifest.get('cutoff') != run.freeze_at:
        raise FreezeConflict('saved source manifest belongs to a different session window')
    saved = store.get_frozen(run_id, 'evidence')
    if saved is not None:
        if saved.dependencies != {'source_manifest': frozen.digest}:
            raise FreezeConflict('saved evidence dependency does not match source manifest')
        return saved
    reasons = set()
    notes = []
    rows = []
    if manifest.get('status') == 'unavailable':
        reasons.add('capture_unavailable')
    else:
        if manifest.get('capture_status') != 'on_time':
            reasons.add(manifest.get('capture_status','unknown') + '_capture')
        if manifest.get('overflow'):
            reasons.add('corpus_overflow')
        if manifest.get('history_status') != 'available':
            span = _partial_history_span(manifest, run.freeze_at)
            if span is None:
                reasons.add('history_' + manifest.get('history_status','unknown'))
            else:
                notes.append('history_partial_hours:' + format(span, '.1f'))
        try:
            if digest({k:v for k,v in manifest.items() if k != 'manifest_hash'}) != manifest['manifest_hash']:
                raise ValueError('manifest hash changed')
            items = manifest['items']
            for offset in range(0, len(items), 100):
                expected = items[offset:offset+100]
                batch = client.read_versions([row['version_ref'] for row in expected])
                if len(batch) != len(expected):
                    raise ValueError('immutable version missing')
                for identity, row in zip(expected, batch, strict=True):
                    if ({k:v for k,v in row.items() if k not in {'text','media_refs'}} != identity
                            or row['kind'] == 'tombstone'
                            or digest({k:v for k,v in row.items() if k not in {'evidence_hash','version_ref'}}) != identity['evidence_hash']):
                        raise ValueError('immutable evidence does not match saved manifest')
                rows.extend(batch)
        except Exception:
            reasons.add('immutable_versions_unavailable')
            rows = []
    selection = select_evidence(rows)
    reasons.update(selection['degraded_reasons'])
    payload = dict(selection, api_version=1, previous_cutoff=previous, cutoff=run.freeze_at,
                   capture_status=manifest.get('capture_status','unavailable'),
                   capture_gap_seconds=manifest.get('capture_gap_seconds'),
                   history_status=manifest.get('history_status','unknown'), overflow=manifest.get('overflow'),
                   facts_only=bool(reasons), degraded_reasons=sorted(reasons), notes=notes)
    return store.freeze(run_id, 'evidence', payload, lease=lease, now=now,
                        dependencies={'source_manifest': frozen.digest})
