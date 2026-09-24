"""Authenticated standard-library client for the loopback delivery service."""

from __future__ import annotations

import ipaddress
import json
import math
import os
import secrets
import socket
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from .models import (
    Attachment,
    DiscordQuery,
    OperationIntent,
    OperationReceipt,
    ValidationError,
    validate_preflight,
    validate_query,
    validate_receipt,
)


MAX_RESPONSE_BYTES = 1024 * 1024
POLL_INTERVAL_SECONDS = 0.25
NON_TERMINAL_STATUSES = frozenset({"pending", "pending_reconciliation", "retrying", "delivering"})


class DeliveryClientError(RuntimeError):
    """A stable, sanitized error returned by a client operation."""

    def __init__(self, category: str, message: str | None = None) -> None:
        self.category = category
        self.message = message or _CATEGORY_MESSAGES.get(category, "delivery service request failed")
        super().__init__(self.message)


_CATEGORY_MESSAGES = {
    "invalid_configuration": "delivery service configuration is invalid",
    "invalid_token_file": "delivery token file must be a private regular file",
    "admin_credentials_required": "admin token file is required for adoption",
    "invalid_operation": "operation is not valid for this client method",
    "invalid_query": "query is not in the allowlist",
    "invalid_timeout": "wait timeout must be a finite non-negative number",
    "unauthorized": "delivery service rejected the bearer token",
    "forbidden": "delivery service denied the request",
    "not_found": "delivery operation was not found",
    "conflict": "delivery service reported an operation conflict",
    "rate_limited": "delivery service rate limited the request",
    "server_error": "delivery service returned a server error",
    "redirect": "delivery service redirects are not followed",
    "request_rejected": "delivery service rejected the request",
    "invalid_response": "delivery service returned an invalid response",
    "timeout": "delivery service request timed out",
    "network_error": "delivery service could not be reached",
}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _load_token(path: Path) -> str:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(os.fspath(path), flags)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise ValueError("not a private regular file")
        chunks = bytearray()
        while len(chunks) <= 4096:
            part = os.read(descriptor, min(1024, 4097 - len(chunks)))
            if not part:
                break
            chunks.extend(part)
        if len(chunks) > 4096:
            raise ValueError("token file too large")
        token = bytes(chunks).decode("utf-8").strip()
        if not token or any(character.isspace() for character in token):
            raise ValueError("invalid token")
        return token
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        raise DeliveryClientError("invalid_token_file") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_base_url(base_url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(base_url)
        hostname = parts.hostname
        port = parts.port
    except (TypeError, ValueError):
        raise DeliveryClientError("invalid_configuration") from None
    if (parts.scheme != "http" or not hostname or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or parts.path not in {"", "/"}):
        raise DeliveryClientError("invalid_configuration")
    try:
        is_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = hostname.lower() == "localhost"
    if not is_loopback or (port is not None and not 1 <= port <= 65535):
        raise DeliveryClientError("invalid_configuration")
    netloc = parts.netloc
    return f"http://{netloc}"


def _response_category(status: int) -> str:
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 429:
        return "rate_limited"
    if 300 <= status < 400:
        return "redirect"
    if status >= 500:
        return "server_error"
    return "request_rejected"


class DeliveryClient:
    """Submit typed operations to a local Delivery Owner service.

    The normal token authorizes submit, status, query, and wait. Adoption uses
    the separately configured admin token because it imports historical state.
    """

    def __init__(
        self,
        base_url: str,
        token_file: Path,
        timeout_seconds: float = 20,
        *,
        admin_token_file: Path | None = None,
    ) -> None:
        self._base_url = _validate_base_url(base_url)
        if not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise DeliveryClientError("invalid_configuration")
        self.timeout_seconds = float(timeout_seconds)
        self._token = _load_token(Path(token_file))
        self._admin_token = _load_token(Path(admin_token_file)) if admin_token_file is not None else None
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def submit(self, operation: OperationIntent) -> OperationReceipt:
        if not isinstance(operation, OperationIntent):
            raise DeliveryClientError("invalid_operation")
        if operation.legacy_nonce is not None:
            raise DeliveryClientError("invalid_operation")
        body, content_type = _multipart_body(operation, include_legacy_nonce=False)
        response = self._request(
            "POST",
            "/v1/operations",
            body=body,
            content_type=content_type,
            token=self._token,
        )
        return self._parse_receipt(response, operation)

    def status(self, operation_key: str) -> OperationReceipt | None:
        from .models import KEY

        if not isinstance(operation_key, str) or not KEY.fullmatch(operation_key):
            raise DeliveryClientError("invalid_operation")
        return self._status(operation_key, self.timeout_seconds)

    def _status(self, operation_key: str, timeout_seconds: float) -> OperationReceipt | None:
        from .models import KEY

        if not isinstance(operation_key, str) or not KEY.fullmatch(operation_key):
            raise DeliveryClientError("invalid_operation")
        encoded_key = urllib.parse.quote(operation_key, safe="")
        response = self._request(
            "GET",
            f"/v1/operations/by-key/{encoded_key}",
            token=self._token,
            allow_not_found=True,
            timeout_seconds=timeout_seconds,
        )
        if response is None:
            return None
        return self._parse_receipt(response)

    def adopt_completed(
        self,
        operation: OperationIntent,
        receipt: Mapping[str, str],
    ) -> OperationReceipt:
        self._require_admin_token()
        if not isinstance(operation, OperationIntent) or operation.legacy_nonce is not None:
            raise DeliveryClientError("invalid_operation")
        try:
            validated_receipt = validate_receipt(receipt, str(operation.kind), operation.target)
            document = {
                "action": "completed",
                "operation": operation.as_dict(include_legacy_nonce=False),
                "receipt": validated_receipt,
                "payload_digest": operation.digest,
            }
        except (ValidationError, TypeError):
            raise DeliveryClientError("invalid_operation") from None
        response = self._post_adoption(document, operation)
        return self._parse_receipt(response, operation)

    def adopt_pending(
        self,
        operation: OperationIntent,
        *,
        preflight: Mapping[str, Any] | None = None,
    ) -> OperationReceipt:
        self._require_admin_token()
        if not isinstance(operation, OperationIntent) or not operation.reconcile_before_first_create:
            raise DeliveryClientError("invalid_operation")
        try:
            document = {
                "action": "pending",
                "operation": operation.as_dict(include_legacy_nonce=True),
                "payload_digest": operation.digest,
            }
            validated_preflight = validate_preflight(preflight, str(operation.kind))
            if validated_preflight is not None:
                document["preflight"] = validated_preflight
        except ValidationError:
            raise DeliveryClientError("invalid_operation") from None
        response = self._post_adoption(document, operation)
        return self._parse_receipt(response, operation)

    def query(self, query: DiscordQuery) -> object:
        if not isinstance(query, DiscordQuery):
            raise DeliveryClientError("invalid_query")
        try:
            document = validate_query(query.as_dict())
        except ValidationError:
            raise DeliveryClientError("invalid_query") from None
        response = self._request_json("POST", "/v1/queries", document, token=self._token)
        try:
            return json.loads(response)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            raise DeliveryClientError("invalid_response") from None

    def wait(self, operation_key: str, timeout_seconds: float) -> OperationReceipt:
        if (not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds)
                or timeout_seconds < 0):
            raise DeliveryClientError("invalid_timeout")
        receipt = self.status(operation_key)
        if receipt is None:
            raise DeliveryClientError("not_found")
        deadline = time.monotonic() + float(timeout_seconds)
        while receipt.status in NON_TERMINAL_STATUSES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return receipt
            time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return receipt
            request_timeout = min(self.timeout_seconds, remaining)
            deadline_limited = remaining <= self.timeout_seconds
            try:
                updated = self._status(operation_key, request_timeout)
            except DeliveryClientError as exc:
                if exc.category == "timeout" and deadline_limited:
                    return receipt
                raise
            if updated is not None:
                receipt = updated
        return receipt

    def _require_admin_token(self) -> None:
        if self._admin_token is None:
            raise DeliveryClientError("admin_credentials_required")

    def _request_json(self, method: str, path: str, document: Any, *, token: str | None) -> bytes:
        try:
            body = json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise DeliveryClientError("invalid_operation") from None
        return self._request(method, path, body=body, content_type="application/json", token=token)

    def _post_adoption(self, document: dict[str, Any], operation: OperationIntent) -> bytes:
        if operation.attachments:
            body, content_type = _multipart_document("adoption", document, operation.attachments)
            return self._request(
                "POST", "/v1/operations/adopt", body=body, content_type=content_type,
                token=self._admin_token,
            )
        return self._request_json("POST", "/v1/operations/adopt", document, token=self._admin_token)

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None,
        body: bytes | None = None,
        content_type: str | None = None,
        allow_not_found: bool = False,
        timeout_seconds: float | None = None,
    ) -> bytes | None:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if content_type is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self._base_url + path, data=body, headers=headers, method=method)
        try:
            request_timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
            with self._opener.open(request, timeout=request_timeout) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    raise DeliveryClientError("invalid_response")
                return response_body
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if allow_not_found and status == 404:
                return None
            raise DeliveryClientError(_response_category(status)) from None
        except urllib.error.URLError as exc:
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise DeliveryClientError("timeout") from None
            raise DeliveryClientError("network_error") from None
        except (TimeoutError, socket.timeout):
            raise DeliveryClientError("timeout") from None
        except DeliveryClientError:
            raise
        except (OSError, ValueError):
            raise DeliveryClientError("network_error") from None

    @staticmethod
    def _parse_receipt(response: bytes, operation: OperationIntent | None = None) -> OperationReceipt:
        try:
            value = json.loads(response)
            return OperationReceipt.from_json(value, operation)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValidationError):
            raise DeliveryClientError("invalid_response") from None


