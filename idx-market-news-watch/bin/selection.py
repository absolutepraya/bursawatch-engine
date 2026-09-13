from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from domain import Classification, CompanyCandidate, Destination, EventClass, Provider, SourceKind, Tier, tier_for_event_class
from state import StateBlockedError, save_state


_WIB = ZoneInfo("Asia/Jakarta")
_PRE_MARKET_TIME = time(8, 30)
_AFTER_CLOSE_TIME = time(16, 30)
_MAX_DIGEST_CANDIDATES = 10
_DUPLICATE_INTERVAL = timedelta(hours=24)
_SAME_PROVIDER_DUPLICATE_INTERVAL = timedelta(days=7)
_SOURCE_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SOURCE_STOP_WORDS = frozenset(
    "akan anak atau bagi bahwa dalam dari dan dengan ini itu kepada karena "
    "masih melalui menjadi pada para perseroan perusahaan sebagai serta "
    "tersebut tidak untuk yang telah dapat lebih sekitar hingga oleh dalam "
    "sebuah satu dua tiga empat lima tahun juta miliar triliun".split()
)
_TIER_TWO_EVENT_WEIGHTS = {
    EventClass.QUANTIFIED_OPERATIONAL_EXECUTION: 0,
    EventClass.OTHER_COMPANY_OPERATION: 1,
    EventClass.ROUTINE_STATUS: 2,
}


def _normalize_fact(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must contain text")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} must contain nonempty text")
    return normalized


def _normalize_dedupe_fact(value: object, field_name: str) -> str:
    return _normalize_fact(value, field_name).casefold()


def _source_tokens(item: SelectionCandidate) -> frozenset[str]:
    return frozenset(
        token
        for token in _SOURCE_TOKEN_PATTERN.findall(item.candidate.source_text.casefold())
        if len(token) >= 3 and token not in _SOURCE_STOP_WORDS
    )


def _strong_source_overlap(left: SelectionCandidate, right: SelectionCandidate) -> bool:
    left_tokens = _source_tokens(left)
    right_tokens = _source_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap >= 5 and overlap / min(len(left_tokens), len(right_tokens)) >= 0.4


def _normalize_fact_sequence(
    value: Sequence[str], field_name: str, normalizer=_normalize_fact
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence of text")
    normalized = tuple(normalizer(item, field_name) for item in value)
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    """Validated classification data needed by deterministic selection."""

    candidate: CompanyCandidate
    event_class: EventClass
    ranking_band: int
    material_facts: tuple[str, ...]
    dedupe_facts: tuple[str, ...]
    summary: str = ""
    title: str = ""
    route: Destination = Destination.ID_STOCKS_NEWS

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, CompanyCandidate):
            raise ValueError("candidate must be a CompanyCandidate")
        if not isinstance(self.event_class, EventClass):
            raise ValueError("event_class must be an EventClass")
        if not isinstance(self.route, Destination):
            raise ValueError("route must be a Destination")
        if (
            not isinstance(self.ranking_band, int)
            or isinstance(self.ranking_band, bool)
            or not 1 <= self.ranking_band <= 5
        ):
            raise ValueError("ranking_band must be an integer from 1 through 5")
        object.__setattr__(self, "material_facts", _normalize_fact_sequence(self.material_facts, "material_facts"))
        object.__setattr__(
            self,
            "dedupe_facts",
            _normalize_fact_sequence(self.dedupe_facts, "dedupe_facts", _normalize_dedupe_fact),
        )
        summary = " ".join(self.summary.split())
        if not summary:
            summary = " ".join(self.material_facts)
        object.__setattr__(self, "summary", summary)
        title = " ".join(self.title.split())
        object.__setattr__(self, "title", title)

    @classmethod
    def from_validated_submission(
        cls, classification: Classification, submission: Mapping[str, object]
    ) -> SelectionCandidate:
        """Adapt the validated agent payload without reclassifying or contacting a model."""
        if not isinstance(classification, Classification):
            raise ValueError("classification must be a Classification")
        if not isinstance(submission, Mapping):
            raise ValueError("submission must be a mapping")
        return cls(
            candidate=classification.candidate,
            event_class=classification.event_class,
            ranking_band=submission["ranking_band"],  # type: ignore[arg-type]
            material_facts=submission["material_facts"],  # type: ignore[arg-type]
            dedupe_facts=submission["dedupe_facts"],  # type: ignore[arg-type]
            summary=submission.get("summary", ""),  # type: ignore[arg-type]
            title=submission.get("title", ""),  # type: ignore[arg-type]
            route=Destination(submission.get("route", Destination.ID_STOCKS_NEWS.value)),
        )

    @property
    def key(self) -> str:
        return self.candidate.key

    @property
    def provider(self) -> Provider:
        return self.candidate.provider

    @property
    def ticker(self) -> str | None:
        return self.candidate.ticker

    @property
    def published_at(self) -> datetime:
        return self.candidate.published_at

    @property
    def material_fact_count(self) -> int:
        return len(set(self.material_facts))

    @property
    def normalized_dedupe_facts(self) -> frozenset[str]:
        return frozenset(self.dedupe_facts)


