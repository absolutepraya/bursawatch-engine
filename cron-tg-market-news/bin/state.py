from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile

from domain import (
    Classification,
    CompanyCandidate,
    Destination,
    EventClass,
    Provider,
    RetryState,
    SourceKind,
    candidate_key,
    retry_delay_minutes,
)
from stock_status import StockStatus


STATE_VERSION = 1
_AGENT_LEASE_DURATION = timedelta(minutes=2)
_PROVIDER_NAMES = frozenset(provider.value for provider in Provider)
_PENDING_ANALYSIS = "pending_analysis"
_AWAITING_AGENT = "awaiting_agent"
_PENDING_SELECTION = "pending_selection"
_PENDING_DELIVERY = "pending_delivery"
_TERMINAL_PHASES = frozenset(
    {
        "suppressed_rank",
        "suppressed_duplicate",
        "suppressed_ineligible",
        "delivered",
        "delivery_failed",
        "abandoned",
    }
)
_VALID_PHASES = _TERMINAL_PHASES | {
    _PENDING_ANALYSIS,
    _AWAITING_AGENT,
    _PENDING_SELECTION,
    _PENDING_DELIVERY,
}
_STATE_KEYS = frozenset(
    {
        "version",
        "providers",
        "candidates",
        "dedupe",
        "digest_windows",
        "last_poll_success",
        "last_delivery_success",
        "last_heartbeat_hour",
        "last_error_notice",
        "stats",
    }
)
_PROVIDER_KEYS = frozenset({"observed_message_id", "bootstrap_complete", "last_poll_success", "last_error"})
_LEGACY_PROVIDER_KEYS = frozenset({"observed_message_id", "last_poll_success", "last_error"})
_CANDIDATE_KEYS = frozenset(
    {
        "candidate",
        "phase",
        "enqueued_at",
        "retry",
        "agent_lease_until",
        "classification",
        "selection",
    }
)
_LEGACY_CANDIDATE_KEYS = _CANDIDATE_KEYS - {"selection"}
_LEGACY_CANDIDATE_PAYLOAD_KEYS = frozenset(
    {
        "provider",
        "source_message_id",
        "ticker",
        "source_kind",
        "published_at",
        "source_text",
        "direct_image",
    }
)
_CANDIDATE_PAYLOAD_KEYS = _LEGACY_CANDIDATE_PAYLOAD_KEYS | {"candidate_id"}
_SOURCE_ATTRIBUTION_CANDIDATE_PAYLOAD_KEYS = _CANDIDATE_PAYLOAD_KEYS | {"source_name"}
_RETRY_KEYS = frozenset({"attempts", "next_attempt_at", "last_error"})
_STOCK_STATUS_EVENT_PREFIX = "phintraco-stock-status:"
_STOCK_STATUS_CATEGORIES = (
    "uma",
    "suspend_in",
    "suspend_out",
    "fca_in",
    "fca_out",
)
_STOCK_STATUS_EVENT_KEYS = frozenset(
    {
        "source_message_id",
        "source_url",
        "effective_date",
        *_STOCK_STATUS_CATEGORIES,
        "channel_id",
        "content",
        "phase",
        "enqueued_at",
        "retry",
        "discord_message_id",
        "delivered_at",
        "rejection_code",
    }
)
_STOCK_STATUS_DELIVERY_HANDOFF_KEYS = _STOCK_STATUS_EVENT_KEYS | {"delivery_handoff"}
_STOCK_STATUS_SOURCE_EVENT_KEYS = _STOCK_STATUS_EVENT_KEYS | {"source_event_key"}
_STOCK_STATUS_SOURCE_EVENT_HANDOFF_KEYS = _STOCK_STATUS_SOURCE_EVENT_KEYS | {"delivery_handoff"}
_STOCK_STATUS_CONFIG_KEYS = _STOCK_STATUS_EVENT_KEYS | {"config_revision"}
_STOCK_STATUS_CONFIG_HANDOFF_KEYS = _STOCK_STATUS_CONFIG_KEYS | {"delivery_handoff"}
_STOCK_STATUS_SOURCE_CONFIG_KEYS = _STOCK_STATUS_SOURCE_EVENT_KEYS | {"config_revision"}
_STOCK_STATUS_SOURCE_CONFIG_HANDOFF_KEYS = _STOCK_STATUS_SOURCE_CONFIG_KEYS | {"delivery_handoff"}
_PUBLICATION_LEDGER_KEY = "publication_projection"
_SOURCE_INGEST_RECONCILIATION_KEY = "source_ingest_state_reconciliation_v1"
_SOURCE_INGEST_RECONCILIATION_V1_FIELDS = frozenset(
    {
        "version",
        "plan_sha256",
        "source_state_sha256",
        "canonical_base_sha256",
        "source_candidate_count",
        "source_provenance_count",
        "new_candidate_count",
        "overlap_count",
        "phase_difference_count",
        "provenance_added_count",
        "source_status_event_count",
        "new_status_event_count",
        "overlap_status_event_count",
        "status_event_phase_difference_count",
        "status_event_provenance_added_count",
        "active_candidate_abandonment_count",
        "applied_at",
    }
)
_SOURCE_INGEST_RECONCILIATION_V2_FIELDS = frozenset(
    {
        "version",
        "plan_sha256",
        "source_state_sha256",
        "canonical_base_sha256",
        "delivery_resolution_sha256",
        "prior_receipt_sha256",
        "source_candidate_count",
        "source_provenance_count",
        "new_candidate_count",
        "overlap_count",
        "phase_difference_count",
        "provenance_added_count",
        "source_status_event_count",
        "new_status_event_count",
        "overlap_status_event_count",
        "status_event_phase_difference_count",
        "status_event_provenance_added_count",
        "canonical_pending_delivery_count",
        "canonical_pending_delivery_confirmed_count",
        "canonical_pending_delivery_not_found_count",
        "active_candidate_abandonment_count",
        "applied_at",
    }
)
_SOURCE_INGEST_RECONCILIATION_FIELDS = _SOURCE_INGEST_RECONCILIATION_V2_FIELDS
_REJECTED_STOCK_STATUS_EVENT_KEYS = frozenset(
    {"source_message_id", "source_url", "phase", "rejected_at", "rejection_code"}
)
_STOCK_STATUS_REASON_CODES = frozenset({"invalid_status", "message_too_long"})
_STOCK_STATUS_URL_RE = re.compile(r"https://t\.me/[A-Za-z0-9_]{5,32}/([1-9][0-9]*)\Z")
_STOCK_TICKER_RE = re.compile(r"[A-Z]{4}\Z")
_BASE_SELECTION_DATA_KEYS = frozenset({"summary", "ranking_band", "material_facts", "dedupe_facts"})
_SELECTION_DATA_KEYS = _BASE_SELECTION_DATA_KEYS | {"title"}
_LEGACY_SELECTION_DATA_KEYS = _BASE_SELECTION_DATA_KEYS - {"summary"}
_SELECTION_DATA_KEYS_WITH_TITLE = _SELECTION_DATA_KEYS
_LEGACY_SELECTION_DATA_KEYS_WITH_TITLE = _LEGACY_SELECTION_DATA_KEYS | {"title"}
_SELECTION_DATA_KEYS_WITH_ROUTE = _BASE_SELECTION_DATA_KEYS | {"route"}
_SELECTION_DATA_KEYS_WITH_TITLE_AND_ROUTE = _SELECTION_DATA_KEYS | {"route"}
_VALID_SELECTION_DATA_KEYS = frozenset(
    {
        _BASE_SELECTION_DATA_KEYS,
        _SELECTION_DATA_KEYS,
        _LEGACY_SELECTION_DATA_KEYS,
        _SELECTION_DATA_KEYS_WITH_TITLE,
        _LEGACY_SELECTION_DATA_KEYS_WITH_TITLE,
        _SELECTION_DATA_KEYS_WITH_ROUTE,
        _SELECTION_DATA_KEYS_WITH_TITLE_AND_ROUTE,
    }
)


