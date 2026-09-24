"""Authenticated source inbox client with local handoff before cursor advancement."""
from __future__ import annotations

import json
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
        if type(result) is not dict or type(result.get("event_key")) is not str or len(result["event_key"]) != 64 or type(result.get("version")) is not int or type(result.get("duplicate")) is not bool or type(result.get("work_keys")) is not list:
            raise ControlPlaneContractError("source acceptance receipt is invalid")
        return result

    def claim(self, limit: int = 10) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("invalid claim limit")
        result = self._post(f"/v1/source-work/claim?limit={limit}", {})
        if type(result) is not list:
            raise ControlPlaneContractError("source work claim is invalid")
        return result

    def settle(self, work_key: str, lease_token: str, success: bool, error_code: str | None = None) -> dict[str, Any]:
        result = self._post(f"/v1/source-work/{_sha_key(work_key)}/settle", {"lease_token": lease_token, "success": success, "error_code": error_code})
        if type(result) is not dict or result.get("work_key") != work_key:
            raise ControlPlaneContractError("source work settlement is invalid")
        return result

    def inspect(self, event_key: str) -> dict[str, Any]:
        result = self._call(f"/v1/source-events/{_sha_key(event_key)}")
        if type(result) is not dict or type(result.get("event")) is not dict or type(result.get("work")) is not list:
            raise ControlPlaneContractError("source event inspection is invalid")
        return result

    def list_work(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        if status not in {"pending", "leased", "done", "dead_letter", "suppressed"} or not 1 <= limit <= 100:
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

    def revise(self, event_key: str, envelope: dict[str, Any], kind: str, reason: str) -> dict[str, Any]:
        if kind not in {"correction", "tombstone"} or not 1 <= len(reason.strip()) <= 500:
            raise ValueError("valid revision kind and bounded reason required")
        result = self._post(f"/v1/source-events/{_sha_key(event_key)}/versions", {"envelope": envelope, "kind": kind, "reason": reason})
        if type(result) is not dict or result.get("event_key") != event_key or type(result.get("version")) is not int:
            raise ControlPlaneContractError("source revision receipt is invalid")
        return result


def _sha_key(value: str) -> str:
    import re
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
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

    def flush(self, limit: int = 50) -> list[dict[str, Any]]:
        receipts = []
        for item in self.spool.pending(limit):
            if item.endpoint != "/v1/source-events" or type(item.payload) is not dict or type(item.payload.get("envelope")) is not dict:
                raise ControlPlaneContractError("source event handoff contains an invalid request")
            receipt = self.client.accept(item.payload["envelope"])
            self.spool.acknowledge(item.path)
            receipts.append(receipt)
        return receipts
