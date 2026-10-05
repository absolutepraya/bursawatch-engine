"""Validated provider identities and safe failure types. No import-time IO."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import re
from urllib.parse import urlencode

ORIGIN = 'https://api.sectors.app'


class SectorsError(Exception):
    """Messages contain only library-controlled text, never response bodies."""


class ValidationError(SectorsError):
    pass


class CacheMiss(SectorsError):
    pass


class BudgetDenied(SectorsError):
    pass


class RequestInFlight(SectorsError):
    pass


class UncertainOutcome(SectorsError):
    pass


class AuthenticationFailure(SectorsError):
    pass


class AllowanceExhausted(SectorsError):
    pass


class Throttled(SectorsError):
    def __init__(self, retry_after=None):
        super().__init__('provider temporarily throttled request')
        self.retry_after = retry_after


class RetryExhausted(SectorsError):
    pass


class TransportFailure(SectorsError):
    pass


def session_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValidationError('invalid session date')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError('invalid session date') from None


def instant(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValidationError('invalid timestamp') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError('timestamp requires timezone')
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, init=False)
class RequestIdentity:
    path: str
    query: tuple

    def __init__(self, path, query=None):
        patterns = [r'/v2/close/', r'/v2/companies/', r'/v2/company/screener/',
                    r'/v2/stock-screener/', r'/v2/index-daily/ihsg/', r'/v2/corporate-actions/',
                    r'/v2/daily/[A-Z][A-Z0-9]{0,11}/',
                    r'/v2/company/corporate-actions/[A-Z][A-Z0-9]{0,11}/']
        if not isinstance(path, str) or not any(re.fullmatch(p, path) for p in patterns):
            raise ValidationError('unsupported provider path')
        q = dict(query or {})
        if set(q) - {'date','start','end','offset','limit','sector','sub_sector','min_market_cap','max_market_cap','filter','where','order_by','include_query_values','type'}:
            raise ValidationError('unsupported query field')
        for name in ('date', 'start', 'end'):
            if name in q:
                session_date(q[name])
        if 'start' in q and 'end' in q and q['start'] > q['end']:
            raise ValidationError('date range is reversed')
        for name in ('offset', 'limit'):
            if name in q and (type(q[name]) is not int or q[name] < (1 if name == 'limit' else 0) or q[name] > 1_000_000):
                raise ValidationError('invalid pagination value')
        if 'include_query_values' in q:
            if type(q['include_query_values']) is not bool:
                raise ValidationError('invalid query-values flag')
            q['include_query_values'] = 'true' if q['include_query_values'] else 'false'
        if path == '/v2/corporate-actions/':
            if q.get('type') != 'stock_split' or 'start' not in q or 'end' not in q:
                raise ValidationError('split calendar requires explicit type and date range')
            if (session_date(q['end']) - session_date(q['start'])).days > 89:
                raise ValidationError('split calendar exceeds 90-day range')
        for name, value in q.items():
            if not isinstance(value, (str, int, float)) or isinstance(value, bool) or len(str(value)) > 200:
                raise ValidationError('invalid query value')
        if path == '/v2/close/' and 'date' not in q:
            raise ValidationError('close request requires a session date')
        object.__setattr__(self, 'path', path)
        object.__setattr__(self, 'query', tuple(sorted(q.items())))

    @property
    def url(self):
        return ORIGIN + self.path + ('?' + urlencode(self.query) if self.query else '')

    @property
    def key(self):
        return hashlib.sha256(self.url.encode()).hexdigest()


@dataclass(frozen=True)
class CachedResponse:
    identity: RequestIdentity
    payload: object
    available_at: datetime
    provenance: str
    imported: bool = False


@dataclass(frozen=True)
class SessionResult:
    session: str
    rows: tuple
    pages: tuple
    total: int
    complete: bool
    missing_offsets: tuple = ()
