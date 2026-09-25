"""Standard-library client for the loopback Source Media Owner."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import socket
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .models import MediaDownload


MAX_OBJECT_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024
_REF = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_KINDS = frozenset({"image", "video", "document", "audio"})


class SourceMediaClientError(RuntimeError):
    """A sanitized, stable error returned by a client operation."""

    _MESSAGES = {
        "invalid_configuration": "source media service configuration is invalid",
        "invalid_token_file": "source media token file must be a private regular file",
        "invalid_upload": "media upload is invalid",
        "invalid_reference": "media reference is invalid",
        "unauthorized": "source media service rejected the bearer token",
        "forbidden": "source media service denied the request",
        "not_found": "source media reference was not found",
        "conflict": "source media idempotency key conflicts with another payload",
        "rate_limited": "source media service rate limited the request",
        "redirect": "source media service redirects are not followed",
        "service_unavailable": "private source media storage is unavailable",
        "server_error": "source media service returned a server error",
        "request_rejected": "source media service rejected the request",
        "invalid_response": "source media service returned invalid metadata",
        "timeout": "source media service request timed out",
        "network_error": "source media service could not be reached",
    }

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(self._MESSAGES.get(category, "source media request failed"))


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _load_token(path: Path) -> str:
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
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
            raise ValueError("token too large")
        token = bytes(chunks).decode("utf-8").strip()
        if not token or any(character.isspace() for character in token):
            raise ValueError("invalid token")
        return token
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        raise SourceMediaClientError("invalid_token_file") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _validate_base_url(base_url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(base_url)
        hostname = parts.hostname
        port = parts.port
    except (TypeError, ValueError):
        raise SourceMediaClientError("invalid_configuration") from None
    if (
        parts.scheme != "http"
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in {"", "/"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise SourceMediaClientError("invalid_configuration")
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname.lower() == "localhost"
    if not loopback:
        raise SourceMediaClientError("invalid_configuration")
    return f"http://{parts.netloc}"


def _category_for_status(status: int) -> str:
    return {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "invalid_upload",
        429: "rate_limited",
    }.get(
        status,
        "redirect" if 300 <= status < 400 else "service_unavailable" if status == 502 else "server_error" if status >= 500 else "request_rejected",
    )


class SourceMediaClient:
    """Upload or read through a loopback service using the configured token scope."""

    def __init__(self, base_url: str, token_file: Path, timeout_seconds: float = 30) -> None:
        self._base_url = _validate_base_url(base_url)
        if not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise SourceMediaClientError("invalid_configuration")
        self._timeout_seconds = float(timeout_seconds)
        self._token = _load_token(Path(token_file))
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def upload(
        self,
        idempotency_key: str,
        data: bytes,
        *,
        kind: str,
        content_type: str,
        filename: str,
    ) -> dict[str, Any]:
        if (
            not isinstance(idempotency_key, str)
            or not _KEY.fullmatch(idempotency_key)
            or not isinstance(data, bytes)
            or not 1 <= len(data) <= MAX_OBJECT_BYTES
            or kind not in _KINDS
            or not isinstance(content_type, str)
            or not isinstance(filename, str)
        ):
            raise SourceMediaClientError("invalid_upload")
        try:
            filename_header = urllib.parse.quote_from_bytes(filename.encode("utf-8"), safe="")
        except UnicodeEncodeError:
            raise SourceMediaClientError("invalid_upload") from None
        request = urllib.request.Request(
            f"{self._base_url}/v1/objects",
            data=data,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/octet-stream",
                "X-Idempotency-Key": idempotency_key,
                "X-Media-Kind": kind,
                "X-Media-Content-Type": content_type,
                "X-Media-Filename": filename_header,
            },
            method="POST",
        )
        response = self._request(request, MAX_RESPONSE_BYTES)
        try:
            result = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise SourceMediaClientError("invalid_response") from None
        if not isinstance(result, dict) or set(result) != {
            "ref", "sha256", "kind", "content_type", "size_bytes", "filename", "durable"
        }:
            raise SourceMediaClientError("invalid_response")
        if (
            not isinstance(result["ref"], str)
            or not _REF.fullmatch(result["ref"])
            or not isinstance(result["sha256"], str)
            or result["sha256"] != hashlib.sha256(data).hexdigest()
            or result["kind"] != kind
            or not isinstance(result["content_type"], str)
            or not isinstance(result["size_bytes"], int)
            or result["size_bytes"] != len(data)
            or not isinstance(result["filename"], str)
            or not result["filename"]
            or result["durable"] is not True
        ):
            raise SourceMediaClientError("invalid_response")
        return result

    def download(self, ref: str) -> MediaDownload:
        if not isinstance(ref, str) or not _REF.fullmatch(ref):
            raise SourceMediaClientError("invalid_reference")
        encoded_ref = urllib.parse.quote(ref, safe="")
        request = urllib.request.Request(
            f"{self._base_url}/v1/objects/{encoded_ref}",
            headers={"Authorization": f"Bearer {self._token}"},
            method="GET",
        )
        response, headers = self._request_with_headers(request, MAX_OBJECT_BYTES + 1)
        if len(response) > MAX_OBJECT_BYTES:
            raise SourceMediaClientError("invalid_response")
        digest = headers.get("X-Media-Sha256", "")
        kind = headers.get("X-Media-Kind", "")
        content_type = headers.get_content_type().lower()
        encoded_filename = headers.get("X-Media-Filename", "")
        try:
            filename = urllib.parse.unquote_to_bytes(encoded_filename).decode("utf-8")
            size = int(headers.get("X-Media-Size-Bytes", "-1"))
        except (UnicodeDecodeError, ValueError):
            raise SourceMediaClientError("invalid_response") from None
        if (
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            or hashlib.sha256(response).hexdigest() != digest
            or kind not in _KINDS
            or not content_type
            or not filename
            or size != len(response)
        ):
            raise SourceMediaClientError("invalid_response")
        return MediaDownload(
            data=response,
            content_type=content_type,
            filename=filename,
            kind=kind,
            sha256=digest,
        )

    def _request(self, request: urllib.request.Request, maximum: int) -> bytes:
        body, _headers = self._request_with_headers(request, maximum)
        return body

    def _request_with_headers(
        self,
        request: urllib.request.Request,
        maximum: int,
    ) -> tuple[bytes, Any]:
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                body = response.read(maximum + 1)
                headers = response.headers
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise SourceMediaClientError(_category_for_status(status)) from None
        except (TimeoutError, socket.timeout):
            raise SourceMediaClientError("timeout") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise SourceMediaClientError("network_error") from None
        if len(body) > maximum:
            raise SourceMediaClientError("invalid_response")
        return body, headers
