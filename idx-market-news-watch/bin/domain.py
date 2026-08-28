from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re


class Provider(StrEnum):
    PHINTRACO = "phintraco"
    TUNTUN = "tuntun"


class SourceKind(StrEnum):
    TUNTUN_STANDALONE = "tuntun_standalone"
    CORPORATE_ENTRY = "corporate_entry"
    TUNTUN_SPECIAL_TOPIC = "tuntun_special_topic"
    PHINTRACO_NOTE = "phintraco_note"
    PHINTRACO_COMPANY_FLASH = "phintraco_company_flash"
    PHINTRACO_STOCK_INFORMATION = "phintraco_stock_information"


class EventClass(StrEnum):
    FINANCIAL_RESULTS_OR_GUIDANCE = "financial_results_or_guidance"
    CORPORATE_ACTION = "corporate_action"
    FINANCING_OR_OWNERSHIP = "financing_or_ownership"
    MNA_OR_ASSET_TRANSACTION = "mna_or_asset_transaction"
    MATERIAL_CONTRACT = "material_contract"
    LISTING_LEGAL_REGULATORY_OR_CREDIT = "listing_legal_regulatory_or_credit"
    QUANTIFIED_OPERATIONAL_EXECUTION = "quantified_operational_execution"
    OTHER_COMPANY_OPERATION = "other_company_operation"
    ROUTINE_STATUS = "routine_status"
    NOT_ELIGIBLE = "not_eligible"


class Tier(StrEnum):
    ONE = "one"
    TWO = "two"


_TICKER_PATTERN = re.compile(r"[A-Z]{4}")
_PROVIDER_URL_ROOTS = {
    Provider.PHINTRACO: "https://t.me/phintasprofits",
    Provider.TUNTUN: "https://t.me/tuntunsekuritas",
}
_TIER_ONE_EVENT_CLASSES = frozenset(
    {
        EventClass.FINANCIAL_RESULTS_OR_GUIDANCE,
        EventClass.CORPORATE_ACTION,
        EventClass.FINANCING_OR_OWNERSHIP,
        EventClass.MNA_OR_ASSET_TRANSACTION,
        EventClass.MATERIAL_CONTRACT,
        EventClass.LISTING_LEGAL_REGULATORY_OR_CREDIT,
    }
)
_TIER_TWO_EVENT_CLASSES = frozenset(
    {
        EventClass.QUANTIFIED_OPERATIONAL_EXECUTION,
        EventClass.OTHER_COMPANY_OPERATION,
        EventClass.ROUTINE_STATUS,
    }
)
_RETRY_DELAYS_MINUTES = (1, 2, 4, 8, 15, 30, 60)


def _require_aware_timestamp(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_positive_message_id(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("source_message_id must be a positive integer")


@dataclass(frozen=True, slots=True)
class SourceMessage:
    provider: Provider
    source_message_id: int
    published_at: datetime
    source_text: str
    direct_image: bool

    def __post_init__(self) -> None:
        _require_positive_message_id(self.source_message_id)
        _require_aware_timestamp(self.published_at, "published_at")


@dataclass(frozen=True, slots=True)
class CompanyCandidate:
    provider: Provider
    source_message_id: int
    ticker: str
    source_kind: SourceKind
    published_at: datetime
    source_text: str
    direct_image: bool

    def __post_init__(self) -> None:
        _require_positive_message_id(self.source_message_id)
        if _TICKER_PATTERN.fullmatch(self.ticker) is None:
            raise ValueError("ticker must match [A-Z]{4}")
        _require_aware_timestamp(self.published_at, "published_at")

    @property
    def key(self) -> str:
        return candidate_key(self)


@dataclass(frozen=True, slots=True)
class Classification:
    candidate: CompanyCandidate
    event_class: EventClass

    @property
    def tier(self) -> Tier | None:
        return tier_for_event_class(self.event_class)


@dataclass(frozen=True, slots=True)
class RetryState:
    candidate_key: str
    attempt: int

    def __post_init__(self) -> None:
        if not self.candidate_key:
            raise ValueError("candidate_key must not be empty")
        if not isinstance(self.attempt, int) or isinstance(self.attempt, bool) or self.attempt < 0:
            raise ValueError("attempt must be a non-negative integer")


def source_message_url(message: SourceMessage | CompanyCandidate) -> str:
    return f"{_PROVIDER_URL_ROOTS[message.provider]}/{message.source_message_id}"


def tier_for_event_class(event_class: EventClass) -> Tier | None:
    if event_class in _TIER_ONE_EVENT_CLASSES:
        return Tier.ONE
    if event_class in _TIER_TWO_EVENT_CLASSES:
        return Tier.TWO
    if event_class is EventClass.NOT_ELIGIBLE:
        return None
    raise ValueError(f"unsupported event class: {event_class!r}")


def retry_delay_minutes(attempt: int) -> int:
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
        raise ValueError("attempt must be a non-negative integer")
    return _RETRY_DELAYS_MINUTES[min(attempt, len(_RETRY_DELAYS_MINUTES) - 1)]


def candidate_key(candidate: CompanyCandidate) -> str:
    return f"{candidate.provider.value}:{candidate.source_message_id}:{candidate.ticker}"
