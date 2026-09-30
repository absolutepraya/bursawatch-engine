"""Receipt-bound publication projection client for domain owners."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from control_plane_client import ControlPlaneContractError, ControlPlaneUnavailable


_HEX_64 = re.compile(r"[0-9a-f]{64}")
_MAX_REQUEST_BYTES = 128 * 1024


class PublicationConflict(ControlPlaneUnavailable):
    """The publication identity or immutable version conflicts with accepted data."""


class PublicationClient:
    """Submit immutable confirmed output snapshots to the Control Plane.

    Retries reuse the same serialized request bytes. This client has no delivery
    transport and cannot create or retry Discord operations.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 5.0,
        max_attempts: int = 3,
        retry_delay: float = 0.2,
        opener: Callable[..., Any] = urlopen,
        sleep: Callable[[float], Any] = time.sleep,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("publication Control Plane base URL is invalid")
        if type(token) is not str or not token.strip():
            raise ValueError("publication owner token is required")
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError("publication request timeout must be between 0 and 30 seconds")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("publication max_attempts must be between 1 and 5")
        if type(retry_delay) not in (int, float) or not 0 <= retry_delay <= 2:
            raise ValueError("publication retry delay must be between 0 and 2 seconds")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = float(timeout)
        self.max_attempts = max_attempts
        self.retry_delay = float(retry_delay)
        self.opener = opener
        self.sleep = sleep

    def _request(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            body = json.dumps(
                dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ControlPlaneContractError("publication request is not valid JSON") from None
        if len(body) > _MAX_REQUEST_BYTES:
            raise ControlPlaneContractError("publication request exceeds the size limit")

        request = Request(
            self.base_url + path,
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        for attempt in range(self.max_attempts):
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read()
            except HTTPError as exc:
                if exc.code == 409:
                    raise PublicationConflict("publication identity conflicts with accepted output") from None
                if not _transient_status(exc.code):
                    raise ControlPlaneUnavailable(f"publication Control Plane returned HTTP {exc.code}") from None
                if attempt + 1 == self.max_attempts:
                    raise ControlPlaneUnavailable("publication Control Plane is temporarily unavailable") from None
                self.sleep(self.retry_delay * (attempt + 1))
                continue
            except (URLError, TimeoutError, OSError):
                if attempt + 1 == self.max_attempts:
                    raise ControlPlaneUnavailable("publication Control Plane request failed") from None
                self.sleep(self.retry_delay * (attempt + 1))
                continue

            try:
                result = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise ControlPlaneContractError("publication Control Plane returned invalid JSON") from None
            if type(result) is not dict:
                raise ControlPlaneContractError("publication Control Plane returned an invalid response")
            return result
        raise ControlPlaneUnavailable("publication Control Plane request failed")

    def submit(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        """Submit one exact receipt-confirmed snapshot, returning its durable ack."""
        if not isinstance(snapshot, Mapping):
            raise ValueError("publication snapshot must be a mapping")
        request_payload = dict(snapshot)
        version = request_payload.get("version")
        if type(version) is not int or version < 1:
            raise ValueError("publication snapshot version is invalid")
        ack = self._request("/v1/publications", request_payload)
        if (
            set(ack) != {"publication_id", "version", "digest"}
            or type(ack["publication_id"]) is not str
            or not _HEX_64.fullmatch(ack["publication_id"])
            or ack["version"] != version
            or type(ack["digest"]) is not str
            or not _HEX_64.fullmatch(ack["digest"])
        ):
            raise ControlPlaneContractError("publication acceptance receipt is invalid")
        return ack

    def checkpoint(self, comparison: Mapping[str, Any]) -> dict[str, Any]:
        """Report one bounded comparison of this owner's durable projection ledger."""
        if not isinstance(comparison, Mapping):
            raise ValueError("publication checkpoint comparison must be a mapping")
        result = self._request("/v1/publications/checkpoints", dict(comparison))
        if not result:
            raise ControlPlaneContractError("publication checkpoint response is invalid")
        return result


def _transient_status(status: int) -> bool:
    return status in {408, 425, 429} or 500 <= status <= 599

