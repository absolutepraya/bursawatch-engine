from __future__ import annotations

import json
import sys
import threading
import uuid
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "bin"))


def _parse_operation(content_type: str, body: bytes) -> tuple[dict[str, Any], tuple[Any, ...]]:
    from bursawatch_discord_delivery.models import Attachment, OperationIntent

    envelope = BytesParser(policy=default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: "
        + content_type.encode("ascii")
        + b"\r\n\r\n"
        + body
    )
    operation: dict[str, Any] | None = None
    attachments = []
    if envelope.is_multipart():
        for part in envelope.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            data = part.get_payload(decode=True) or b""
            if field_name == "operation":
                operation = json.loads(data)
            elif field_name == "attachments":
                attachments.append(
                    Attachment(
                        filename=part.get_filename(),
                        mime_type=part.get_content_type(),
                        data=data,
                    )
                )
    elif content_type.startswith("application/json"):
        document = json.loads(body)
        operation = document["operation"]
    if operation is None:
        raise AssertionError("fake server received no operation part")
    intent = OperationIntent(
        key=operation["key"],
        kind=operation["kind"],
        ordering_key=operation["ordering_key"],
        target=operation["target"],
        payload=operation["payload"],
        attachments=tuple(attachments),
        reconcile_before_first_create=operation.get("reconcile_before_first_create", False),
        legacy_nonce=operation.get("legacy_nonce"),
    )
    return operation, (intent,)


def _parse_adoption(content_type: str, body: bytes) -> tuple[dict[str, Any], tuple[Any, ...]]:
    from bursawatch_discord_delivery.models import Attachment, OperationIntent

    document: dict[str, Any] | None = None
    attachments = []
    if content_type.lower().startswith("multipart/form-data;"):
        envelope = BytesParser(policy=default).parsebytes(
            b"MIME-Version: 1.0\r\nContent-Type: "
            + content_type.encode("ascii")
            + b"\r\n\r\n"
            + body
        )
        if not envelope.is_multipart():
            raise AssertionError("fake server received invalid adoption multipart")
        for part in envelope.iter_parts():
            name = part.get_param("name", header="content-disposition")
            data = part.get_payload(decode=True) or b""
            if name == "adoption":
                if document is not None:
                    raise AssertionError("fake server received duplicate adoption envelope")
                document = json.loads(data)
            elif name == "attachments":
                attachments.append(Attachment(part.get_filename(), part.get_content_type(), data))
            else:
                raise AssertionError("fake server received unexpected adoption part")
    else:
        document = json.loads(body)
    if not isinstance(document, dict):
        raise AssertionError("fake server received no adoption envelope")
    operation = document["operation"]
    intent = OperationIntent(
        key=operation["key"],
        kind=operation["kind"],
        ordering_key=operation["ordering_key"],
        target=operation["target"],
        payload=operation["payload"],
        attachments=tuple(attachments),
        reconcile_before_first_create=operation.get("reconcile_before_first_create", False),
        legacy_nonce=operation.get("legacy_nonce"),
    )
    return document, (intent, tuple(attachments))


