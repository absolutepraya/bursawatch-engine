"""Authenticated source inbox client with local handoff before cursor advancement."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from control_plane_client import ControlPlaneContractError, ControlPlaneUnavailable, RequestSpool, SourceCatalogClient


class SourceEventClient(SourceCatalogClient):
    def _call(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        request = Request(self.base_url + path, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None, headers={"Accept": "application/json", "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}, method="POST" if payload is not None else "GET")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            raise ControlPlaneUnavailable(f"source inbox returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ControlPlaneUnavailable("source inbox request failed") from exc
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ControlPlaneContractError("source inbox returned invalid JSON") from exc

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._call(path, payload)

    def accept(self, envelope: dict[str, Any]) -> dict[str, Any]:
        result = self._post("/v1/source-events", {"envelope": envelope})
        if type(result) is not dict or result.get("event_key") != _event_key(envelope) or result.get("version") != 1 or type(result.get("duplicate")) is not bool or type(result.get("work_keys")) is not list or any(type(key) is not str or not _valid_sha_key(key) for key in result["work_keys"]):
            raise ControlPlaneContractError("source acceptance receipt is invalid")
        return result

    def claim(self, pipeline_ids: list[str], limit: int = 10) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100 or type(pipeline_ids) is not list or not pipeline_ids or any(type(item) is not str for item in pipeline_ids):
            raise ValueError("invalid claim filter")
        result = self._post(f"/v1/source-work/claim?limit={limit}", {"pipeline_ids": pipeline_ids})
        if type(result) is not list:
            raise ControlPlaneContractError("source work claim is invalid")
        if any(type(item) is not dict or item.get("pipeline_id") not in pipeline_ids for item in result):
            raise ControlPlaneContractError("source work claim contains an unsupported pipeline")
        return result

    def settle(self, work_key: str, lease_token: str, success: bool, error_code: str | None = None) -> dict[str, Any]:
        result = self._post(f"/v1/source-work/{_sha_key(work_key)}/settle", {"lease_token": lease_token, "success": success, "error_code": error_code})
        if type(result) is not dict or result.get("work_key") != work_key:
            raise ControlPlaneContractError("source work settlement is invalid")
        return result

    def fence(self, work_key: str, lease_token: str) -> bool:
        result = self._post(f"/v1/source-work/{_sha_key(work_key)}/fence", {"lease_token": lease_token})
        if type(result) is not dict or type(result.get("current")) is not bool:
            raise ControlPlaneContractError("source work fence is invalid")
        return result["current"]

    def begin(self, work_key: str, lease_token: str) -> bool:
        result = self._post(f"/v1/source-work/{_sha_key(work_key)}/begin", {"lease_token": lease_token})
        if type(result) is not dict or type(result.get("begun")) is not bool:
            raise ControlPlaneContractError("source work begin receipt is invalid")
        return result["begun"]

    def inspect(self, event_key: str) -> dict[str, Any]:
        result = self._call(f"/v1/source-events/{_sha_key(event_key)}")
        if type(result) is not dict or type(result.get("event")) is not dict or type(result.get("work")) is not list:
            raise ControlPlaneContractError("source event inspection is invalid")
        return result

    def list_work(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        if status not in {"pending", "leased", "executing", "done", "dead_letter", "suppressed", "superseded"} or not 1 <= limit <= 100:
            raise ValueError("invalid work filter")
        result = self._call(f"/v1/source-work?status={status}&limit={limit}")
        if type(result) is not list:
            raise ControlPlaneContractError("source work inspection is invalid")
        return result

    def _operator_action(self, work_key: str, action: str, reason: str) -> dict[str, Any]:
        if not 1 <= len(reason.strip()) <= 500:
            raise ValueError("bounded reason required")
        result = self._post(f"/v1/source-work/{_sha_key(work_key)}/{action}", {"reason": reason})
        if type(result) is not dict or result.get("work_key") != work_key:
            raise ControlPlaneContractError("source work action is invalid")
        return result

    def replay(self, work_key: str, reason: str) -> dict[str, Any]:
        return self._operator_action(work_key, "replay", reason)

    def suppress(self, work_key: str, reason: str) -> dict[str, Any]:
        return self._operator_action(work_key, "suppress", reason)

    def recover(self, work_key: str, reason: str, *, worker_stopped: bool) -> dict[str, Any]:
        if worker_stopped is not True or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("recovery requires a stopped worker and bounded reason")
        result = self._post(f"/v1/source-work/{_sha_key(work_key)}/recover", {"reason": reason, "worker_stopped": True})
        if type(result) is not dict or result.get("work_key") != work_key or result.get("status") != "dead_letter":
            raise ControlPlaneContractError("source work recovery is invalid")
        return result

    def revise(self, event_key: str, envelope: dict[str, Any], kind: str, revision_id: str, reason: str) -> dict[str, Any]:
        if kind not in {"correction", "tombstone"} or not 1 <= len(reason.strip()) <= 500 or type(revision_id) is not str or not 1 <= len(revision_id) <= 128:
            raise ValueError("valid revision kind and bounded reason required")
        result = self._post(f"/v1/source-events/{_sha_key(event_key)}/versions", {"envelope": envelope, "kind": kind, "revision_id": revision_id, "reason": reason})
        if type(result) is not dict or result.get("event_key") != event_key or type(result.get("version")) is not int or type(result.get("duplicate")) is not bool:
            raise ControlPlaneContractError("source revision receipt is invalid")
        return result


def _event_key(envelope: dict[str, Any]) -> str:
    try:
        identity = [envelope["platform"], envelope["endpoint_id"], envelope["provider_event_id"]]
        if any(type(value) is not str or not value for value in identity):
            raise ValueError
        return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
    except (KeyError, ValueError, TypeError) as exc:
        raise ControlPlaneContractError("staged source event identity is invalid") from exc


def _valid_sha_key(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _sha_key(value: str) -> str:
    if type(value) is not str or not _valid_sha_key(value):
        raise ValueError("invalid source key")
    return value


class SourceEventHandoff:
    """Persist each source read before accepting it; callers advance cursors only on receipts.

    A failed request leaves the spool entry in place. A crash after acceptance but before
    cursor persistence can repeat the provider read, which the inbox deduplicates.
    """
    def __init__(self, root: Path, client: SourceEventClient):
        self.spool = RequestSpool(root)
        self.client = client

    def stage(self, envelope: dict[str, Any]) -> Path:
        return self.spool.append("POST", "/v1/source-events", {"envelope": envelope})

    def stage_revision(self, event_key: str, envelope: dict[str, Any], kind: str, revision_id: str, reason: str) -> Path:
        key = _sha_key(event_key)
        if _event_key(envelope) != key or kind not in {"correction", "tombstone"} or type(revision_id) is not str or not 1 <= len(revision_id) <= 128 or type(reason) is not str or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("invalid staged source revision")
        return self.spool.append("POST", f"/v1/source-events/{key}/versions", {"envelope": envelope, "kind": kind, "revision_id": revision_id, "reason": reason})

    def flush(self, limit: int = 50) -> list[dict[str, Any]]:
        receipts = []
        for item in self.spool.pending(limit):
            if type(item.payload) is not dict or type(item.payload.get("envelope")) is not dict:
                raise ControlPlaneContractError("source event handoff contains an invalid request")
            if item.endpoint == "/v1/source-events":
                receipt = self.client.accept(item.payload["envelope"])
            elif item.endpoint.startswith("/v1/source-events/") and item.endpoint.endswith("/versions"):
                key = item.endpoint.removeprefix("/v1/source-events/").removesuffix("/versions")
                if not _valid_sha_key(key) or _event_key(item.payload["envelope"]) != key or set(item.payload) != {"envelope", "kind", "revision_id", "reason"}:
                    raise ControlPlaneContractError("source revision handoff identity is invalid")
                receipt = self.client.revise(key, item.payload["envelope"], item.payload["kind"], item.payload["revision_id"], item.payload["reason"])
            else:
                raise ControlPlaneContractError("source event handoff endpoint is invalid")
            self.spool.acknowledge(item.path)
            receipts.append(receipt)
        return receipts
