"""Imported, explicitly verified authoritative session snapshots, never inferred weekdays."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path


def aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware timestamp required')
    return value


def iso_date(value: str) -> date:
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise ValueError('canonical ISO session required')
    return result


def restored_calendar(payload):
    """Restore only an already frozen, checksum-bound owner snapshot."""
    return SessionCalendar(**{**payload,
        'amendment_checked_at': datetime.fromisoformat(payload['amendment_checked_at']),
        'valid_from': date.fromisoformat(payload['valid_from']),
        'valid_through': date.fromisoformat(payload['valid_through']),
        'sessions': tuple(date.fromisoformat(s) for s in payload['sessions'])})


@dataclass(frozen=True)
class SessionCalendar:
    version: str
    amendment: str
    authority: str
    source_url: str
    source_digest: str
    import_digest: str
    amendment_checked_at: datetime
    valid_from: date
    valid_through: date
    sessions: tuple[date, ...]

    @classmethod
    def from_file(cls, path: Path, *, expected_version: str, expected_amendment: str, as_of: datetime):
        raw = Path(path).read_bytes()
        p = json.loads(raw)
        checked = aware(datetime.fromisoformat(p['amendment_checked_at']))
        as_of = aware(as_of)
        if (p.get('verified') is not True or p.get('authority') != 'IDX'
                or p.get('version') != expected_version or p.get('amendment') != expected_amendment
                or not expected_version or not expected_amendment or checked > as_of
                or as_of - checked > timedelta(days=7)):
            raise ValueError('calendar verification/amendment check unavailable or stale')
        digest = p['source_digest']
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest) or not p['source_url']:
            raise ValueError('calendar provenance required')
        start, end = iso_date(p['valid_from']), iso_date(p['valid_through'])
        sessions = tuple(iso_date(s) for s in p['sessions'])
        if start > end or not sessions or tuple(sorted(set(sessions))) != sessions or any(s < start or s > end for s in sessions):
            raise ValueError('invalid calendar range or session order')
        if not start <= as_of.date() <= end:
            raise ValueError('calendar does not cover amendment check run')
        return cls(expected_version, expected_amendment, p['authority'], p['source_url'], digest,
                   hashlib.sha256(raw).hexdigest(), checked, start, end, sessions)

    def _check(self, session: date):
        if not self.valid_from <= session <= self.valid_through:
            raise ValueError('session outside verified calendar coverage')

    def is_session(self, session: date) -> bool:
        self._check(session)
        return session in self.sessions

    def first_session_of_week(self, session: date) -> date:
        self._check(session)
        monday = session - timedelta(days=session.weekday())
        if monday < self.valid_from or monday + timedelta(days=6) > self.valid_through:
            raise ValueError('calendar must cover entire week')
        candidates = [s for s in self.sessions if monday <= s <= monday + timedelta(days=6)]
        if not candidates:
            raise ValueError('verified week has no sessions')
        return candidates[0]

    def last_sessions(self, through: date, count: int) -> tuple[date, ...]:
        if type(count) is not int or count <= 0 or not self.is_session(through):
            raise ValueError('positive window ending on verified session required')
        candidates = tuple(s for s in self.sessions if s <= through)
        if len(candidates) < count:
            raise ValueError('insufficient verified session history')
        return candidates[-count:]