class StateBlockedError(RuntimeError):
    """Raised when durable state cannot safely participate in a run."""


def _state_path(path: str | os.PathLike[str] | None = None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    configured_path = os.environ.get("IDX_MARKET_NEWS_STATE_PATH")
    if configured_path:
        return Path(configured_path).expanduser()
    return Path(__file__).resolve().parents[1] / "state.json"


def _require_aware_timestamp(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_timestamp(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise StateBlockedError(f"malformed state: {field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise StateBlockedError(f"malformed state: {field_name} must be an ISO timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StateBlockedError(f"malformed state: {field_name} must be timezone-aware")
    return parsed


def _validate_timestamp_or_none(value: object, field_name: str) -> None:
    if value is not None:
        _parse_timestamp(value, field_name)


def _provider_name(provider: Provider | str) -> str:
    if isinstance(provider, Provider):
        return provider.value
    if isinstance(provider, str) and provider in _PROVIDER_NAMES:
        return provider
    raise ValueError(f"unsupported provider: {provider!r}")


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r}")


def _validate_json_value(value: object, field_name: str) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise StateBlockedError(f"malformed state: {field_name} must be finite")
        return
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{field_name}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise StateBlockedError(f"malformed state: {field_name} keys must be strings")
            _validate_json_value(item, f"{field_name}.{key}")
        return
    raise StateBlockedError(f"malformed state: {field_name} is not JSON data")


def _candidate_payload(candidate: CompanyCandidate) -> dict[str, object]:
    if not isinstance(candidate.provider, Provider) or not isinstance(candidate.source_kind, SourceKind):
        raise ValueError("candidate provider and source_kind must be domain enums")
    return {
        "provider": candidate.provider.value,
        "source_message_id": candidate.source_message_id,
        "ticker": candidate.ticker,
        "candidate_id": candidate.candidate_id,
        "source_kind": candidate.source_kind.value,
        "published_at": candidate.published_at.isoformat(),
        "source_text": candidate.source_text,
        "direct_image": candidate.direct_image,
    }


def _candidate_from_payload(payload: object, field_name: str) -> CompanyCandidate:
    if not isinstance(payload, dict) or frozenset(payload) not in {
        _LEGACY_CANDIDATE_PAYLOAD_KEYS,
        _CANDIDATE_PAYLOAD_KEYS,
        _SOURCE_ATTRIBUTION_CANDIDATE_PAYLOAD_KEYS,
    }:
        raise StateBlockedError(f"malformed state: {field_name} has an invalid candidate payload")
    if not _is_plain_int(payload["source_message_id"]):
        raise StateBlockedError(f"malformed state: {field_name}.source_message_id must be an integer")
    if (payload["ticker"] is not None and not isinstance(payload["ticker"], str)) or not isinstance(payload["source_text"], str):
        raise StateBlockedError(f"malformed state: {field_name} has invalid candidate text")
    if not isinstance(payload["direct_image"], bool):
        raise StateBlockedError(f"malformed state: {field_name}.direct_image must be boolean")
    published_at = _parse_timestamp(payload["published_at"], f"{field_name}.published_at")
    try:
        return CompanyCandidate(
            provider=Provider(payload["provider"]),
            source_message_id=payload["source_message_id"],
            ticker=payload["ticker"],
            source_kind=SourceKind(payload["source_kind"]),
            published_at=published_at,
            source_text=payload["source_text"],
            direct_image=payload["direct_image"],
            candidate_id=payload.get("candidate_id", ""),
        )
    except (TypeError, ValueError) as error:
        raise StateBlockedError(f"malformed state: {field_name} has an invalid candidate") from error


def _validate_retry(value: object, field_name: str) -> None:
    if not isinstance(value, dict) or set(value) != _RETRY_KEYS:
        raise StateBlockedError(f"malformed state: {field_name} has an invalid retry record")
    attempts = value["attempts"]
    if not _is_plain_int(attempts) or attempts < 0:
        raise StateBlockedError(f"malformed state: {field_name}.attempts must be non-negative")
    _validate_timestamp_or_none(value["next_attempt_at"], f"{field_name}.next_attempt_at")
    if value["last_error"] is not None and not isinstance(value["last_error"], str):
        raise StateBlockedError(f"malformed state: {field_name}.last_error must be text or null")


def _validate_stock_status_source(source_message_id: object, source_url: object, field_name: str) -> int:
    if not _is_plain_int(source_message_id) or source_message_id <= 0:
        raise StateBlockedError(f"malformed state: {field_name}.source_message_id must be positive")
    if not isinstance(source_url, str):
        raise StateBlockedError(f"malformed state: {field_name}.source_url must be text")
    match = _STOCK_STATUS_URL_RE.fullmatch(source_url)
    if not match or int(match.group(1)) != source_message_id:
        raise StateBlockedError(f"malformed state: {field_name}.source_url has invalid identity")
    return source_message_id


def _validate_stock_status_event(key: object, event: object) -> None:
    if not isinstance(key, str) or not key.startswith(_STOCK_STATUS_EVENT_PREFIX):
        raise StateBlockedError("malformed state: stock status event key is invalid")
    suffix = key.removeprefix(_STOCK_STATUS_EVENT_PREFIX)
    if not suffix.isdigit() or suffix.startswith("0"):
        raise StateBlockedError("malformed state: stock status event key is invalid")
    if not isinstance(event, dict):
        raise StateBlockedError(f"malformed state: {key} must be an object")
    phase = event.get("phase")
    if phase == "rejected":
        if set(event) != _REJECTED_STOCK_STATUS_EVENT_KEYS:
            raise StateBlockedError(f"malformed state: {key} has invalid rejection fields")
        source_message_id = _validate_stock_status_source(
            event["source_message_id"], event["source_url"], key
        )
        _validate_timestamp_or_none(event["rejected_at"], f"{key}.rejected_at")
        if not isinstance(event["rejection_code"], str) or event["rejection_code"] not in _STOCK_STATUS_REASON_CODES:
            raise StateBlockedError(f"malformed state: {key}.rejection_code is invalid")
    else:
        if frozenset(event) not in {
            _STOCK_STATUS_EVENT_KEYS,
            _STOCK_STATUS_DELIVERY_HANDOFF_KEYS,
            _STOCK_STATUS_SOURCE_EVENT_KEYS,
            _STOCK_STATUS_SOURCE_EVENT_HANDOFF_KEYS,
            _STOCK_STATUS_CONFIG_KEYS,
            _STOCK_STATUS_CONFIG_HANDOFF_KEYS,
            _STOCK_STATUS_SOURCE_CONFIG_KEYS,
            _STOCK_STATUS_SOURCE_CONFIG_HANDOFF_KEYS,
        }:
            raise StateBlockedError(f"malformed state: {key} has invalid event fields")
        source_message_id = _validate_stock_status_source(
            event["source_message_id"], event["source_url"], key
        )
        if "source_event_key" in event and (
            not isinstance(event["source_event_key"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", event["source_event_key"])
        ):
            raise StateBlockedError(f"malformed state: {key}.source_event_key is invalid")
        if "config_revision" in event and (
            not _is_plain_int(event["config_revision"]) or event["config_revision"] < 1
        ):
            raise StateBlockedError(f"malformed state: {key}.config_revision is invalid")
        if phase not in {"pending_delivery", "delivered"}:
            raise StateBlockedError(f"malformed state: {key} has invalid phase")
        if not isinstance(event["effective_date"], str):
            raise StateBlockedError(f"malformed state: {key}.effective_date must be a date")
        try:
            parsed_date = date.fromisoformat(event["effective_date"])
        except ValueError as error:
            raise StateBlockedError(f"malformed state: {key}.effective_date must be a date") from error
        if parsed_date.isoformat() != event["effective_date"]:
            raise StateBlockedError(f"malformed state: {key}.effective_date must be canonical")
        for category in _STOCK_STATUS_CATEGORIES:
            tickers = event[category]
            if not isinstance(tickers, list) or any(
                not isinstance(ticker, str) or not _STOCK_TICKER_RE.fullmatch(ticker)
                for ticker in tickers
            ) or len(set(tickers)) != len(tickers):
                raise StateBlockedError(f"malformed state: {key}.{category} has invalid tickers")
        if not isinstance(event["channel_id"], str) or not event["channel_id"].isdigit():
            raise StateBlockedError(f"malformed state: {key}.channel_id is invalid")
        if not isinstance(event["content"], str) or not event["content"] or len(event["content"]) > 2000:
            raise StateBlockedError(f"malformed state: {key}.content is invalid")
        if "delivery_handoff" in event:
            handoff = event["delivery_handoff"]
            if not isinstance(handoff, dict) or set(handoff) != {
                "state", "operation_key", "receipt"
            }:
                raise StateBlockedError(f"malformed state: {key}.delivery_handoff is invalid")
            if handoff["state"] not in {"unknown", "accepted"}:
                raise StateBlockedError(f"malformed state: {key}.delivery_handoff.state is invalid")
            if not isinstance(handoff["operation_key"], str) or not handoff["operation_key"]:
                raise StateBlockedError(f"malformed state: {key}.delivery_handoff.operation_key is invalid")
            receipt = handoff["receipt"]
            if handoff["state"] == "unknown":
                if receipt is not None:
                    raise StateBlockedError(f"malformed state: {key}.delivery_handoff receipt is invalid")
            elif (
                not isinstance(receipt, dict)
                or set(receipt) != {"id", "key", "digest", "status", "receipt"}
                or receipt.get("key") != handoff["operation_key"]
                or not all(isinstance(receipt.get(field), str) and receipt[field] for field in ("id", "key", "digest", "status"))
                or receipt.get("receipt") is not None and not isinstance(receipt["receipt"], dict)
            ):
                raise StateBlockedError(f"malformed state: {key}.delivery_handoff receipt is invalid")
        _parse_timestamp(event["enqueued_at"], f"{key}.enqueued_at")
        retry = event["retry"]
        _validate_retry(retry, f"{key}.retry")
        if retry["attempts"] > 1_000_000 or (
            retry["last_error"] is not None and len(retry["last_error"]) > 500
        ):
            raise StateBlockedError(f"malformed state: {key}.retry is out of bounds")
        discord_message_id = event["discord_message_id"]
        delivered_at = event["delivered_at"]
        if phase == "pending_delivery":
            if discord_message_id is not None or delivered_at is not None or event["rejection_code"] is not None:
                raise StateBlockedError(f"malformed state: {key} has delivery fields before success")
        else:
            if not isinstance(discord_message_id, str) or not discord_message_id:
                raise StateBlockedError(f"malformed state: {key}.discord_message_id is invalid")
            _parse_timestamp(delivered_at, f"{key}.delivered_at")
            if event["rejection_code"] is not None:
                raise StateBlockedError(f"malformed state: {key} has a rejection code after delivery")
    if source_message_id != int(suffix):
        raise StateBlockedError(f"malformed state: {key} does not match its source identity")


def _stock_status_events(state: dict[str, object], *, create: bool = False) -> dict[str, object]:
    stats = state["stats"]
    assert isinstance(stats, dict)
    if "stock_status_events" not in stats and create:
        stats["stock_status_events"] = {}
    events = stats.get("stock_status_events", {})
    if not isinstance(events, dict):
        raise StateBlockedError("malformed state: stats.stock_status_events must be an object")
    return events


def has_stock_status_event(state: dict[str, object], source_message_id: int) -> bool:
    """Return whether this Phintraco source identity already has a durable outcome."""
    _validate_state(state)
    key = _status_event_key(source_message_id)
    return key in _stock_status_events(state)


def _validate_selection_data(value: object, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or frozenset(value) not in _VALID_SELECTION_DATA_KEYS:
        raise StateBlockedError(f"malformed state: {field_name} has invalid selection data")
    if "summary" in value and (not isinstance(value["summary"], str) or not value["summary"].strip()):
        raise StateBlockedError(f"malformed state: {field_name}.summary must be nonempty text")
    if "title" in value and (not isinstance(value["title"], str) or not value["title"].strip()):
        raise StateBlockedError(f"malformed state: {field_name}.title must be nonempty text")
    if "route" in value:
        try:
            Destination(value["route"])
        except (TypeError, ValueError) as error:
            raise StateBlockedError(f"malformed state: {field_name}.route is invalid") from error
    ranking_band = value["ranking_band"]
    if not _is_plain_int(ranking_band) or not 1 <= ranking_band <= 5:
        raise StateBlockedError(f"malformed state: {field_name}.ranking_band must be from 1 through 5")
    for facts_field in ("material_facts", "dedupe_facts"):
        facts = value[facts_field]
        if not isinstance(facts, list) or not facts or any(not isinstance(fact, str) or not fact.strip() for fact in facts):
            raise StateBlockedError(f"malformed state: {field_name}.{facts_field} must be nonempty text")

def _validate_candidate_record(key: object, record: object) -> None:
    if not isinstance(key, str) or not key:
        raise StateBlockedError("malformed state: candidate keys must be nonempty strings")
    if not isinstance(record, dict) or set(record) not in {_LEGACY_CANDIDATE_KEYS, _CANDIDATE_KEYS}:
        raise StateBlockedError(f"malformed state: candidate {key!r} has invalid keys")
    candidate = _candidate_from_payload(record["candidate"], f"candidates.{key}.candidate")
    if candidate_key(candidate) != key:
        raise StateBlockedError(f"malformed state: candidate {key!r} does not match its identity")
    phase = record["phase"]
    if not isinstance(phase, str) or phase not in _VALID_PHASES:
        raise StateBlockedError(f"malformed state: candidate {key!r} has invalid phase")
    _parse_timestamp(record["enqueued_at"], f"candidates.{key}.enqueued_at")
    _validate_retry(record["retry"], f"candidates.{key}.retry")
    lease_until = record["agent_lease_until"]
    _validate_timestamp_or_none(lease_until, f"candidates.{key}.agent_lease_until")
    classification = record["classification"]
    if classification is not None:
        if not isinstance(classification, str):
            raise StateBlockedError(f"malformed state: candidate {key!r} classification must be text or null")
        try:
            EventClass(classification)
        except ValueError as error:
            raise StateBlockedError(f"malformed state: candidate {key!r} has invalid classification") from error
    _validate_selection_data(record.get("selection"), f"candidates.{key}.selection")
    if phase == _AWAITING_AGENT and lease_until is None:
        raise StateBlockedError(f"malformed state: leased candidate {key!r} has no lease deadline")
    if phase != _AWAITING_AGENT and lease_until is not None:
        raise StateBlockedError(f"malformed state: unleased candidate {key!r} has a lease deadline")
    if phase == _PENDING_SELECTION and classification is None:
        raise StateBlockedError(f"malformed state: selected candidate {key!r} has no classification")


def _validate_state(state: object) -> None:
    if not isinstance(state, dict) or set(state) != _STATE_KEYS:
        raise StateBlockedError("malformed state: top-level schema does not match version 1")
    if state["version"] != STATE_VERSION or not _is_plain_int(state["version"]):
        raise StateBlockedError("malformed state: unsupported state version")

    providers = state["providers"]
    if not isinstance(providers, dict) or set(providers) != _PROVIDER_NAMES:
        raise StateBlockedError("malformed state: provider lanes are incomplete")
    for provider, lane in providers.items():
        if not isinstance(lane, dict) or set(lane) not in {_LEGACY_PROVIDER_KEYS, _PROVIDER_KEYS}:
            raise StateBlockedError(f"malformed state: provider lane {provider!r} has invalid keys")
        message_id = lane["observed_message_id"]
        if not _is_plain_int(message_id) or message_id < 0:
            raise StateBlockedError(f"malformed state: provider lane {provider!r} has invalid cursor")
        if "bootstrap_complete" in lane and not isinstance(lane["bootstrap_complete"], bool):
            raise StateBlockedError(f"malformed state: provider lane {provider!r} has invalid bootstrap marker")
        _validate_timestamp_or_none(lane["last_poll_success"], f"providers.{provider}.last_poll_success")
        if lane["last_error"] is not None and not isinstance(lane["last_error"], str):
            raise StateBlockedError(f"malformed state: provider lane {provider!r} has invalid error")

    candidates = state["candidates"]
    if not isinstance(candidates, dict):
        raise StateBlockedError("malformed state: candidates must be an object")
    for key, record in candidates.items():
        _validate_candidate_record(key, record)

    for name in ("dedupe", "digest_windows", "stats"):
        value = state[name]
        if not isinstance(value, dict):
            raise StateBlockedError(f"malformed state: {name} must be an object")
        _validate_json_value(value, name)
    status_events = state["stats"].get("stock_status_events")
    if "stock_status_events" in state["stats"]:
        if not isinstance(status_events, dict):
            raise StateBlockedError("malformed state: stats.stock_status_events must be an object")
        for key, event in status_events.items():
            _validate_stock_status_event(key, event)
    if _PUBLICATION_LEDGER_KEY in state["stats"]:
        _validate_publication_ledger(state["stats"][_PUBLICATION_LEDGER_KEY])
    if _SOURCE_INGEST_RECONCILIATION_KEY in state["stats"]:
        _validate_source_ingest_reconciliation(
            state["stats"][_SOURCE_INGEST_RECONCILIATION_KEY]
        )
    _validate_timestamp_or_none(state["last_poll_success"], "last_poll_success")
    _validate_timestamp_or_none(state["last_delivery_success"], "last_delivery_success")
    _validate_timestamp_or_none(state["last_heartbeat_hour"], "last_heartbeat_hour")
    if state["last_error_notice"] is not None and not isinstance(state["last_error_notice"], str):
        raise StateBlockedError("malformed state: last_error_notice must be text or null")


def _migrate_legacy_provider_lanes(state: dict[str, object]) -> bool:
    providers = state["providers"]
    assert isinstance(providers, dict)
    migrated = False
    for lane in providers.values():
        assert isinstance(lane, dict)
        if set(lane) != _LEGACY_PROVIDER_KEYS:
            continue
        cursor = lane["observed_message_id"]
        assert _is_plain_int(cursor)
        lane["bootstrap_complete"] = cursor != 0
        migrated = True
    return migrated



def _migrate_legacy_candidate_records(state: dict[str, object]) -> bool:
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    migrated = False
    for record in candidates.values():
        assert isinstance(record, dict)
        if set(record) == _LEGACY_CANDIDATE_KEYS:
            record["selection"] = None
            migrated = True
        selection = record.get("selection")
        if isinstance(selection, dict) and set(selection) == _LEGACY_SELECTION_DATA_KEYS:
            facts = selection["material_facts"]
            assert isinstance(facts, list)
            selection["summary"] = " ".join(str(fact).strip() for fact in facts)
            migrated = True
        if record["phase"] == _PENDING_SELECTION and record["selection"] is None:
            record["phase"] = _PENDING_ANALYSIS
            record["classification"] = None
            record["agent_lease_until"] = None
            record["retry"] = {
                "attempts": 0,
                "next_attempt_at": None,
                "last_error": None,
            }
            migrated = True
    return migrated

def empty_state() -> dict[str, object]:
    def provider_lane() -> dict[str, object]:
        return {
            "observed_message_id": 0,
            "bootstrap_complete": False,
            "last_poll_success": None,
            "last_error": None,
        }

    return {
        "version": STATE_VERSION,
        "providers": {provider.value: provider_lane() for provider in Provider},
        "candidates": {},
        "dedupe": {},
        "digest_windows": {},
        "last_poll_success": None,
        "last_delivery_success": None,
        "last_heartbeat_hour": None,
        "last_error_notice": None,
        "stats": {"immediate_delivery_contract_v1": {"complete": True}},
    }


def load_state(path: str | os.PathLike[str] | None = None, *, migrate: bool = True) -> dict[str, object]:
    state_path = _state_path(path)
    try:
        status = state_path.lstat()
    except FileNotFoundError:
        return empty_state()
    if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
        raise StateBlockedError("malformed state: state path must be a regular file")
    if stat.S_IMODE(status.st_mode) != 0o600:
        raise StateBlockedError("state permissions must be 0600")
    try:
        raw_state = state_path.read_text(encoding="utf-8")
    except OSError as error:
        raise StateBlockedError(f"unable to read state: {error.strerror or error}") from error
    if not raw_state:
        return empty_state()
    if not raw_state.strip():
        raise StateBlockedError("malformed state: nonempty state contains only whitespace")
    try:
        loaded = json.loads(raw_state, parse_constant=_reject_nonfinite_json_constant)
    except (json.JSONDecodeError, ValueError) as error:
        raise StateBlockedError("malformed state: JSON cannot be decoded") from error
    _validate_state(loaded)
    if migrate and (_migrate_legacy_provider_lanes(loaded) or _migrate_legacy_candidate_records(loaded)):
        save_state(loaded, state_path)
    return loaded


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_state(
    state: Mapping[str, object],
    path: str | os.PathLike[str] | None = None,
    *,
    migrate: bool = True,
) -> None:
    if not isinstance(state, dict):
        raise StateBlockedError("malformed state: top-level state must be an object")
    if type(migrate) is not bool:
        raise ValueError("migrate must be a boolean")
    _validate_state(state)
    if migrate:
        _migrate_legacy_provider_lanes(state)
        _migrate_legacy_candidate_records(state)
    _validate_state(state)
    state_path = _state_path(path)
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            dir=state_path.parent,
        )
    except OSError as error:
        raise StateBlockedError(f"unable to create temporary state: {error.strerror or error}") from error
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            descriptor = -1
            json.dump(state, temporary_file, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, state_path)
        _fsync_directory(state_path.parent)
    except OSError as error:
        raise StateBlockedError(f"unable to save state: {error.strerror or error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def run_lock(path: str | os.PathLike[str] | None = None) -> Iterator[None]:
    state_path = _state_path(path)
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = Path(f"{state_path}.lock")
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        raise StateBlockedError(f"unable to open run lock: {error.strerror or error}") from error
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise StateBlockedError("run lock is already held") from error
            raise StateBlockedError(f"unable to acquire run lock: {error.strerror or error}") from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _record_for_candidate(state: dict[str, object], key: str) -> dict[str, object]:
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    record = candidates.get(key)
    if not isinstance(record, dict):
        raise StateBlockedError(f"candidate {key!r} is not in durable state")
    return record


def _status_event_key(source_message_id: int) -> str:
    if not _is_plain_int(source_message_id) or source_message_id <= 0:
        raise ValueError("source_message_id must be a positive integer")
    return f"{_STOCK_STATUS_EVENT_PREFIX}{source_message_id}"


def _status_identity_fields(event: dict[str, object]) -> tuple[object, ...]:
    return (
        event.get("source_event_key"),
        event.get("config_revision"),
        event.get("source_message_id"),
        event.get("source_url"),
        event.get("effective_date"),
        *(event.get(category) for category in _STOCK_STATUS_CATEGORIES),
        event.get("channel_id"),
        event.get("content"),
    )


def enqueue_stock_status(
    state: dict[str, object],
    status: StockStatus,
    source_url: str,
    channel_id: str,
    content: str,
    now: datetime,
    *,
    source_event_key: str | None = None,
    config_revision: int | None = None,
) -> bool:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    if not isinstance(status, StockStatus):
        raise ValueError("status must be a StockStatus")
    key = _status_event_key(status.source_message_id)
    _validate_stock_status_source(status.source_message_id, source_url, key)
    if not isinstance(channel_id, str) or not channel_id.isdigit():
        raise ValueError("channel_id must be a numeric Discord ID")
    if not isinstance(content, str) or not content or len(content) > 2000:
        raise ValueError("content must be nonempty and at most 2,000 characters")
    if not isinstance(status.effective_date, date):
        raise ValueError("status effective_date must be a date")
    if source_event_key is not None and (
        not isinstance(source_event_key, str)
        or not re.fullmatch(r"[0-9a-f]{64}", source_event_key)
    ):
        raise ValueError("source_event_key must be a lowercase SHA-256 identity")
    if config_revision is not None and (not _is_plain_int(config_revision) or config_revision < 1):
        raise ValueError("config_revision must be a positive integer")
    event: dict[str, object] = {
        "source_message_id": status.source_message_id,
        "source_url": source_url,
        "effective_date": status.effective_date.isoformat(),
        **{category: list(getattr(status, category)) for category in _STOCK_STATUS_CATEGORIES},
        "channel_id": channel_id,
        "content": content,
        "phase": "pending_delivery",
        "enqueued_at": now.isoformat(),
        "retry": {"attempts": 0, "next_attempt_at": None, "last_error": None},
        "discord_message_id": None,
        "delivered_at": None,
        "rejection_code": None,
    }
    if source_event_key is not None:
        event["source_event_key"] = source_event_key
    if config_revision is not None:
        event["config_revision"] = config_revision
    events = _stock_status_events(state, create=True)
    existing = events.get(key)
    if existing is not None:
        if (
            isinstance(existing, dict)
            and existing.get("phase") in {"pending_delivery", "delivered"}
            and _status_identity_fields(existing) == _status_identity_fields(event)
        ):
            return False
        if (
            isinstance(existing, dict)
            and existing.get("source_event_key") is None
            and source_event_key is not None
            and existing.get("config_revision") is None
            and _status_identity_fields(existing)[2:] == _status_identity_fields(event)[2:]
        ):
            existing["source_event_key"] = source_event_key
            if config_revision is not None:
                existing["config_revision"] = config_revision
            save_state(state)
            return False
        raise StateBlockedError(f"status event {key!r} collides with different durable content")
    events[key] = event
    save_state(state)
    return True


def _validate_publication_ledger(value: object) -> None:
    if not isinstance(value, dict):
        raise StateBlockedError("malformed state: publication projection ledger must be an object")
    for owner_key, record in value.items():
        if not isinstance(owner_key, str) or not owner_key or not isinstance(record, dict) or set(record) != {"snapshot", "ack"}:
            raise StateBlockedError("malformed state: publication projection entry is invalid")
        snapshot = record["snapshot"]
        if not isinstance(snapshot, dict) or snapshot.get("owner_key") != owner_key:
            raise StateBlockedError("malformed state: publication projection snapshot identity is invalid")
        confirmed = snapshot.get("delivery_confirmed_at")
        _parse_timestamp(confirmed, "publication_projection.delivery_confirmed_at")
        required = snapshot.get("required_operation_keys")
        legs = snapshot.get("legs")
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(key, str) or not key for key in required)
            or not isinstance(legs, list)
            or [leg.get("operation_key") for leg in legs if isinstance(leg, dict)] != required
            or len(legs) != len(required)
            or any(not isinstance(leg, dict) or leg.get("status") != "delivered" for leg in legs)
        ):
            raise StateBlockedError("malformed state: publication projection legs are incomplete")
        ack = record["ack"]
        if ack is not None and (
            not isinstance(ack, dict)
            or set(ack) != {"publication_id", "version", "digest"}
            or not isinstance(ack.get("publication_id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", ack["publication_id"])
            or type(ack.get("version")) is not int
            or ack["version"] != snapshot.get("version")
            or not isinstance(ack.get("digest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", ack["digest"])
        ):
            raise StateBlockedError("malformed state: publication projection acknowledgment is invalid")


def _validate_source_ingest_reconciliation(value: object) -> None:
    if not isinstance(value, dict):
        raise StateBlockedError("malformed state: source-ingest reconciliation receipt is invalid")
    receipt_fields = frozenset(value)
    if receipt_fields == _SOURCE_INGEST_RECONCILIATION_V1_FIELDS:
        receipt_version = 1
        count_fields = (
            "source_candidate_count",
            "source_provenance_count",
            "new_candidate_count",
            "overlap_count",
            "phase_difference_count",
            "provenance_added_count",
            "source_status_event_count",
            "new_status_event_count",
            "overlap_status_event_count",
            "status_event_phase_difference_count",
            "status_event_provenance_added_count",
            "active_candidate_abandonment_count",
        )
    elif receipt_fields == _SOURCE_INGEST_RECONCILIATION_V2_FIELDS:
        receipt_version = 2
        count_fields = (
            "source_candidate_count",
            "source_provenance_count",
            "new_candidate_count",
            "overlap_count",
            "phase_difference_count",
            "provenance_added_count",
            "source_status_event_count",
            "new_status_event_count",
            "overlap_status_event_count",
            "status_event_phase_difference_count",
            "status_event_provenance_added_count",
            "canonical_pending_delivery_count",
            "canonical_pending_delivery_confirmed_count",
            "canonical_pending_delivery_not_found_count",
            "active_candidate_abandonment_count",
        )
    else:
        raise StateBlockedError("malformed state: source-ingest reconciliation receipt is invalid")
    if value["version"] != receipt_version or not _is_plain_int(value["version"]):
        raise StateBlockedError("malformed state: source-ingest reconciliation version is invalid")
    hash_fields = ["plan_sha256", "source_state_sha256", "canonical_base_sha256"]
    if receipt_version == 2:
        hash_fields.append("delivery_resolution_sha256")
    for field in hash_fields:
        if not isinstance(value[field], str) or not re.fullmatch(r"[0-9a-f]{64}", value[field]):
            raise StateBlockedError(f"malformed state: source-ingest reconciliation {field} is invalid")
    prior_receipt_sha256 = value.get("prior_receipt_sha256")
    if receipt_version == 2 and prior_receipt_sha256 is not None and (
        not isinstance(prior_receipt_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", prior_receipt_sha256)
    ):
        raise StateBlockedError("malformed state: source-ingest reconciliation prior_receipt_sha256 is invalid")
    if any(not _is_plain_int(value[field]) or value[field] < 0 for field in count_fields):
        raise StateBlockedError("malformed state: source-ingest reconciliation counts are invalid")
    if (
        value["source_candidate_count"] != value["source_provenance_count"]
        or value["source_candidate_count"] != value["new_candidate_count"] + value["overlap_count"]
        or value["phase_difference_count"] > value["overlap_count"]
        or value["provenance_added_count"] > value["source_provenance_count"]
        or value["source_status_event_count"]
        != value["new_status_event_count"] + value["overlap_status_event_count"]
        or value["status_event_phase_difference_count"] > value["overlap_status_event_count"]
        or value["status_event_provenance_added_count"] > value["overlap_status_event_count"]
    ):
        raise StateBlockedError("malformed state: source-ingest reconciliation counts are inconsistent")
    if receipt_version == 2 and (
        value["canonical_pending_delivery_count"]
        != value["canonical_pending_delivery_confirmed_count"]
        + value["canonical_pending_delivery_not_found_count"]
    ):
        raise StateBlockedError("malformed state: source-ingest reconciliation counts are inconsistent")
    _parse_timestamp(value["applied_at"], "source-ingest reconciliation applied_at")


def record_publication_intent(state: dict[str, object], snapshot: dict[str, object]) -> bool:
    """Persist one exact confirmed snapshot before acknowledging owner delivery."""
    _validate_state(state)
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("owner_key"), str):
        raise ValueError("publication snapshot identity is invalid")
    owner_key = snapshot["owner_key"]
    stats = state["stats"]
    assert isinstance(stats, dict)
    ledger = stats.setdefault(_PUBLICATION_LEDGER_KEY, {})
    if not isinstance(ledger, dict):
        raise StateBlockedError("malformed state: publication projection ledger must be an object")
    existing = ledger.get(owner_key)
    if existing is not None:
        if not isinstance(existing, dict) or existing.get("snapshot") != snapshot:
            raise StateBlockedError("publication identity conflicts with its durable projection intent")
        return False
    ledger[owner_key] = {"snapshot": snapshot, "ack": None}
    save_state(state)
    return True


def pending_publication_intents(state: dict[str, object]) -> list[tuple[str, dict[str, object]]]:
    _validate_state(state)
    stats = state["stats"]
    assert isinstance(stats, dict)
    ledger = stats.get(_PUBLICATION_LEDGER_KEY, {})
    assert isinstance(ledger, dict)
    pending = [
        (key, record["snapshot"])
        for key, record in ledger.items()
        if isinstance(record, dict) and record.get("ack") is None
    ]
    return sorted(pending, key=lambda item: (item[1]["delivery_confirmed_at"], item[0]))


def acknowledge_publication_intent(
    state: dict[str, object], owner_key: str, ack: dict[str, object]
) -> bool:
    _validate_state(state)
    stats = state["stats"]
    assert isinstance(stats, dict)
    ledger = stats.get(_PUBLICATION_LEDGER_KEY)
    record = ledger.get(owner_key) if isinstance(ledger, dict) else None
    if not isinstance(record, dict):
        raise StateBlockedError("publication acknowledgment has no durable intent")
    if record["ack"] is not None:
        if record["ack"] != ack:
            raise StateBlockedError("publication acknowledgment changed after acceptance")
        return False
    record["ack"] = ack
    save_state(state)
    return True


def publication_checkpoint_comparison(
    state: dict[str, object], compared_at: datetime
) -> dict[str, object]:
    _validate_state(state)
    _require_aware_timestamp(compared_at, "compared_at")
    stats = state["stats"]
    assert isinstance(stats, dict)
    ledger = stats.get(_PUBLICATION_LEDGER_KEY, {})
    assert isinstance(ledger, dict)
    ordered = sorted(
        ledger.items(),
        key=lambda item: (item[1]["snapshot"]["delivery_confirmed_at"], item[0]),
    )
    confirmed = max(
        (record["snapshot"]["delivery_confirmed_at"] for record in ledger.values()),
        default=None,
    )
    accepted = None
    for _owner_key, record in ordered:
        snapshot = record["snapshot"]
        if record["ack"] is None:
            break
        accepted = snapshot["delivery_confirmed_at"]
    if confirmed is not None and not any(record["ack"] is None for record in ledger.values()):
        accepted = confirmed
    return {
        "compared_at": compared_at.isoformat(),
        "confirmed_through_at": confirmed,
        "accepted_through_at": accepted,
        "outstanding_count": sum(1 for record in ledger.values() if record["ack"] is None),
    }


def reject_stock_status(
    state: dict[str, object],
    source_message_id: int,
    source_url: str,
    reason_code: str,
    now: datetime,
) -> bool:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    key = _status_event_key(source_message_id)
    _validate_stock_status_source(source_message_id, source_url, key)
    if reason_code not in _STOCK_STATUS_REASON_CODES:
        raise ValueError("unsupported stock status rejection code")
    event: dict[str, object] = {
        "source_message_id": source_message_id,
        "source_url": source_url,
        "phase": "rejected",
        "rejected_at": now.isoformat(),
        "rejection_code": reason_code,
    }
    events = _stock_status_events(state, create=True)
    existing = events.get(key)
    if existing is not None:
        if existing == event:
            return False
        if (
            isinstance(existing, dict)
            and existing.get("phase") == "rejected"
            and existing.get("source_message_id") == source_message_id
            and existing.get("source_url") == source_url
            and existing.get("rejection_code") == reason_code
        ):
            return False
        raise StateBlockedError(f"status event {key!r} collides with different durable content")
    events[key] = event
    save_state(state)
    return True


def pending_stock_status_events(
    state: dict[str, object], now: datetime
) -> list[tuple[str, dict[str, object]]]:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    due: list[tuple[str, dict[str, object]]] = []
    for key, event in _stock_status_events(state).items():
        assert isinstance(key, str) and isinstance(event, dict)
        if event["phase"] != "pending_delivery":
            continue
        retry = event["retry"]
        assert isinstance(retry, dict)
        next_attempt_at = retry["next_attempt_at"]
        if next_attempt_at is None or _parse_timestamp(next_attempt_at, f"{key}.retry.next_attempt_at") <= now:
            due.append((key, event))
    return sorted(due, key=lambda item: item[0])


def mark_stock_status_delivered(
    state: dict[str, object],
    event_key: str,
    discord_message_id: str,
    now: datetime,
) -> None:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    if not isinstance(discord_message_id, str) or not discord_message_id:
        raise ValueError("discord_message_id must be nonempty text")
    event = _stock_status_events(state).get(event_key)
    if not isinstance(event, dict):
        raise StateBlockedError(f"status event {event_key!r} is not in durable state")
    if event["phase"] == "delivered":
        if event["discord_message_id"] == discord_message_id:
            return
        raise StateBlockedError(f"status event {event_key!r} was delivered with a different ID")
    if event["phase"] != "pending_delivery":
        raise StateBlockedError(f"status event {event_key!r} is not pending delivery")
    event["phase"] = "delivered"
    event["discord_message_id"] = discord_message_id
    event["delivered_at"] = now.isoformat()
    save_state(state)


def schedule_stock_status_retry(
    state: dict[str, object],
    event_key: str,
    now: datetime,
    error: str,
    minimum_delay_seconds: float = 0,
) -> None:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    if not isinstance(error, str) or not error.strip():
        raise ValueError("retry error must be nonempty text")
    if (
        isinstance(minimum_delay_seconds, bool)
        or not isinstance(minimum_delay_seconds, (int, float))
        or not math.isfinite(minimum_delay_seconds)
        or minimum_delay_seconds < 0
    ):
        raise ValueError("minimum_delay_seconds must be finite and non-negative")
    event = _stock_status_events(state).get(event_key)
    if not isinstance(event, dict) or event["phase"] != "pending_delivery":
        raise StateBlockedError(f"status event {event_key!r} is not pending delivery")
    retry = event["retry"]
    assert isinstance(retry, dict)
    attempts = retry["attempts"]
    due_at = now + timedelta(minutes=retry_delay_minutes(attempts))
    server_due_at = now + timedelta(seconds=minimum_delay_seconds)
    if server_due_at > due_at:
        due_at = server_due_at
    retry["attempts"] = attempts + 1
    retry["next_attempt_at"] = due_at.isoformat()
    retry["last_error"] = error.strip()[:500]
    save_state(state)


def _candidate_from_record(key: str, record: dict[str, object]) -> CompanyCandidate:
    return _candidate_from_payload(record["candidate"], f"candidates.{key}.candidate")


def _retry_due_at(record: dict[str, object], now: datetime) -> bool:
    retry = record["retry"]
    assert isinstance(retry, dict)
    next_attempt_at = retry["next_attempt_at"]
    return next_attempt_at is None or _parse_timestamp(next_attempt_at, "retry.next_attempt_at") <= now


def enqueue_candidate(state: dict[str, object], candidate: CompanyCandidate, now: datetime) -> bool:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    key = candidate_key(candidate)
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    if key in candidates:
        existing = _candidate_from_record(key, _record_for_candidate(state, key))
        if existing != candidate:
            raise StateBlockedError(f"candidate identity collision for {key!r}")
        return False
    candidates[key] = {
        "candidate": _candidate_payload(candidate),
        "phase": _PENDING_ANALYSIS,
        "enqueued_at": now.isoformat(),
        "retry": {
            "attempts": 0,
            "next_attempt_at": now.isoformat(),
            "last_error": None,
        },
        "agent_lease_until": None,
        "classification": None,
        "selection": None,
    }
    save_state(state)
    return True


def claim_oldest_pending_analysis(
    state: dict[str, object], now: datetime, *, candidate_keys: set[str] | None = None
) -> CompanyCandidate | None:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    due_candidates: list[tuple[datetime, str, dict[str, object]]] = []
    for key, record in candidates.items():
        assert isinstance(key, str) and isinstance(record, dict)
        if (candidate_keys is None or key in candidate_keys) and record["phase"] == _PENDING_ANALYSIS and _retry_due_at(record, now):
            due_candidates.append((_parse_timestamp(record["enqueued_at"], f"candidates.{key}.enqueued_at"), key, record))
    if not due_candidates:
        return None
    _, key, record = min(due_candidates, key=lambda item: (item[0], item[1]))
    record["phase"] = _AWAITING_AGENT
    record["agent_lease_until"] = (now + _AGENT_LEASE_DURATION).isoformat()
    save_state(state)
    return _candidate_from_record(key, record)


def _schedule_retry(
    record: dict[str, object],
    key: str,
    now: datetime,
    error: str,
    minimum_due_at: datetime | None = None,
) -> RetryState:
    retry = record["retry"]
    assert isinstance(retry, dict)
    attempts = retry["attempts"]
    assert _is_plain_int(attempts)
    next_attempt = attempts + 1
    retry["attempts"] = next_attempt
    due_at = now + timedelta(minutes=retry_delay_minutes(attempts))
    if minimum_due_at is not None and minimum_due_at > due_at:
        due_at = minimum_due_at
    retry["next_attempt_at"] = due_at.isoformat()
    retry["last_error"] = error
    record["phase"] = _PENDING_ANALYSIS
    record["agent_lease_until"] = None
    return RetryState(candidate_key=key, attempt=next_attempt)


def expire_agent_leases(
    state: dict[str, object], now: datetime, *, candidate_keys: set[str] | None = None
) -> list[CompanyCandidate]:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    expired: list[CompanyCandidate] = []
    for key, record in candidates.items():
        assert isinstance(key, str) and isinstance(record, dict)
        if (candidate_keys is not None and key not in candidate_keys) or record["phase"] != _AWAITING_AGENT:
            continue
        lease_until = _parse_timestamp(record["agent_lease_until"], f"candidates.{key}.agent_lease_until")
        if lease_until > now:
            continue
        _schedule_retry(record, key, now, "agent lease expired")
        expired.append(_candidate_from_record(key, record))
    if expired:
        save_state(state)
    return expired


def submit_classification(
    state: dict[str, object],
    classification: Classification,
    now: datetime,
    selection: Mapping[str, object],
) -> None:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    if not isinstance(classification, Classification):
        raise ValueError("classification must be a Classification")
    if not isinstance(selection, Mapping):
        raise ValueError("selection must be a mapping")
    persisted_selection = dict(selection)
    _validate_selection_data(persisted_selection, "selection")
    key = candidate_key(classification.candidate)
    record = _record_for_candidate(state, key)
    if record["phase"] != _AWAITING_AGENT:
        raise StateBlockedError(f"candidate {key!r} is not awaiting agent classification")
    if _candidate_from_record(key, record) != classification.candidate:
        raise StateBlockedError(f"candidate {key!r} does not match its active lease")
    lease_until = _parse_timestamp(record["agent_lease_until"], f"candidates.{key}.agent_lease_until")
    if lease_until <= now:
        raise StateBlockedError(f"candidate {key!r} agent lease has expired")
    record["phase"] = _PENDING_SELECTION
    record["classification"] = classification.event_class.value
    record["selection"] = persisted_selection
    record["agent_lease_until"] = None
    save_state(state)


def mark_terminal(state: dict[str, object], key: str, phase: str) -> None:
    _validate_state(state)
    if phase not in _TERMINAL_PHASES:
        raise ValueError(f"phase {phase!r} is not terminal")
    record = _record_for_candidate(state, key)
    record["phase"] = phase
    record["agent_lease_until"] = None
    retry = record["retry"]
    assert isinstance(retry, dict)
    retry["next_attempt_at"] = None
    save_state(state)


def abandon_active_candidates(state: dict[str, object], reason: str) -> int:
    """Terminally suppress all in-flight work during an approved delivery-contract cutover."""
    _validate_state(state)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("abandon reason must be nonempty text")
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    abandoned = 0
    for record in candidates.values():
        assert isinstance(record, dict)
        if record["phase"] in _TERMINAL_PHASES:
            continue
        record["phase"] = "abandoned"
        record["agent_lease_until"] = None
        retry = record["retry"]
        assert isinstance(retry, dict)
        retry["next_attempt_at"] = None
        retry["last_error"] = reason
        abandoned += 1
    return abandoned


def schedule_retry(
    state: dict[str, object],
    key: str,
    now: datetime,
    error: str,
    minimum_due_at: datetime | None = None,
) -> RetryState:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    if minimum_due_at is not None:
        _require_aware_timestamp(minimum_due_at, "minimum_due_at")
    if not isinstance(error, str) or not error:
        raise ValueError("retry error must be nonempty text")
    record = _record_for_candidate(state, key)
    if record["phase"] in _TERMINAL_PHASES:
        raise StateBlockedError(f"terminal candidate {key!r} cannot be retried")
    retry_state = _schedule_retry(record, key, now, error, minimum_due_at)
    save_state(state)
    return retry_state


def clear_retry(state: dict[str, object], key: str) -> RetryState:
    _validate_state(state)
    record = _record_for_candidate(state, key)
    retry = record["retry"]
    assert isinstance(retry, dict)
    retry["attempts"] = 0
    retry["next_attempt_at"] = None
    retry["last_error"] = None
    save_state(state)
    return RetryState(candidate_key=key, attempt=0)


def provider_cursor(state: dict[str, object], provider: Provider | str) -> int:
    _validate_state(state)
    name = _provider_name(provider)
    providers = state["providers"]
    assert isinstance(providers, dict)
    lane = providers[name]
    assert isinstance(lane, dict)
    cursor = lane["observed_message_id"]
    assert _is_plain_int(cursor)
    return cursor


def provider_bootstrap_complete(state: dict[str, object], provider: Provider | str) -> bool:
    _validate_state(state)
    _migrate_legacy_provider_lanes(state)
    name = _provider_name(provider)
    providers = state["providers"]
    assert isinstance(providers, dict)
    lane = providers[name]
    assert isinstance(lane, dict)
    complete = lane["bootstrap_complete"]
    assert isinstance(complete, bool)
    return complete


def complete_provider_bootstrap(
    state: dict[str, object],
    provider: Provider | str,
    observed_message_id: int,
) -> bool:
    _validate_state(state)
    _migrate_legacy_provider_lanes(state)
    if not _is_plain_int(observed_message_id) or observed_message_id < 0:
        raise ValueError("observed_message_id must be a non-negative integer")
    name = _provider_name(provider)
    providers = state["providers"]
    assert isinstance(providers, dict)
    lane = providers[name]
    assert isinstance(lane, dict)
    if lane["bootstrap_complete"]:
        return False
    current = lane["observed_message_id"]
    assert _is_plain_int(current)
    lane["observed_message_id"] = max(current, observed_message_id)
    lane["bootstrap_complete"] = True
    save_state(state)
    return True


def mark_provider_bootstrap_complete(state: dict[str, object], provider: Provider | str) -> bool:
    if provider_bootstrap_complete(state, provider):
        return True
    return complete_provider_bootstrap(state, provider, provider_cursor(state, provider))


def advance_provider_cursor(state: dict[str, object], provider: Provider | str, observed_message_id: int) -> int:
    _validate_state(state)
    if not _is_plain_int(observed_message_id) or observed_message_id < 0:
        raise ValueError("observed_message_id must be a non-negative integer")
    name = _provider_name(provider)
    providers = state["providers"]
    assert isinstance(providers, dict)
    lane = providers[name]
    assert isinstance(lane, dict)
    current = lane["observed_message_id"]
    assert _is_plain_int(current)
    if observed_message_id > current:
        lane["observed_message_id"] = observed_message_id
        save_state(state)
    return lane["observed_message_id"]
