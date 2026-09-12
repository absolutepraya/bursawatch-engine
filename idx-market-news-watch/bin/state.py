from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timedelta
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import tempfile

from domain import (
    Classification,
    CompanyCandidate,
    EventClass,
    Provider,
    RetryState,
    SourceKind,
    candidate_key,
    retry_delay_minutes,
)


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
_CANDIDATE_PAYLOAD_KEYS = frozenset(
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
_RETRY_KEYS = frozenset({"attempts", "next_attempt_at", "last_error"})
_BASE_SELECTION_DATA_KEYS = frozenset({"summary", "ranking_band", "material_facts", "dedupe_facts"})
_SELECTION_DATA_KEYS = _BASE_SELECTION_DATA_KEYS | {"title"}
_LEGACY_SELECTION_DATA_KEYS = _BASE_SELECTION_DATA_KEYS - {"summary"}
_SELECTION_DATA_KEYS_WITH_TITLE = _SELECTION_DATA_KEYS
_LEGACY_SELECTION_DATA_KEYS_WITH_TITLE = _LEGACY_SELECTION_DATA_KEYS | {"title"}
_VALID_SELECTION_DATA_KEYS = frozenset(
    {
        _BASE_SELECTION_DATA_KEYS,
        _SELECTION_DATA_KEYS,
        _LEGACY_SELECTION_DATA_KEYS,
        _SELECTION_DATA_KEYS_WITH_TITLE,
        _LEGACY_SELECTION_DATA_KEYS_WITH_TITLE,
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
        "source_kind": candidate.source_kind.value,
        "published_at": candidate.published_at.isoformat(),
        "source_text": candidate.source_text,
        "direct_image": candidate.direct_image,
    }


def _candidate_from_payload(payload: object, field_name: str) -> CompanyCandidate:
    if not isinstance(payload, dict) or set(payload) != _CANDIDATE_PAYLOAD_KEYS:
        raise StateBlockedError(f"malformed state: {field_name} has an invalid candidate payload")
    if not _is_plain_int(payload["source_message_id"]):
        raise StateBlockedError(f"malformed state: {field_name}.source_message_id must be an integer")
    if not isinstance(payload["ticker"], str) or not isinstance(payload["source_text"], str):
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



def _validate_selection_data(value: object, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or frozenset(value) not in _VALID_SELECTION_DATA_KEYS:
        raise StateBlockedError(f"malformed state: {field_name} has invalid selection data")
    if "summary" in value and (not isinstance(value["summary"], str) or not value["summary"].strip()):
        raise StateBlockedError(f"malformed state: {field_name}.summary must be nonempty text")
    if "title" in value and (not isinstance(value["title"], str) or not value["title"].strip()):
        raise StateBlockedError(f"malformed state: {field_name}.title must be nonempty text")
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


def load_state(path: str | os.PathLike[str] | None = None) -> dict[str, object]:
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
    if _migrate_legacy_provider_lanes(loaded) or _migrate_legacy_candidate_records(loaded):
        save_state(loaded, state_path)
    return loaded


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_state(state: Mapping[str, object], path: str | os.PathLike[str] | None = None) -> None:
    if not isinstance(state, dict):
        raise StateBlockedError("malformed state: top-level state must be an object")
    _validate_state(state)
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


def claim_oldest_pending_analysis(state: dict[str, object], now: datetime) -> CompanyCandidate | None:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    due_candidates: list[tuple[datetime, str, dict[str, object]]] = []
    for key, record in candidates.items():
        assert isinstance(key, str) and isinstance(record, dict)
        if record["phase"] == _PENDING_ANALYSIS and _retry_due_at(record, now):
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


def expire_agent_leases(state: dict[str, object], now: datetime) -> list[CompanyCandidate]:
    _validate_state(state)
    _require_aware_timestamp(now, "now")
    candidates = state["candidates"]
    assert isinstance(candidates, dict)
    expired: list[CompanyCandidate] = []
    for key, record in candidates.items():
        assert isinstance(key, str) and isinstance(record, dict)
        if record["phase"] != _AWAITING_AGENT:
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
