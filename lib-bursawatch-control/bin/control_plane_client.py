from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Callable
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


API_VERSION = 1
WATCHER_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
MAX_CONFIG_BYTES = 2_000_000


class ControlPlaneError(RuntimeError):
    """Base error for live control-plane access."""


class ControlPlaneUnavailable(ControlPlaneError):
    """Raised when the live control plane cannot be reached safely."""


class ControlPlaneContractError(ControlPlaneError):
    """Raised when the service returns an invalid snapshot."""


class ControlPlaneSpoolFull(ControlPlaneError):
    """Raised when the bounded local request spool cannot accept another item."""


class SourceCatalogConflict(ControlPlaneError):
    """A source catalog write used a stale expected revision."""


def _catalog_object(value: object, fields: dict[str, type | tuple[type, ...]], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ControlPlaneContractError(f"{label} must be an object")
    for key, expected in fields.items():
        if key not in value or type(value[key]) not in (expected if isinstance(expected, tuple) else (expected,)):
            raise ControlPlaneContractError(f"{label}.{key} has an invalid type")
    return value


def _catalog_list(value: object, label: str) -> list[Any]:
    if type(value) is not list:
        raise ControlPlaneContractError(f"{label} must be a list")
    return value


def _catalog_config(value: object) -> dict[str, Any]:
    config = _catalog_object(value, {key: list for key in ("selected_securities", "people_org", "endpoints", "publisher_defaults", "endpoint_overrides")}, "config")
    if set(config) != {"selected_securities", "people_org", "endpoints", "publisher_defaults", "endpoint_overrides"}:
        raise ControlPlaneContractError("config has unexpected fields")
    if any(type(symbol) is not str for symbol in config["selected_securities"]):
        raise ControlPlaneContractError("selected_securities must contain strings")
    for person in config["people_org"]:
        _catalog_object(person, {"id": str, "name": str, "kind": str, "asset_ref": (dict, type(None))}, "people_org item")
        if person["asset_ref"] is not None:
            _catalog_object(person["asset_ref"], {"url": str, "kind": str}, "asset_ref")
    for endpoint in config["endpoints"]:
        _catalog_object(endpoint, {"id": str, "publisher_id": str, "platform": str, "address": str, "credential_ref": (str, type(None))}, "endpoint item")
    for field, owner in (("publisher_defaults", "publisher_id"), ("endpoint_overrides", "endpoint_id")):
        for item in config[field]:
            _catalog_object(item, {owner: str, "capability_id": str, "enabled": bool, "settings": dict}, field + " item")
    return config


def _catalog_revision(value: object) -> dict[str, Any]:
    record = _catalog_object(value, {"revision": int, "config": dict, "sha256": str, "actor_id": str, "updated_at": str}, "catalog revision")
    if record["revision"] < 1 or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
        raise ControlPlaneContractError("catalog revision or checksum is invalid")
    _catalog_config(record["config"])
    checksum = hashlib.sha256(json.dumps(record["config"], sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    if record["sha256"] != checksum:
        raise ControlPlaneContractError("catalog checksum does not match config")
    try:
        updated_at = datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneContractError("catalog updated_at is invalid") from exc
    if updated_at.tzinfo is None or not record["actor_id"]:
        raise ControlPlaneContractError("catalog timestamp or actor is invalid")
    return record


def _source_catalog_response(path: str, result: object) -> dict[str, Any]:
    if path == "/v1/source-catalog/config":
        return _catalog_revision(result)
    if path == "/v1/source-catalog/effective":
        body = _catalog_object(result, {"revision": int, "updated_at": str, "selected_securities": list, "subscriptions": list}, "effective catalog")
        if body["revision"] < 1 or any(type(symbol) is not str for symbol in body["selected_securities"]):
            raise ControlPlaneContractError("effective catalog revision or securities are invalid")
        for item in body["subscriptions"]:
            _catalog_object(item, {"endpoint_id": str, "publisher_id": str, "platform": str, "address": str, "provider_id": (str, type(None)), "credential_ref": (str, type(None)), "capability_id": str, "pipeline": str, "enabled": bool, "verification_status": str, "settings": dict, "source": str}, "subscription")
        return body
    if path == "/v1/source-catalog":
        body = _catalog_object(result, {key: list for key in ("securities", "institutions", "people_org", "endpoints", "capabilities", "compatibility")}, "source catalog")
        _catalog_revision(body.get("config"))
        for item in body["securities"]:
            _catalog_object(item, {"symbol": str, "name": str, "exchange": str}, "security")
        for item in body["institutions"]:
            _catalog_object(item, {"id": str, "name": str, "tier": int, "asset_ref": (dict, type(None))}, "institution")
        for item in body["people_org"]:
            _catalog_object(item, {"id": str, "name": str, "kind": (str, type(None)), "tier": int, "asset_ref": (dict, type(None))}, "people_org item")
        for item in body["endpoints"]:
            _catalog_object(item, {"id": str, "publisher_id": str, "platform": str, "address": str, "provider_id": (str, type(None)), "credential_ref": (str, type(None)), "system_owned": bool, "verified": bool}, "registered endpoint")
        for item in body["capabilities"]:
            _catalog_object(item, {"id": str, "label": str, "pipeline": str, "version": int}, "capability")
        for item in body["compatibility"]:
            _catalog_object(item, {"endpoint_id": str, "capability_id": str}, "compatibility")
        return body
    raise ValueError("unsupported source catalog route")


class SourceCatalogClient:
    """Typed access to versioned source catalog snapshots.

    Machine credentials can read effective subscriptions. Human admin
    credentials are required for writes. Writes are never spooled or retried
    because a stale revision must be handled by the caller.
    """

    def __init__(self, base_url: str, token: str, *, timeout: float = 5.0, opener: Callable[..., Any] = urlopen) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("source catalog base URL is invalid")
        if type(token) is not str or not token.strip():
            raise ValueError("source catalog token is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.opener = opener

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = Request(
            self.base_url + path,
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") if payload is not None else None,
            headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="PUT" if payload is not None else "GET",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            if exc.code == 409:
                raise SourceCatalogConflict("source catalog revision is stale") from exc
            raise ControlPlaneUnavailable(f"source catalog returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ControlPlaneUnavailable("source catalog request failed") from exc
        try:
            return _source_catalog_response(path, json.loads(raw))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ControlPlaneContractError("source catalog returned invalid JSON") from exc

    def get_catalog(self) -> dict[str, Any]:
        return self._request("/v1/source-catalog")

    def get_effective(self) -> dict[str, Any]:
        return self._request("/v1/source-catalog/effective")

    def put_config(self, expected_revision: int, config: dict[str, Any]) -> dict[str, Any]:
        if type(expected_revision) is not int or expected_revision < 1 or type(config) is not dict:
            raise ValueError("source catalog write requires a revision and config")
        return self._request("/v1/source-catalog/config", {"expected_revision": expected_revision, "config": config})


@dataclass(frozen=True)
class SpoolItem:
    path: Path
    request_id: str
    method: str
    endpoint: str
    payload: dict[str, Any]


class RequestSpool:
    """Durable local-first queue for small control-plane HTTP requests."""

    def __init__(
        self,
        root: Path,
        *,
        max_bytes: int = 25 * 1024 * 1024,
        max_requests: int = 10_000,
    ) -> None:
        if max_bytes < 1 or max_requests < 1:
            raise ValueError("spool limits must be positive")
        self.root = Path(root).expanduser()
        self.pending_dir = self.root / "pending"
        self.lock_path = self.root / "spool.lock"
        self.max_bytes = max_bytes
        self.max_requests = max_requests

    def append(self, method: str, endpoint: str, payload: dict[str, Any]) -> Path:
        if method != "POST" or not endpoint.startswith("/v1/") or "//" in endpoint:
            raise ValueError("spool endpoint must be a relative v1 POST endpoint")
        request_id = uuid.uuid4().hex
        record = {
            "request_id": request_id,
            "method": method,
            "endpoint": endpoint,
            "payload": payload,
            "queued_at": datetime.now().astimezone().isoformat(),
        }
        try:
            encoded = (
                json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ControlPlaneContractError("control-plane request is not valid JSON") from exc
        if len(encoded) > 128 * 1024:
            raise ControlPlaneSpoolFull("one control-plane request exceeds the spool item limit")

        self.pending_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                files = sorted(self.pending_dir.glob("*.json"))
                current_bytes = sum(path.stat().st_size for path in files)
                if len(files) >= self.max_requests or current_bytes + len(encoded) > self.max_bytes:
                    raise ControlPlaneSpoolFull("control-plane request spool is full")
                target = self.pending_dir / f"{time.time_ns():020d}-{request_id}.json"
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=self.pending_dir, prefix=".pending-", delete=False
                ) as temporary:
                    temporary.write(encoded)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_path = Path(temporary.name)
                os.chmod(temporary_path, 0o600)
                os.replace(temporary_path, target)
                return target
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def pending(self, limit: int | None = None) -> list[SpoolItem]:
        files = sorted(self.pending_dir.glob("*.json"))
        if limit is not None:
            files = files[:limit]
        items: list[SpoolItem] = []
        for path in files:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                item = SpoolItem(
                    path=path,
                    request_id=raw["request_id"],
                    method=raw["method"],
                    endpoint=raw["endpoint"],
                    payload=raw["payload"],
                )
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ControlPlaneContractError(f"control-plane spool item is invalid: {path.name}") from exc
            items.append(item)
        return items

    def acknowledge(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved.parent != self.pending_dir.resolve() or resolved.suffix != ".json":
            raise ValueError("spool acknowledgement path is outside the pending directory")
        resolved.unlink(missing_ok=True)


def default_spool_root(watcher_id: str) -> Path:
    _validate_watcher_id(watcher_id)
    return Path.home() / ".hermes" / "state" / "bursawatch-control" / "spool" / watcher_id


class ControlPlaneReporter:
    """Queues run lifecycle and event requests, then flushes them best-effort."""

    def __init__(
        self,
        base_url: str,
        watcher_id: str,
        token: str,
        *,
        timeout: float = 5.0,
        spool: RequestSpool | None = None,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if type(token) is not str or not token.strip():
            raise ControlPlaneUnavailable("control-plane token is not configured")
        _endpoint(base_url, watcher_id)
        self.base_url = base_url.rstrip("/")
        self.watcher_id = watcher_id
        self.token = token
        self.timeout = timeout
        self.spool = spool or RequestSpool(default_spool_root(watcher_id))
        self.opener = opener
        self.last_error: str | None = None

    @classmethod
    def from_environment(cls, prefix: str) -> "ControlPlaneReporter | None":
        settings = live_config_settings(prefix)
        if settings is None:
            return None
        base_url, watcher_id, token, timeout = settings
        spool_path = os.environ.get(
            f"{prefix}_CONTROL_PLANE_SPOOL_PATH",
            str(default_spool_root(watcher_id)),
        )
        return cls(base_url, watcher_id, token, timeout=timeout, spool=RequestSpool(Path(spool_path)))

    def _post(self, endpoint: str, payload: dict[str, Any]) -> None:
        request = Request(
            f"{self.base_url}{endpoint}",
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                if not 200 <= status < 300:
                    raise ControlPlaneUnavailable(f"control-plane returned HTTP {status}")
        except HTTPError as exc:
            raise ControlPlaneUnavailable(f"control-plane returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ControlPlaneUnavailable("control-plane request failed") from exc

    def flush(self, limit: int = 50) -> int:
        sent = 0
        self.last_error = None
        try:
            items = self.spool.pending(limit)
        except (ControlPlaneError, OSError) as exc:
            self.last_error = str(exc) or "control-plane request spool could not be read"
            return sent
        for item in items:
            try:
                self._post(item.endpoint, item.payload)
                self.spool.acknowledge(item.path)
                sent += 1
            except (ControlPlaneError, OSError) as exc:
                self.last_error = str(exc) or "control-plane request could not be delivered"
                break
        return sent

    def _queue(self, endpoint: str, payload: dict[str, Any]) -> None:
        try:
            self.spool.append("POST", endpoint, payload)
        except (ControlPlaneError, OSError) as exc:
            self.last_error = str(exc) or "control-plane request could not be queued"

    def start_run(
        self,
        config_revision: int,
        scheduler_job_id: str | None = None,
        trigger: str = "scheduled",
    ) -> str:
        run_id = uuid.uuid4().hex
        self._queue(
            "/v1/runs",
            {
                "run_id": run_id,
                "watcher_id": self.watcher_id,
                "config_revision": config_revision,
                "scheduler_job_id": scheduler_job_id,
                "trigger": trigger,
            },
        )
        self.flush()
        return run_id

    def event(
        self,
        run_id: str,
        event_id: str,
        *,
        level: str,
        phase: str,
        event_type: str,
        message: str,
        attributes: dict[str, Any] | None = None,
        flush: bool = True,
    ) -> None:
        self._queue(
            f"/v1/runs/{quote(run_id, safe='')}/events",
            {
                "event_id": event_id,
                "occurred_at": datetime.now().astimezone().isoformat(),
                "level": level,
                "phase": phase,
                "event_type": event_type,
                "message": " ".join(message.split())[:500],
                "attributes": attributes or {},
            },
        )
        if flush:
            self.flush()

    def finish(
        self,
        run_id: str,
        status: str,
        error: str | None = None,
        *,
        flush: bool = True,
    ) -> None:
        self._queue(
            f"/v1/runs/{quote(run_id, safe='')}/finish",
            {"status": status, "error": " ".join(error.split())[:500] if error else None},
        )
        if flush:
            self.flush(limit=200)


def _checksum(config: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ControlPlaneContractError("control-plane config is not valid JSON") from exc
    if len(encoded) > MAX_CONFIG_BYTES:
        raise ControlPlaneContractError("control-plane config is too large")
    return hashlib.sha256(encoded).hexdigest()


def _validate_watcher_id(value: object) -> str:
    if type(value) is not str or not WATCHER_ID_RE.fullmatch(value):
        raise ControlPlaneContractError("control-plane watcher ID is invalid")
    return value


@dataclass(frozen=True)
class ConfigSnapshot:
    watcher_id: str
    revision: int
    config_version: int
    config: dict[str, Any]
    config_sha256: str
    updated_at: str

    @classmethod
    def from_payload(cls, payload: object) -> "ConfigSnapshot":
        if type(payload) is not dict:
            raise ControlPlaneContractError("control-plane response is not an object")
        fields = {
            "api_version",
            "watcher_id",
            "revision",
            "config_version",
            "config",
            "config_sha256",
            "updated_at",
        }
        if set(payload) != fields:
            raise ControlPlaneContractError("control-plane response has unexpected fields")
        if payload["api_version"] != API_VERSION:
            raise ControlPlaneContractError("control-plane API version is unsupported")
        watcher_id = _validate_watcher_id(payload["watcher_id"])
        revision = payload["revision"]
        config_version = payload["config_version"]
        config = payload["config"]
        checksum = payload["config_sha256"]
        updated_at = payload["updated_at"]
        if type(revision) is not int or revision < 1:
            raise ControlPlaneContractError("control-plane revision is invalid")
        if type(config_version) is not int or config_version < 1:
            raise ControlPlaneContractError("control-plane config version is invalid")
        if type(config) is not dict:
            raise ControlPlaneContractError("control-plane config is not an object")
        if type(checksum) is not str or checksum != _checksum(config):
            raise ControlPlaneContractError("control-plane config checksum mismatch")
        if type(updated_at) is not str or not updated_at.strip():
            raise ControlPlaneContractError("control-plane update timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ControlPlaneContractError("control-plane update timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise ControlPlaneContractError("control-plane update timestamp has no timezone")
        return cls(watcher_id, revision, config_version, config, checksum, updated_at)


def _endpoint(base_url: str, watcher_id: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ControlPlaneUnavailable("control-plane URL is invalid")
    _validate_watcher_id(watcher_id)
    return f"{base_url.rstrip('/')}/v1/watchers/{quote(watcher_id, safe='')}/config"


def fetch_config(
    base_url: str,
    watcher_id: str,
    token: str,
    timeout: float = 5.0,
    opener: Callable[..., Any] = urlopen,
) -> ConfigSnapshot:
    if type(token) is not str or not token.strip():
        raise ControlPlaneUnavailable("control-plane token is not configured")
    request = Request(
        _endpoint(base_url, watcher_id),
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read(MAX_CONFIG_BYTES + 1)
    except HTTPError as exc:
        raise ControlPlaneUnavailable(f"control-plane returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ControlPlaneUnavailable("control-plane request failed") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise ControlPlaneContractError("control-plane response is too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlPlaneContractError("control-plane response is not valid JSON") from exc
    snapshot = ConfigSnapshot.from_payload(payload)
    if snapshot.watcher_id != watcher_id:
        raise ControlPlaneContractError("control-plane watcher ID does not match request")
    return snapshot


def live_config_settings(prefix: str) -> tuple[str, str, str, float] | None:
    base_url = os.environ.get(f"{prefix}_CONTROL_PLANE_URL", "").strip()
    if not base_url:
        return None
    watcher_id = os.environ.get(f"{prefix}_CONTROL_PLANE_WATCHER_ID", "").strip()
    token = os.environ.get(f"{prefix}_CONTROL_PLANE_TOKEN", "").strip()
    timeout_raw = os.environ.get(f"{prefix}_CONTROL_PLANE_TIMEOUT_SECONDS", "5").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise ControlPlaneUnavailable("control-plane timeout is invalid") from exc
    if timeout <= 0 or timeout > 60:
        raise ControlPlaneUnavailable("control-plane timeout must be between 0 and 60 seconds")
    return base_url, watcher_id, token, timeout
