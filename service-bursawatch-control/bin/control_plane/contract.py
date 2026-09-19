from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from typing import Any


API_VERSION = 1
WATCHER_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
MAX_CONFIG_BYTES = 2_000_000


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
