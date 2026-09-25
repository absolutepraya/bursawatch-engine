"""Injected storage-provider contract and private Supabase REST adapter."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from .models import IdempotencyConflict, MAX_OBJECT_BYTES, StorageError


class StorageProvider(Protocol):
    def put_if_absent(
        self,
        object_path: str,
        data: bytes,
        content_type: str,
        sha256: str,
        idempotency_metadata: bytes,
    ) -> None: ...

    def get(self, object_path: str) -> bytes | None: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class SupabaseStorageProvider:
    """Use the authenticated private-object API without creating public URLs."""

    def __init__(self, project_url: str, bucket: str, service_role_key: str) -> None:
        parts = urllib.parse.urlsplit(project_url)
        if parts.scheme != "https" or not parts.hostname or not service_role_key:
            raise ValueError("invalid private storage configuration")
        self._base = f"{parts.scheme}://{parts.netloc}/storage/v1/object"
        self._bucket = urllib.parse.quote(bucket, safe="")
        self._key = service_role_key
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
        )

    def _url(self, object_path: str, *, authenticated: bool = False) -> str:
        path = urllib.parse.quote(object_path, safe="/")
        scope = "/authenticated" if authenticated else ""
        return f"{self._base}{scope}/{self._bucket}/{path}"

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        result = {"apikey": self._key, "Authorization": f"Bearer {self._key}"}
        if content_type:
            result["Content-Type"] = content_type
        return result

    @staticmethod
    def _is_missing(error: urllib.error.HTTPError, body: bytes) -> bool:
        if error.code == 404:
            return True
        try:
            details = json.loads(body[:4096])
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        if not isinstance(details, dict):
            return False
        detail = " ".join(str(details.get(key, "")) for key in ("error", "message")).lower()
        return "object not found" in detail or "not found" in detail

    def get(self, object_path: str) -> bytes | None:
        request = urllib.request.Request(self._url(object_path, authenticated=True), headers=self._headers())
        try:
            with self._opener.open(request, timeout=30) as response:
                data = response.read(MAX_OBJECT_BYTES + 1)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(4096)
            finally:
                exc.close()
            if self._is_missing(exc, body):
                return None
            raise StorageError("private storage read failed") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise StorageError("private storage read failed") from None
        if len(data) > MAX_OBJECT_BYTES:
            raise StorageError("private storage object exceeds service limit")
        return data

    def _put_one_if_absent(self, object_path: str, data: bytes, content_type: str, digest: str) -> None:
        request = urllib.request.Request(
            self._url(object_path),
            data=data,
            headers={**self._headers(content_type), "x-upsert": "false"},
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                if response.status in {200, 201, 204}:
                    return
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(4096)
            finally:
                exc.close()
            existing = self.get(object_path)
            if existing is not None:
                if hashlib.sha256(existing).hexdigest() == digest:
                    return
                raise IdempotencyConflict("upload key conflicts with an existing payload") from None
            if self._is_missing(exc, body):
                raise StorageError("private storage upload failed") from None
            raise StorageError("private storage upload failed") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            # The request may have reached Storage despite a connection failure.
            existing = self.get(object_path)
            if existing is not None and hashlib.sha256(existing).hexdigest() == digest:
                return
            if existing is not None:
                raise IdempotencyConflict("upload key conflicts with an existing payload") from None
            raise StorageError("private storage upload failed") from None
        raise StorageError("private storage upload failed")

    def put_if_absent(
        self,
        object_path: str,
        data: bytes,
        content_type: str,
        sha256: str,
        idempotency_metadata: bytes,
    ) -> None:
        marker_path = f"{object_path}.meta.json"
        marker_digest = hashlib.sha256(idempotency_metadata).hexdigest()
        # Detect an orphaned payload before writing a new marker. This avoids
        # binding a key to a request that conflicts with an earlier object.
        existing = self.get(object_path)
        if existing is not None and hashlib.sha256(existing).hexdigest() != sha256:
            raise IdempotencyConflict("upload key conflicts with an existing payload")
        # Persist request metadata first so changed metadata is detectable if
        # the process exits before its local SQLite ledger commits.
        self._put_one_if_absent(marker_path, idempotency_metadata, "application/json", marker_digest)
        self._put_one_if_absent(object_path, data, content_type, sha256)