@dataclass(frozen=True, slots=True)
class DigestWindow:
    kind: str
    start: datetime
    end: datetime


def is_confident_duplicate(left: SelectionCandidate, right: SelectionCandidate) -> bool:
    """Return true only for a same-event duplicate with strong source evidence."""
    if not isinstance(left, SelectionCandidate) or not isinstance(right, SelectionCandidate):
        raise ValueError("duplicate checks require SelectionCandidate values")
    if (
        left.route is not right.route
        or left.ticker is None
        or right.ticker is None
        or left.ticker != right.ticker
        or left.event_class is not right.event_class
    ):
        return False
    interval = _SAME_PROVIDER_DUPLICATE_INTERVAL if left.provider is right.provider else _DUPLICATE_INTERVAL
    if abs(left.published_at - right.published_at) > interval:
        return False
    if len(left.normalized_dedupe_facts & right.normalized_dedupe_facts) >= 2:
        return True
    return left.provider is right.provider and _strong_source_overlap(left, right)


def _record_for(state: dict[str, object], item: SelectionCandidate) -> dict[str, object]:
    candidates = state.get("candidates")
    if not isinstance(candidates, dict):
        raise StateBlockedError("malformed state: candidates must be an object")
    record = candidates.get(item.key)
    if not isinstance(record, dict):
        raise StateBlockedError(f"candidate {item.key!r} is not in durable state")
    if record.get("classification") != item.event_class.value:
        raise StateBlockedError(f"candidate {item.key!r} classification does not match selection data")
    return record


