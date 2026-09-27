from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import socket
import ssl
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Literal
from zoneinfo import ZoneInfo


OutcomeKind = Literal["probe", "cooldown", "leased", "auth_required", "state_blocked"]
NotificationKind = Literal[
    "transport_outage", "auth_required", "recovery", "state_blocked"
]

STATE_VERSION = 1
PROBE_LEASE_SECONDS = 75
BACKOFF_BASE_SECONDS = 60
BACKOFF_CAP_SECONDS = 15 * 60
JITTER_MAX_SECONDS = 15
ACTIVE_PROBE_WAIT_SECONDS = 5
ACTIVE_PROBE_POLL_SECONDS = 0.25
LOG_RETENTION_DAYS = 30
DEFAULT_STATE_PATH = (
    Path.home() / ".hermes" / "state" / "telegram-resilience-polyclop.json"
)
DEFAULT_LOG_PATH = Path.home() / ".logs" / "telegram-resilience-polyclop.jsonl"
WIB = ZoneInfo("Asia/Jakarta")


@dataclass(frozen=True)
class ProbeDecision:
    kind: OutcomeKind
    lease_id: str | None
    incident_id: str | None
    retry_at: datetime | None


@dataclass(frozen=True)
class PendingNotification:
    claim_id: str
    incident_id: str
    kind: NotificationKind
    event_key: str
    content: str


class StateBlockedError(RuntimeError):
    pass


async def acquire_probe_after_active_lease(
    resilience: "PolyCopResilience",
    watcher: str,
    now: datetime,
    *,
    sleep=None,
) -> ProbeDecision:
    """Wait briefly for a healthy peer probe, but never bypass a failure circuit.

    Simultaneous healthy cron ticks must serialize their independent Telegram
    sessions instead of letting the same watcher lose every lease and starve.
    A peer transport failure changes the next decision to cooldown, while an
    authorization failure changes it to auth_required, so neither can create a
    retry storm.
    """
    sleeper = asyncio.sleep if sleep is None else sleep
    attempts = int(ACTIVE_PROBE_WAIT_SECONDS / ACTIVE_PROBE_POLL_SECONDS)
    decision = resilience.acquire_probe(watcher, now)
    for _ in range(attempts):
        if decision.kind != "leased":
            return decision
        await sleeper(ACTIVE_PROBE_POLL_SECONDS)
        decision = resilience.acquire_probe(watcher, now)
    return decision


def _empty_state() -> dict[str, object]:
    return {
        "version": STATE_VERSION,
        "circuit": {
            "status": "closed",
            "lease_id": None,
            "lease_expires_at": None,
            "consecutive_transport_failures": 0,
            "next_probe_at": None,
        },
        "incident": None,
        "notifications": [],
        "last_authenticated_success_at": None,
        "last_connection": {"dc_id": None, "endpoint": None},
    }


