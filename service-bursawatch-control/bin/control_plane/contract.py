from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


API_VERSION = 1
WATCHER_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
JOB_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
MAX_CONFIG_BYTES = 2_000_000
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 86_400


class ContractError(ValueError):
    """Raised when an API payload violates the control-plane contract."""


def canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("payload must be JSON-serializable") from exc
    if len(encoded) > MAX_CONFIG_BYTES:
        raise ContractError(f"configuration exceeds {MAX_CONFIG_BYTES} bytes")
    return encoded


def config_checksum(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(config)).hexdigest()


def validate_watcher_id(value: object) -> str:
    if type(value) is not str or not WATCHER_ID_RE.fullmatch(value):
        raise ContractError("watcher_id must use lowercase letters, digits, and hyphens")
    return value


def validate_job_id(value: object) -> str:
    if type(value) is not str or not JOB_ID_RE.fullmatch(value):
        raise ContractError("job_id must use lowercase letters, digits, and hyphens")
    return value


def validate_interval_seconds(value: object) -> int:
    if type(value) is not int or not MIN_INTERVAL_SECONDS <= value <= MAX_INTERVAL_SECONDS:
        raise ContractError(
            f"interval_seconds must be between {MIN_INTERVAL_SECONDS} and {MAX_INTERVAL_SECONDS}"
        )
    if value % 60:
        raise ContractError("interval_seconds must be a whole number of minutes")
    return value


def validate_timezone(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ContractError("timezone must be a non-empty IANA timezone")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ContractError("timezone must be a valid IANA timezone") from exc
    return value


def schedule_checksum(enabled: bool, interval_seconds: int, timezone: str) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "enabled": enabled,
                "interval_seconds": interval_seconds,
                "timezone": timezone,
            }
        )
    ).hexdigest()


def validate_timestamp(value: object, label: str = "updated_at") -> str:
    if type(value) is not str or not value.strip():
        raise ContractError(f"{label} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{label} must include a timezone")
    return value


@dataclass(frozen=True)
class ConfigSnapshot:
    watcher_id: str
    revision: int
    config_version: int
    config: dict[str, Any]
    config_sha256: str
    updated_at: str

    def __post_init__(self) -> None:
        validate_watcher_id(self.watcher_id)
        if type(self.revision) is not int or self.revision < 1:
            raise ContractError("revision must be a positive integer")
        if type(self.config_version) is not int or self.config_version < 1:
            raise ContractError("config_version must be a positive integer")
        if type(self.config) is not dict:
            raise ContractError("config must be an object")
        expected = config_checksum(self.config)
        if self.config_sha256 != expected:
            raise ContractError("config_sha256 does not match config")
        validate_timestamp(self.updated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "watcher_id": self.watcher_id,
            "revision": self.revision,
            "config_version": self.config_version,
            "config": self.config,
            "config_sha256": self.config_sha256,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ConfigSnapshot":
        if type(payload) is not dict:
            raise ContractError("config snapshot must be an object")
        expected_fields = {
            "api_version",
            "watcher_id",
            "revision",
            "config_version",
            "config",
            "config_sha256",
            "updated_at",
        }
        if set(payload) != expected_fields:
            raise ContractError("config snapshot has unexpected fields")
        if payload["api_version"] != API_VERSION:
            raise ContractError(f"config snapshot api_version must be {API_VERSION}")
        if type(payload["config_sha256"]) is not str:
            raise ContractError("config_sha256 must be text")
        return cls(
            watcher_id=validate_watcher_id(payload["watcher_id"]),
            revision=payload["revision"],
            config_version=payload["config_version"],
            config=payload["config"],
            config_sha256=payload["config_sha256"],
            updated_at=validate_timestamp(payload["updated_at"]),
        )


@dataclass(frozen=True)
class ScheduleSnapshot:
    """An immutable desired interval schedule, not proof of runtime application."""

    job_id: str
    revision: int
    enabled: bool
    interval_seconds: int
    timezone: str
    schedule_sha256: str
    updated_at: str

    def __post_init__(self) -> None:
        validate_job_id(self.job_id)
        if type(self.revision) is not int or self.revision < 1:
            raise ContractError("revision must be a positive integer")
        if type(self.enabled) is not bool:
            raise ContractError("enabled must be a boolean")
        validate_interval_seconds(self.interval_seconds)
        validate_timezone(self.timezone)
        expected = schedule_checksum(self.enabled, self.interval_seconds, self.timezone)
        if self.schedule_sha256 != expected:
            raise ContractError("schedule_sha256 does not match schedule")
        validate_timestamp(self.updated_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "job_id": self.job_id,
            "revision": self.revision,
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "timezone": self.timezone,
            "schedule_sha256": self.schedule_sha256,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ScheduleSnapshot":
        if type(payload) is not dict:
            raise ContractError("schedule snapshot must be an object")
        expected_fields = {
            "api_version",
            "job_id",
            "revision",
            "enabled",
            "interval_seconds",
            "timezone",
            "schedule_sha256",
            "updated_at",
        }
        if set(payload) != expected_fields:
            raise ContractError("schedule snapshot has unexpected fields")
        if payload["api_version"] != API_VERSION:
            raise ContractError(f"schedule snapshot api_version must be {API_VERSION}")
        if type(payload["schedule_sha256"]) is not str:
            raise ContractError("schedule_sha256 must be text")
        return cls(
            job_id=validate_job_id(payload["job_id"]),
            revision=payload["revision"],
            enabled=payload["enabled"],
            interval_seconds=payload["interval_seconds"],
            timezone=payload["timezone"],
            schedule_sha256=payload["schedule_sha256"],
            updated_at=validate_timestamp(payload["updated_at"]),
        )