def _multipart_body(operation: OperationIntent, *, include_legacy_nonce: bool) -> tuple[bytes, str]:
    try:
        operation_document = operation.as_dict(include_legacy_nonce=include_legacy_nonce)
    except ValidationError:
        raise DeliveryClientError("invalid_operation") from None
    operation_bytes = json.dumps(operation_document, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return _multipart_parts("operation", operation_bytes, operation.attachments)


def _multipart_document(
    field_name: str,
    document: Mapping[str, Any],
    attachments: tuple[Attachment, ...],
) -> tuple[bytes, str]:
    document_bytes = json.dumps(document, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return _multipart_parts(field_name, document_bytes, attachments)


def _multipart_parts(
    field_name: str,
    document_bytes: bytes,
    attachments: tuple[Attachment, ...],
) -> tuple[bytes, str]:
    if field_name not in {"operation", "adoption"}:
        raise DeliveryClientError("invalid_operation")
    boundary = "bursawatch-delivery-" + secrets.token_hex(16)
    boundary_bytes = boundary.encode("ascii")
    chunks: list[bytes] = []

    def start_part(headers: bytes, content: bytes) -> None:
        chunks.extend((b"--", boundary_bytes, b"\r\n", headers, b"\r\n\r\n", content, b"\r\n"))

    start_part(
        f'Content-Disposition: form-data; name="{field_name}"\r\nContent-Type: application/json'.encode("ascii"),
        document_bytes,
    )
    for attachment in attachments:
        if not isinstance(attachment, Attachment):
            raise DeliveryClientError("invalid_operation")
        headers = (
            f'Content-Disposition: form-data; name="attachments"; filename="{attachment.filename}"\r\n'
            f"Content-Type: {attachment.mime_type}"
        ).encode("ascii")
        start_part(headers, attachment.data)
    chunks.extend((b"--", boundary_bytes, b"--\r\n"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