def _selection_candidate_from_record(key: str, record: Mapping[str, object]) -> SelectionCandidate:
    candidate_payload = record.get("candidate")
    selection_data = record.get("selection")
    classification = record.get("classification")
    if not isinstance(candidate_payload, Mapping) or not isinstance(selection_data, Mapping):
        raise StateBlockedError(f"candidate {key!r} has no durable selection data")
    try:
        candidate = CompanyCandidate(
            provider=Provider(candidate_payload["provider"]),
            source_message_id=candidate_payload["source_message_id"],
            ticker=candidate_payload["ticker"],
            source_kind=SourceKind(candidate_payload["source_kind"]),
            published_at=datetime.fromisoformat(candidate_payload["published_at"]),
            source_text=candidate_payload["source_text"],
            direct_image=candidate_payload["direct_image"],
            candidate_id=candidate_payload.get("candidate_id", ""),
            source_name=candidate_payload.get("source_name", "Tuntun Sekuritas"),
        )
        item = SelectionCandidate(
            candidate=candidate,
            event_class=EventClass(classification),
            ranking_band=selection_data["ranking_band"],
            material_facts=selection_data["material_facts"],
            dedupe_facts=selection_data["dedupe_facts"],
            summary=selection_data.get("summary", ""),
            title=selection_data.get("title", ""),
            route=Destination(selection_data.get("route", Destination.ID_STOCKS_NEWS.value)),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StateBlockedError(f"candidate {key!r} has invalid durable selection data") from error
    if item.key != key:
        raise StateBlockedError(f"candidate {key!r} does not match durable selection data")
    return item


def pending_selection_candidates(state: dict[str, object]) -> list[SelectionCandidate]:
    """Reconstruct all pending selection work from durable validated submission data."""
    if not isinstance(state, dict):
        raise ValueError("state must be a durable state object")
    candidates = state.get("candidates")
    if not isinstance(candidates, dict):
        raise StateBlockedError("malformed state: candidates must be an object")
    pending = [
        _selection_candidate_from_record(key, record)
        for key, record in candidates.items()
        if isinstance(key, str) and isinstance(record, Mapping) and record.get("phase") == "pending_selection"
    ]
    return sorted(pending, key=lambda item: (item.published_at, item.key))


def _set_phase(record: dict[str, object], phase: str) -> None:
    record["phase"] = phase
    record["agent_lease_until"] = None
    if phase in {"suppressed_rank", "suppressed_ineligible"}:
        retry = record.get("retry")
        if not isinstance(retry, dict):
            raise StateBlockedError("malformed state: candidate retry must be an object")
        retry["next_attempt_at"] = None


def assign_tier(state: dict[str, object], item: SelectionCandidate) -> Tier | None:
    """Route one classified candidate for immediate standalone delivery or terminal suppression."""
    if not isinstance(state, dict) or not isinstance(item, SelectionCandidate):
        raise ValueError("assign_tier requires durable state and a SelectionCandidate")
    record = _record_for(state, item)
    if record.get("phase") != "pending_selection":
        raise StateBlockedError(f"candidate {item.key!r} is not awaiting tier selection")

    if item.route is Destination.EXCLUDE:
        _set_phase(record, "suppressed_ineligible")
        save_state(state)
        return None
    tier = tier_for_event_class(item.event_class)
    if item.route is Destination.MACRO_NEWS or tier in {Tier.ONE, Tier.TWO}:
        _set_phase(record, "pending_delivery")
    else:
        _set_phase(record, "suppressed_ineligible")
    save_state(state)
    return tier


def rank_update_sections(candidates: Sequence[SelectionCandidate]) -> list[SelectionCandidate]:
    """Rank already-classified Macro & Global and Industry items for an update's two-card budget."""
    if isinstance(candidates, (str, bytes)) or any(not isinstance(item, SelectionCandidate) for item in candidates):
        raise ValueError("candidates must contain only SelectionCandidate values")
    return sorted(
        candidates,
        key=lambda item: (item.ranking_band, -item.material_fact_count, item.key),
    )


def _tier_two_sort_key(item: SelectionCandidate) -> tuple[int, int, int, datetime, str]:
    try:
        event_weight = _TIER_TWO_EVENT_WEIGHTS[item.event_class]
    except KeyError as error:
        raise ValueError("rank_tier_two accepts Tier Two events only") from error
    return (
        event_weight,
        item.ranking_band,
        -item.material_fact_count,
        item.published_at,
        item.key,
    )


def rank_tier_two(candidates: Sequence[SelectionCandidate]) -> list[SelectionCandidate]:
    """Rank Tier Two work by fixed policy, then deterministic identity for exact ties."""
    if isinstance(candidates, (str, bytes)):
        raise ValueError("candidates must be a sequence of SelectionCandidate values")
    ranked = list(candidates)
    if any(not isinstance(item, SelectionCandidate) for item in ranked):
        raise ValueError("candidates must contain only SelectionCandidate values")
    return sorted(ranked, key=_tier_two_sort_key)


def suppress_digest_overflow(state: dict[str, object], overflow: Sequence[SelectionCandidate]) -> None:
    """Terminally suppress ranked-out work so it cannot appear in a later digest."""
    if not isinstance(state, dict):
        raise ValueError("state must be a durable state object")
    changed = False
    for item in overflow:
        if not isinstance(item, SelectionCandidate):
            raise ValueError("overflow must contain only SelectionCandidate values")
        record = _record_for(state, item)
        if record.get("phase") != "pending_selection":
            raise StateBlockedError(f"candidate {item.key!r} is not awaiting digest selection")
        _set_phase(record, "suppressed_rank")
        changed = True
    if changed:
        save_state(state)


def select_digest_candidates(
    state: dict[str, object], candidates: Sequence[SelectionCandidate] | None = None
) -> tuple[list[SelectionCandidate], list[SelectionCandidate]]:
    """Persist one closed Tier Two digest, terminally suppressing every ranked-out item."""
    if not isinstance(state, dict):
        raise ValueError("state must be a durable state object")
    if candidates is None:
        candidates = pending_selection_candidates(state)
    elif isinstance(candidates, (str, bytes)):
        raise ValueError("candidates must be a sequence of SelectionCandidate values")

    pending_tier_two: list[SelectionCandidate] = []
    for item in candidates:
        if not isinstance(item, SelectionCandidate):
            raise ValueError("candidates must contain only SelectionCandidate values")
        if tier_for_event_class(item.event_class) is not Tier.TWO:
            continue
        record = _record_for(state, item)
        if record.get("phase") == "pending_selection":
            pending_tier_two.append(item)

    ranked = rank_tier_two(pending_tier_two)
    selected = ranked[:_MAX_DIGEST_CANDIDATES]
    overflow = ranked[_MAX_DIGEST_CANDIDATES:]
    if not selected:
        return [], []

    for item in selected:
        _set_phase(_record_for(state, item), "pending_delivery")
    for item in overflow:
        _set_phase(_record_for(state, item), "suppressed_rank")
    save_state(state)
    return selected, overflow


def _previous_weekday(value: date) -> date:
    previous = value - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous


def digest_window(now: datetime) -> DigestWindow | None:
    """Return the exact closed WIB digest window due at this instant, if any."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    wib_now = now.astimezone(_WIB)
    if wib_now.weekday() >= 5 or wib_now.second != 0 or wib_now.microsecond != 0:
        return None
    if wib_now.timetz().replace(tzinfo=None) == _PRE_MARKET_TIME:
        previous_business_day = _previous_weekday(wib_now.date())
        start = datetime.combine(previous_business_day, _AFTER_CLOSE_TIME, tzinfo=_WIB)
        return DigestWindow(kind="pre_market", start=start, end=wib_now)
    if wib_now.timetz().replace(tzinfo=None) == _AFTER_CLOSE_TIME:
        start = datetime.combine(wib_now.date(), _PRE_MARKET_TIME, tzinfo=_WIB)
        return DigestWindow(kind="after_close", start=start, end=wib_now)
    return None