def _require_aware(value: datetime, field: str = "now") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _parse_time(value: object, field: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StateBlockedError(f"{field} must be an ISO timestamp or null")
    try:
        return _require_aware(datetime.fromisoformat(value), field)
    except ValueError as error:
        raise StateBlockedError(f"{field} must be an ISO timestamp or null") from error


def _safe_endpoint(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    return value.split("?", 1)[0].split("#", 1)[0].rsplit("@", 1)[-1][:255] or None


def is_transport_error(error: BaseException) -> bool:
    return isinstance(error, (TimeoutError, OSError, socket.gaierror, ssl.SSLError))


class PolyCopResilience:
    def __init__(self, state_path: Path, log_path: Path) -> None:
        self.state_path = state_path
        self.log_path = log_path
        self.lock_path = state_path.with_name(state_path.name + ".lock")

    @classmethod
    def for_paths(cls, state_path: Path, log_path: Path) -> "PolyCopResilience":
        return cls(Path(state_path), Path(log_path))

    @classmethod
    def from_defaults(cls) -> "PolyCopResilience":
        state_path = os.environ.get("POLYCOP_RESILIENCE_STATE_PATH")
        log_path = os.environ.get("POLYCOP_RESILIENCE_LOG_PATH")
        if os.environ.get("BURSAWATCH_RELEASE_NO_POST") == "1":
            release_no_post_root = os.environ.get("BURSAWATCH_RELEASE_NO_POST_TEMP")
            if not release_no_post_root:
                raise StateBlockedError("release no-post resilience paths are unavailable")
            release_root = Path(release_no_post_root)
            state_path = str(release_root / "telegram-resilience.json")
            log_path = str(release_root / "telegram-resilience.jsonl")
        return cls(
            Path(state_path) if state_path else DEFAULT_STATE_PATH,
            Path(log_path) if log_path else DEFAULT_LOG_PATH,
        )

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _load(self) -> dict[str, object]:
        if not self.state_path.exists():
            return _empty_state()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StateBlockedError("shared resilience state is unreadable") from error
        self._validate(state)
        return state

    @staticmethod
    def _validate(state: object) -> None:
        if not isinstance(state, dict) or set(state) != {
            "version",
            "circuit",
            "incident",
            "notifications",
            "last_authenticated_success_at",
            "last_connection",
        }:
            raise StateBlockedError("shared resilience state has invalid keys")
        if state["version"] != STATE_VERSION:
            raise StateBlockedError("shared resilience state has unsupported version")
        circuit = state["circuit"]
        if not isinstance(circuit, dict) or set(circuit) != {
            "status",
            "lease_id",
            "lease_expires_at",
            "consecutive_transport_failures",
            "next_probe_at",
        }:
            raise StateBlockedError("shared resilience circuit has invalid keys")
        if circuit["status"] not in {
            "closed",
            "probing",
            "transport_open",
            "auth_required",
        }:
            raise StateBlockedError("shared resilience circuit status is invalid")
        if not isinstance(circuit["consecutive_transport_failures"], int) or (
            circuit["consecutive_transport_failures"] < 0
        ):
            raise StateBlockedError("shared resilience failure count is invalid")
        if circuit["lease_id"] is not None and not isinstance(circuit["lease_id"], str):
            raise StateBlockedError("shared resilience lease id is invalid")
        _parse_time(circuit["lease_expires_at"], "circuit.lease_expires_at")
        _parse_time(circuit["next_probe_at"], "circuit.next_probe_at")
        _parse_time(state["last_authenticated_success_at"], "last success")
        if not isinstance(state["notifications"], list):
            raise StateBlockedError("shared resilience notifications are invalid")
        for notification in state["notifications"]:
            if not isinstance(notification, dict) or set(notification) != {
                "incident_id",
                "kind",
                "event_key",
                "content",
                "created_at",
                "claim_id",
                "claim_expires_at",
                "acknowledged_at",
            }:
                raise StateBlockedError("shared resilience notification is invalid")
            if notification["kind"] not in {
                "transport_outage",
                "auth_required",
                "recovery",
                "state_blocked",
            }:
                raise StateBlockedError("shared resilience notification kind is invalid")
            for field in ("incident_id", "event_key", "content"):
                if not isinstance(notification[field], str):
                    raise StateBlockedError("shared resilience notification text is invalid")
            for field in ("created_at", "claim_expires_at", "acknowledged_at"):
                _parse_time(notification[field], f"notification.{field}")
            if notification["claim_id"] is not None and not isinstance(
                notification["claim_id"], str
            ):
                raise StateBlockedError("shared resilience notification claim is invalid")
        connection = state["last_connection"]
        if not isinstance(connection, dict) or set(connection) != {"dc_id", "endpoint"}:
            raise StateBlockedError("shared resilience connection metadata is invalid")
        if connection["dc_id"] is not None and not isinstance(connection["dc_id"], int):
            raise StateBlockedError("shared resilience dc id is invalid")
        if connection["endpoint"] is not None and not isinstance(connection["endpoint"], str):
            raise StateBlockedError("shared resilience endpoint is invalid")
        incident = state["incident"]
        if incident is None:
            return
        if not isinstance(incident, dict) or set(incident) != {
            "id",
            "kind",
            "opened_at",
            "affected_watchers",
            "last_error",
        }:
            raise StateBlockedError("shared resilience incident is invalid")
        if incident["kind"] not in {"transport", "auth"}:
            raise StateBlockedError("shared resilience incident kind is invalid")
        if not isinstance(incident["id"], str) or not isinstance(incident["last_error"], str):
            raise StateBlockedError("shared resilience incident fields are invalid")
        _parse_time(incident["opened_at"], "incident.opened_at")
        if not (
            isinstance(incident["affected_watchers"], list)
            and all(isinstance(item, str) for item in incident["affected_watchers"])
        ):
            raise StateBlockedError("shared resilience affected watchers are invalid")

    def _save(self, state: dict[str, object]) -> None:
        self._validate(state)
        self.state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.", dir=self.state_path.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
            directory = os.open(self.state_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _log(self, event: str, now: datetime, **detail: object) -> None:
        self.log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        record = {"at": now.isoformat(), "event": event, **detail}
        cutoff = now - timedelta(days=LOG_RETENTION_DAYS)
        retained: list[str] = []
        if self.log_path.exists():
            for raw in self.log_path.read_text(encoding="utf-8").splitlines():
                try:
                    prior = json.loads(raw)
                    prior_at = _parse_time(prior.get("at"), "log.at")
                except (AttributeError, json.JSONDecodeError, StateBlockedError):
                    continue
                if prior_at is not None and prior_at >= cutoff:
                    retained.append(json.dumps(prior, ensure_ascii=False, sort_keys=True))
        retained.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.log_path.name}.", dir=self.log_path.parent
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write("\n".join(retained))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.log_path)
            directory = os.open(self.log_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _add_watcher(state: dict[str, object], watcher: str) -> bool:
        incident = state["incident"]
        if not isinstance(incident, dict):
            return False
        watchers = incident["affected_watchers"]
        assert isinstance(watchers, list)
        if watcher in watchers:
            return False
        watchers.append(watcher)
        watchers.sort()
        return True

    @staticmethod
    def _new_incident(kind: str, watcher: str, now: datetime, error: str) -> dict[str, object]:
        return {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "opened_at": now.isoformat(),
            "affected_watchers": [watcher],
            "last_error": error,
        }

    @staticmethod
    def _notification_content(
        incident: dict[str, object], kind: NotificationKind, now: datetime
    ) -> str:
        at = now.astimezone(WIB).strftime("%H:%M")
        watchers = ",".join(incident["affected_watchers"])
        if kind == "transport_outage":
            return (
                f"❌ telegram-polycop · {at} WIB · transport unavailable; "
                f"affected={watchers}"
            )
        if kind == "auth_required":
            return (
                f"❌ telegram-polycop · {at} WIB · authorization required; "
                "manual PolyCop session login needed"
            )
        opened_at = _parse_time(incident["opened_at"], "incident.opened_at")
        assert opened_at is not None
        minutes = max(1, int((now - opened_at).total_seconds() // 60))
        return (
            f"🫀 telegram-polycop · {at} WIB · recovered after {minutes}m; "
            f"affected={watchers}"
        )

    @staticmethod
    def _queue_notification(
        state: dict[str, object],
        incident: dict[str, object],
        kind: NotificationKind,
        now: datetime,
    ) -> None:
        event_key = f"{incident['id']}:{kind}"
        notifications = state["notifications"]
        assert isinstance(notifications, list)
        if any(
            isinstance(item, dict) and item.get("event_key") == event_key
            for item in notifications
        ):
            return
        notifications.append(
            {
                "incident_id": incident["id"],
                "kind": kind,
                "event_key": event_key,
                "content": PolyCopResilience._notification_content(incident, kind, now),
                "created_at": now.isoformat(),
                "claim_id": None,
                "claim_expires_at": None,
                "acknowledged_at": None,
            }
        )

    @staticmethod
    def _new_lease(circuit: dict[str, object], now: datetime) -> str:
        lease_id = uuid.uuid4().hex
        circuit["status"] = "probing"
        circuit["lease_id"] = lease_id
        circuit["lease_expires_at"] = (
            now + timedelta(seconds=PROBE_LEASE_SECONDS)
        ).isoformat()
        return lease_id

    def acquire_probe(self, watcher: str, now: datetime) -> ProbeDecision:
        _require_aware(now)
        if not watcher:
            raise ValueError("watcher must be nonempty")
        with self._lock():
            try:
                state = self._load()
            except StateBlockedError:
                self._log("state_blocked", now, watcher=watcher)
                return ProbeDecision("state_blocked", None, None, None)
            circuit = state["circuit"]
            assert isinstance(circuit, dict)
            status = circuit["status"]
            lease_expires = _parse_time(circuit["lease_expires_at"], "circuit.lease_expires_at")
            if status == "probing" and lease_expires is not None and lease_expires <= now:
                circuit["status"] = "transport_open" if state["incident"] is not None else "closed"
                circuit["lease_id"] = None
                circuit["lease_expires_at"] = None
                if circuit["status"] == "transport_open":
                    circuit["next_probe_at"] = now.isoformat()
                self._log("stale_probe_lease_reclaimed", now, watcher=watcher)
                status = circuit["status"]
            if status == "probing":
                self._save(state)
                return ProbeDecision("leased", None, None, lease_expires)
            if status == "auth_required":
                if self._add_watcher(state, watcher):
                    self._save(state)
                incident = state["incident"]
                assert isinstance(incident, dict)
                return ProbeDecision("auth_required", None, incident["id"], None)
            if status == "transport_open":
                retry_at = _parse_time(circuit["next_probe_at"], "circuit.next_probe_at")
                assert retry_at is not None
                if retry_at > now:
                    if self._add_watcher(state, watcher):
                        self._save(state)
                    incident = state["incident"]
                    assert isinstance(incident, dict)
                    return ProbeDecision("cooldown", None, incident["id"], retry_at)
            lease_id = self._new_lease(circuit, now)
            self._save(state)
            incident = state["incident"]
            return ProbeDecision(
                "probe",
                lease_id,
                incident["id"] if isinstance(incident, dict) else None,
                None,
            )

    def _lease(self, state: dict[str, object], lease_id: str | None, now: datetime) -> dict[str, object]:
        if not lease_id:
            raise ValueError("lease id is required")
        circuit = state["circuit"]
        assert isinstance(circuit, dict)
        expires = _parse_time(circuit["lease_expires_at"], "circuit.lease_expires_at")
        if (
            circuit["status"] != "probing"
            or circuit["lease_id"] != lease_id
            or expires is None
            or expires < now
        ):
            raise ValueError("lease is not current")
        return circuit

    @staticmethod
    def _jitter(incident_id: str, failures: int) -> int:
        digest = hashlib.sha256(f"{incident_id}:{failures}".encode()).digest()
        return int.from_bytes(digest[:2], "big") % (JITTER_MAX_SECONDS + 1)

    def record_transport_failure(
        self, lease_id: str | None, watcher: str, error: BaseException, now: datetime
    ) -> None:
        _require_aware(now)
        if not is_transport_error(error):
            raise ValueError("error is not a classified Telegram transport failure")
        with self._lock():
            state = self._load()
            circuit = self._lease(state, lease_id, now)
            incident = state["incident"]
            if not isinstance(incident, dict) or incident["kind"] != "transport":
                incident = self._new_incident("transport", watcher, now, type(error).__name__)
                state["incident"] = incident
                self._queue_notification(state, incident, "transport_outage", now)
            else:
                self._add_watcher(state, watcher)
                incident["last_error"] = type(error).__name__
            failures = int(circuit["consecutive_transport_failures"]) + 1
            circuit["consecutive_transport_failures"] = failures
            base = min(BACKOFF_BASE_SECONDS * (2 ** (failures - 1)), BACKOFF_CAP_SECONDS)
            delay = min(base + self._jitter(incident["id"], failures), BACKOFF_CAP_SECONDS)
            circuit["status"] = "transport_open"
            circuit["lease_id"] = None
            circuit["lease_expires_at"] = None
            circuit["next_probe_at"] = (now + timedelta(seconds=delay)).isoformat()
            self._save(state)
            self._log(
                "transport_failure",
                now,
                watcher=watcher,
                error=type(error).__name__,
                incident_id=incident["id"],
                retry_in_seconds=delay,
            )

    def record_auth_required(self, lease_id: str | None, watcher: str, now: datetime) -> None:
        _require_aware(now)
        with self._lock():
            state = self._load()
            circuit = self._lease(state, lease_id, now)
            incident = state["incident"]
            if not isinstance(incident, dict) or incident["kind"] != "auth":
                incident = self._new_incident("auth", watcher, now, "authorization_required")
                state["incident"] = incident
                self._queue_notification(state, incident, "auth_required", now)
            else:
                self._add_watcher(state, watcher)
            circuit["status"] = "auth_required"
            circuit["lease_id"] = None
            circuit["lease_expires_at"] = None
            circuit["next_probe_at"] = None
            self._save(state)
            self._log("auth_required", now, watcher=watcher, incident_id=incident["id"])

    def record_authenticated_success(
        self,
        lease_id: str | None,
        watcher: str,
        now: datetime,
        dc_id: int | None,
        endpoint: str | None,
    ) -> None:
        _require_aware(now)
        if dc_id is not None and not isinstance(dc_id, int):
            raise ValueError("dc_id must be an integer or null")
        with self._lock():
            state = self._load()
            circuit = self._lease(state, lease_id, now)
            recovered = state["incident"]
            if isinstance(recovered, dict):
                self._queue_notification(state, recovered, "recovery", now)
            circuit.update(
                {
                    "status": "closed",
                    "lease_id": None,
                    "lease_expires_at": None,
                    "consecutive_transport_failures": 0,
                    "next_probe_at": None,
                }
            )
            state["incident"] = None
            state["last_authenticated_success_at"] = now.isoformat()
            state["last_connection"] = {"dc_id": dc_id, "endpoint": _safe_endpoint(endpoint)}
            self._save(state)
            self._log(
                "authenticated_success",
                now,
                watcher=watcher,
                recovered_incident_id=recovered["id"] if isinstance(recovered, dict) else None,
                dc_id=dc_id,
                endpoint=_safe_endpoint(endpoint),
            )

    def record_safe_release(self, lease_id: str | None, watcher: str, now: datetime) -> None:
        """Release a probe that failed locally before Telegram was contacted."""
        _require_aware(now)
        with self._lock():
            state = self._load()
            circuit = self._lease(state, lease_id, now)
            circuit.update({"status": "closed", "lease_id": None, "lease_expires_at": None, "next_probe_at": None})
            self._save(state)
            self._log("safe_release", now, watcher=watcher)

    def claim_notification(self, watcher: str, now: datetime) -> PendingNotification | None:
        _require_aware(now)
        with self._lock():
            state = self._load()
            notifications = state["notifications"]
            assert isinstance(notifications, list)
            for item in notifications:
                assert isinstance(item, dict)
                if item["acknowledged_at"] is not None:
                    continue
                claim_expires_at = _parse_time(
                    item["claim_expires_at"], "notification.claim_expires_at"
                )
                if claim_expires_at is not None and claim_expires_at > now:
                    continue
                claim_id = uuid.uuid4().hex
                item["claim_id"] = claim_id
                item["claim_expires_at"] = (
                    now + timedelta(seconds=PROBE_LEASE_SECONDS)
                ).isoformat()
                self._save(state)
                self._log(
                    "notification_claimed",
                    now,
                    watcher=watcher,
                    incident_id=item["incident_id"],
                    kind=item["kind"],
                )
                return PendingNotification(
                    claim_id=claim_id,
                    incident_id=item["incident_id"],
                    kind=item["kind"],
                    event_key=item["event_key"],
                    content=item["content"],
                )
            return None

    def acknowledge_notification(self, claim_id: str, now: datetime) -> None:
        _require_aware(now)
        if not claim_id:
            raise ValueError("claim id must be nonempty")
        with self._lock():
            state = self._load()
            notifications = state["notifications"]
            assert isinstance(notifications, list)
            for item in notifications:
                assert isinstance(item, dict)
                if item["claim_id"] != claim_id:
                    continue
                item["acknowledged_at"] = now.isoformat()
                item["claim_id"] = None
                item["claim_expires_at"] = None
                self._save(state)
                self._log(
                    "notification_acknowledged",
                    now,
                    incident_id=item["incident_id"],
                    kind=item["kind"],
                )
                return
        raise ValueError("notification claim is not current")
