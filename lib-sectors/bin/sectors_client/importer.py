"""Offline import of the retained close-history wrapper. Never starts bootstrap."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from .cache import validate_payload
from .models import ORIGIN, RequestIdentity, ValidationError, instant, session_date


@dataclass(frozen=True)
class ImportReport:
    pages_imported: int
    complete_sessions: tuple
    partial_sessions: dict
    missing_sessions: tuple
    source_digest: str
    ignored_artifacts: int = 0


def import_retained(path, store, *, imported_at):
    """Import explicit caller path using conservative availability at import time.

    A directory selects only the documented retained history wrapper. Other
    diagnostic/membership/cap files are not silently treated as close evidence.
    Imported pages add no billing ledger entries and make no balance claim.
    """
    path = Path(path)
    ignored = 0
    if path.is_dir():
        ignored = max(0, len(list(path.glob('*.json'))) - 1)
        path = path / 'bursawatch-preview-history-20261005.json'
    if path.is_symlink():
        raise ValidationError('retained history input must not be a symlink')
    try:
        with path.open('rb') as stream:
            raw = stream.read(100_000_001)
        if len(raw) > 100_000_000:
            raise ValidationError('retained history exceeds import size bound')
        data = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        raise ValidationError('retained history input is unavailable or invalid') from None
    imported_at = instant(imported_at)
    try:
        if data.get('origin', ORIGIN) != ORIGIN:
            raise ValueError
        started = instant(data['started_at'])
        if started > imported_at:
            raise ValueError
        dates = data['dates']
        sessions = data['sessions']
        declared = data['complete_dates']
        if not isinstance(dates, list) or not isinstance(sessions, dict) or not isinstance(declared, list):
            raise ValueError
        for value in dates:
            if session_date(value) > started.date():
                raise ValueError
        if len(set(dates)) != len(dates) or set(sessions) - set(dates) or len(set(declared)) != len(declared):
            raise ValueError
        prepared, complete, partial = [], [], {}
        for session, pages in sessions.items():
            session_date(session)
            if not isinstance(pages, list) or not pages:
                raise ValueError
            total, limit = None, None
            offsets, symbols = set(), set()
            for page in pages:
                p = page['pagination']
                request = RequestIdentity('/v2/close/', {'date':session,'limit':p['limit'],'offset':p['offset']})
                validate_payload(request, page)
                if total is not None and (p['total_count'] != total or p['limit'] != limit):
                    raise ValueError
                total, limit = p['total_count'], p['limit']
                if p['offset'] in offsets or p['offset'] % limit:
                    raise ValueError
                offsets.add(p['offset'])
                for row in page['results']:
                    if row['symbol'] in symbols:
                        raise ValueError
                    symbols.add(row['symbol'])
                prepared.append((request, page))
            missing = tuple(x for x in range(0, total, limit) if x not in offsets)
            if not missing and len(symbols) == total:
                complete.append(session)
            else:
                partial[session] = missing
        if set(declared) != set(complete):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValidationError('retained history provenance or pagination is inconsistent') from None
    inserted = 0
    # All validation precedes the transaction. Invalid files import no pages.
    with store.connection(write=True) as db:
        for request, page in prepared:
            inserted += store._save(db, request, page, imported_at.isoformat(), 'retained-local-close-pages', True)
    return ImportReport(inserted, tuple(sorted(complete)), partial,
                        tuple(sorted(set(dates) - set(sessions))),
                        hashlib.sha256(raw).hexdigest(), ignored)
