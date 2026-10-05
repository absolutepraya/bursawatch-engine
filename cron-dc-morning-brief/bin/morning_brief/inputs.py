"""Offline typed membership/cap inputs and conservative price compatibility."""
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import io
import json
import math
from pathlib import Path
import re
from zoneinfo import ZoneInfo
from .calendar import SessionCalendar, aware, iso_date


def symbol(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z]{4}(?:\.JK)?', value):
        raise ValueError('invalid IDX symbol')
    return value.removesuffix('.JK')


def positive(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value <= 0:
        raise ValueError('finite positive value required')
    return float(value)


@dataclass(frozen=True)
class Provenance:
    source_url: str
    digest: str
    method: str
    reference: str


@dataclass(frozen=True)
class MembershipSnapshot:
    version: str
    groups: dict[str, tuple[str, ...]]
    provenance: Provenance
    collected_at: datetime | None = None
    ownership_as_of: date | None = None


@dataclass(frozen=True)
class CapSnapshot:
    identity: str
    collected_at: datetime
    effective_date: date | None
    values: dict[str, float]
    provenance: Provenance

    def __post_init__(self):
        if not self.identity: raise ValueError('cap identity required')
        aware(self.collected_at)


@dataclass(frozen=True)
class PriceSeries:
    symbol: str
    closes: dict[str, float]
    basis: str
    version: str
    trading_eligible: bool


@dataclass(frozen=True)
class ActionDecision:
    symbol: str
    identity: str
    status: str
    treatment: str
    ratio: float | None
    evidence: str
    effective_session: str | None = None


def _read(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def load_konglo_csv(path, *, version: str, source_url: str) -> MembershipSnapshot:
    raw = Path(path).read_bytes()
    groups = {}
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if reader.fieldnames != ['konglo', 'ticker', 'size_bucket'] or not version or not source_url:
        raise ValueError('versioned supplied konglo CSV required')
    for row in reader:
        name = row['konglo']
        ticker = symbol(row['ticker'])
        if not name or not row['size_bucket'] or ticker in groups.setdefault(name, set()):
            raise ValueError('invalid or duplicate within-group CSV row')
        groups[name].add(ticker)
    if not groups: raise ValueError('empty membership')
    return MembershipSnapshot(version, {k: tuple(sorted(v)) for k, v in sorted(groups.items())},
                              Provenance(source_url, hashlib.sha256(raw).hexdigest(), 'supplied-overlapping-konglo-csv', version))


def load_sector_membership(path, *, version: str, official_check_reference: str, source_url: str) -> MembershipSnapshot:
    p, digest = _read(path)
    summary = p['summary']
    rows = p['memberships']
    if (not version or not official_check_reference or not source_url or summary.get('failure') is not None
            or summary.get('complete_for_filter') is not True or summary.get('filter') != 'sector IS NOT NULL'
            or summary['total_count'] != len(rows) or summary['rows_collected'] != len(rows)):
        raise ValueError('complete membership with official-first provenance required')
    groups, seen = {}, set()
    for row in rows:
        ticker = symbol(row['symbol']); name = row['sector']
        if not isinstance(name, str) or not name or ticker in seen: raise ValueError('invalid membership row')
        seen.add(ticker); groups.setdefault(name, []).append(ticker)
    if summary.get('counts') != {k: len(v) for k, v in groups.items()}: raise ValueError('membership totals mismatch')
    return MembershipSnapshot(version, {k: tuple(sorted(v)) for k, v in sorted(groups.items())},
                              Provenance(source_url, digest, 'official-first/sectors-idx-ic-fallback', official_check_reference),
                              aware(datetime.fromisoformat(summary['checked_at'])))


def load_cap_snapshot(path, *, identity: str, source_url: str) -> CapSnapshot:
    p, digest = _read(path)
    if p.get('failure') is not None or not source_url: raise ValueError('failed cap collection')
    started = aware(datetime.fromisoformat(p['checked_at']))
    completed = aware(datetime.fromisoformat(p['completed_at']))
    if started > completed: raise ValueError('invalid collection timestamps')
    pages = [(int(k.removeprefix('caps_')),v) for k,v in p['data'].items() if k.startswith('caps_')]
    pages.sort(key=lambda pair: pair[0])
    values, offset, total = {}, 0, None
    for key_offset,page in pages:
        meta, rows = page['pagination'], page['results']
        page_total, limit = meta['total_count'], meta['limit']
        if (type(page_total) is not int or page_total <= 0 or type(limit) is not int or limit <= 0
                or key_offset != offset or meta['offset'] != offset or meta['showing'] != len(rows)
                or len(rows) != min(limit, page_total-offset) or (total is not None and total != page_total)):
            raise ValueError('invalid cap pagination')
        total = page_total
        next_offset = offset + len(rows)
        has_next = next_offset < total
        if meta['has_next'] is not has_next or meta.get('next_offset') != (next_offset if has_next else None):
            raise ValueError('cap continuation mismatch')
        for row in rows:
            ticker = symbol(row['symbol'])
            if ticker in values: raise ValueError('duplicate cap symbol')
            values[ticker] = positive(row['query_values']['market_cap'])
        offset = next_offset
    if not pages or total != len(values): raise ValueError('partial cap snapshot')
    # Provider companies screener has no authoritative underlying cap date.
    return CapSnapshot(identity, completed, None, values, Provenance(source_url,digest,'sectors-companies-cap/effective-date-unverified',identity))


def cap_refresh_due(session: date, calendar: SessionCalendar) -> bool:
    return calendar.is_session(session) and session == calendar.first_session_of_week(session)


def cap_status(snapshot: CapSnapshot, session: date, calendar: SessionCalendar) -> str:
    if not calendar.is_session(session): raise ValueError('cap assessment needs verified session')
    collected = snapshot.collected_at.astimezone(ZoneInfo('Asia/Jakarta')).date()
    if collected > session: return 'future'
    first = calendar.first_session_of_week(session)
    if collected >= first: return 'current_week'
    previous = calendar.first_session_of_week(first - timedelta(days=7))
    return 'extra_week' if collected >= previous else 'expired'


def compatible_closes(series: PriceSeries, actions: list[ActionDecision]) -> dict[str,float]:
    symbol(series.symbol)
    if not series.version or series.trading_eligible is not True or series.basis not in {'raw','split_adjusted'}:
        raise ValueError('unverified trading eligibility or price basis')
    result = {iso_date(d).isoformat():positive(v) for d,v in series.closes.items()}
    seen, applied_splits = set(), set()
    for action in actions:
        if action.symbol != series.symbol: continue
        if not action.identity or action.identity in seen or action.status != 'resolved' or not action.evidence:
            raise ValueError('unresolved/duplicate corporate action')
        seen.add(action.identity)
        if action.treatment == 'exclude_dividend': continue
        if action.treatment == 'already_adjusted' and series.basis == 'split_adjusted': continue
        if action.treatment == 'adjust_raw' and series.basis == 'raw' and action.effective_session:
            ratio = positive(action.ratio)
            effective = iso_date(action.effective_session).isoformat()
            if effective in applied_splits:
                raise ValueError('duplicate split effective session')
            applied_splits.add(effective)
            result = {d: v/ratio if d < effective else v for d,v in result.items()}
        else:
            raise ValueError('incompatible or unknown action treatment')
    if series.basis == 'raw' and not any(a.symbol==series.symbol and a.treatment=='adjust_raw' for a in actions):
        raise ValueError('raw series lacks verified adjustment compatibility')
    return result


class InputUnavailable(ValueError):
    """Explicit rotation omission, with no synthetic or provider fallback."""


@dataclass(frozen=True)
class NumericalInputs:
    calendar: SessionCalendar
    membership: MembershipSnapshot
    caps: CapSnapshot
    prices: dict[str, PriceSeries]
    benchmark: dict[str, float]
    sessions: tuple[date, ...]
    actions: tuple[ActionDecision, ...]
    freeze_at: datetime
    cap_collection_status: str

    @property
    def provenance(self) -> dict:
        return dict(calendar=self.calendar.version, amendment=self.calendar.amendment,
                    calendar_digest=self.calendar.import_digest,
                    calendar_source_digest=self.calendar.source_digest,
                    calendar_amendment_checked_at=self.calendar.amendment_checked_at.isoformat(),
                    membership=self.membership.version, membership_digest=self.membership.provenance.digest,
                    membership_method=self.membership.provenance.method,
                    membership_reference=self.membership.provenance.reference,
                    cap_collection_status=self.cap_collection_status,
                    freeze_at=self.freeze_at.isoformat())


def prepare_numerical_inputs(calendar: SessionCalendar, membership: MembershipSnapshot, caps: CapSnapshot,
                             prices: dict[str, PriceSeries], benchmark: dict[str, float], *,
                             through: date, freeze_at: datetime,
                             actions: tuple[ActionDecision, ...] = ()) -> NumericalInputs:
    """Validate explicit imported inputs; never fetch or substitute missing market data.

    Price trading eligibility and action evidence must be supplied by the owner;
    positive bulk close rows do not provide those facts by themselves.
    """
    aware(freeze_at)
    try:
        sessions = calendar.last_sessions(through,18)
        status = cap_status(caps,through,calendar)
    except ValueError as exc:
        raise InputUnavailable(str(exc)) from None
    if (caps.collected_at > freeze_at or status not in {'current_week','extra_week'}
            or (membership.collected_at is not None and membership.collected_at > freeze_at)
            or not membership.version or not membership.groups
            or not membership.provenance.digest or not membership.provenance.reference):
        raise InputUnavailable('unavailable cap or membership snapshot at frozen cutoff')
    if through > freeze_at.astimezone(ZoneInfo('Asia/Jakarta')).date():
        raise InputUnavailable('future closing session')
    try:
        aligned_index = {s.isoformat():positive(benchmark[s.isoformat()]) for s in sessions}
    except (ValueError,KeyError):
        raise InputUnavailable('missing aligned benchmark session') from None
    return NumericalInputs(calendar,membership,caps,dict(prices),aligned_index,sessions,tuple(actions),freeze_at,status)