def _make_server(state: dict[str, Any]) -> tuple[ThreadingHTTPServer, threading.Thread]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _json(self, status: int, value: Any) -> None:
            self._send(status, json.dumps(value).encode("utf-8"), {"Content-Type": "application/json"})

        def _handle(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            record = {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
            with state["lock"]:
                state["requests"].append(record)
                override = state["overrides"].pop(0) if state["overrides"] else None
            if override is not None:
                expected_method = override.get("method")
                expected_path = override.get("path")
                if expected_method and expected_method != self.command:
                    raise AssertionError(f"unexpected {self.command} while waiting for {expected_method}")
                if expected_path and expected_path not in self.path:
                    raise AssertionError(f"unexpected request path {self.path!r}")
                if override.get("drop"):
                    self.close_connection = True
                    return
                self._send(override["status"], override.get("body", b""), override.get("headers", {}))
                return

            if self.command == "POST" and self.path == "/v1/operations":
                operation, (intent,) = _parse_operation(self.headers.get("Content-Type", ""), body)
                with state["lock"]:
                    existing = state["accepted"].get(intent.key)
                    if existing and existing["digest"] != intent.digest:
                        self._json(409, {"detail": "conflict body must not escape"})
                        return
                    if existing is None:
                        existing = {
                            "id": str(uuid.uuid4()),
                            "key": intent.key,
                            "digest": intent.digest,
                            "status": "pending",
                            "receipt": None,
                        }
                        state["accepted"][intent.key] = existing
                    state["last_operation"] = operation
                    drop = state.pop("drop_after_accept", False)
                if drop:
                    self.close_connection = True
                    return
                self._json(202, existing)
                return

            if self.command == "POST" and self.path == "/v1/operations/adopt":
                document, (intent, attachments) = _parse_adoption(self.headers.get("Content-Type", ""), body)
                if document.get("payload_digest") != intent.digest:
                    self._json(422, {"detail": "digest mismatch"})
                    return
                operation = document["operation"]
                action = document["action"]
                status = "delivered" if action == "completed" else "pending_reconciliation"
                import_key = (action, intent.key)
                record = {
                    "id": state["adopted"].get(import_key, {}).get("id", str(uuid.uuid4())),
                    "key": operation["key"],
                    "digest": intent.digest,
                    "status": status,
                    "receipt": document.get("receipt"),
                }
                existing = state["adopted"].get(import_key)
                if existing and existing["digest"] != intent.digest:
                    self._json(409, {"detail": "adoption conflict"})
                    return
                state["adopted"][import_key] = record
                state["last_adoption"] = document
                state["last_adoption_attachments"] = attachments
                state["last_adoption_token"] = self.headers.get("Authorization")
                self._json(202, record)
                return

            if self.command == "GET" and self.path.startswith("/v1/operations/by-key/"):
                key = unquote(self.path[len("/v1/operations/by-key/") :])
                with state["lock"]:
                    sequence = state["status_sequences"].get(key)
                    if sequence:
                        record = sequence.pop(0)
                        self._json(200, record)
                        return
                    record = state["accepted"].get(key)
                if record is None:
                    self._json(404, {"detail": "missing operation"})
                else:
                    self._json(200, record)
                return

            if self.command == "POST" and self.path == "/v1/queries":
                state["last_query"] = json.loads(body)
                self._json(200, state["query_response"])
                return

            self._json(404, {"detail": "fake route not found"})

        do_GET = _handle
        do_POST = _handle

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


@dataclass
class FakeOwner:
    base_url: str
    state: dict[str, Any]
    server: ThreadingHTTPServer
    thread: threading.Thread

    def respond(
        self,
        status: int,
        body: bytes = b"{}",
        *,
        headers: dict[str, str] | None = None,
        method: str | None = None,
        path: str | None = None,
        drop: bool = False,
    ) -> None:
        with self.state["lock"]:
            self.state["overrides"].append(
                {"status": status, "body": body, "headers": headers or {},
                 "method": method, "path": path, "drop": drop}
            )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def _start_owner() -> FakeOwner:
    state: dict[str, Any] = {
        "lock": threading.Lock(),
        "requests": [],
        "overrides": [],
        "accepted": {},
        "adopted": {},
        "status_sequences": {},
        "query_response": [],
    }
    server, thread = _make_server(state)
    return FakeOwner(f"http://127.0.0.1:{server.server_port}", state, server, thread)


@pytest.fixture
def fake_owner() -> Any:
    owner = _start_owner()
    try:
        yield owner
    finally:
        owner.close()


@pytest.fixture
def fake_capture_server() -> Any:
    state: dict[str, Any] = {
        "lock": threading.Lock(),
        "requests": [],
        "overrides": [],
        "accepted": {},
        "adopted": {},
        "status_sequences": {},
        "query_response": [],
    }
    server, thread = _make_server(state)
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "delivery-client.token"
    path.write_text("test-client-token\n", encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def admin_token_file(tmp_path: Path) -> Path:
    path = tmp_path / "delivery-admin.token"
    path.write_text("test-admin-token\n", encoding="utf-8")
    path.chmod(0o600)
    return path
