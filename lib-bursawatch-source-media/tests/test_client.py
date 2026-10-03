from __future__ import annotations

import hashlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "service-bursawatch-source-media" / "bin"))

from bursawatch_source_media import SourceMediaClient, SourceMediaClientError
from source_media.api import create_app
from source_media.config import Config
from source_media.store import MediaStore


class MemoryProvider:
    def __init__(self):
        self.objects = {}

    def put_if_absent(self, object_path, data, content_type, sha256, idempotency_metadata):
        if object_path in self.objects and self.objects[object_path] != data:
            from source_media.models import IdempotencyConflict
            raise IdempotencyConflict("upload key conflicts with an existing payload")
        marker = f"{object_path}.meta.json"
        if marker in self.objects and self.objects[marker] != idempotency_metadata:
            from source_media.models import IdempotencyConflict
            raise IdempotencyConflict("upload key conflicts with an existing payload")
        self.objects[object_path] = data
        self.objects[marker] = idempotency_metadata

    def get(self, object_path):
        return self.objects.get(object_path)


class ApiBridge:
    def __init__(self, app):
        self.asgi = TestClient(app)
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                headers = {name: value for name, value in self.headers.items()}
                result = bridge.asgi.post(self.path, content=body, headers=headers)
                self._write(result.status_code, result.content, result.headers)

            def do_GET(self):  # noqa: N802
                headers = {name: value for name, value in self.headers.items()}
                result = bridge.asgi.get(self.path, headers=headers)
                self._write(result.status_code, result.content, result.headers)

            def _write(self, status, body, headers):
                self.send_response(status)
                for name in ("content-type", "cache-control", "content-disposition", "x-media-sha256", "x-media-kind", "x-media-filename", "x-media-size-bytes"):
                    if name in headers:
                        self.send_header(name, headers[name])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.asgi.close()


@pytest.fixture
def clients(tmp_path):
    config = Config(
        port=9130,
        upload_token="upload-secret",
        read_token="read-secret",
        state_path=tmp_path / "state.sqlite3",
        supabase_url="https://unit.test",
        bucket="private-bucket",
        service_role_key_path=tmp_path / "key",
    )
    store = MediaStore(config.state_path, MemoryProvider())
    bridge = ApiBridge(create_app(config, store))
    upload_token = tmp_path / "upload-token"
    read_token = tmp_path / "read-token"
    upload_token.write_text("upload-secret\n", encoding="utf-8")
    read_token.write_text("read-secret\n", encoding="utf-8")
    upload_token.chmod(0o600)
    read_token.chmod(0o600)
    try:
        yield bridge.base_url, upload_token, read_token
    finally:
        bridge.close()
        store.close()


def test_source_media_client_upload_download_and_token_scope(clients):
    base_url, upload_token, read_token = clients
    uploader = SourceMediaClient(base_url, upload_token)
    reader = SourceMediaClient(base_url, read_token)
    data = b"\xff\xd8\xffchart-bytes"

    metadata = uploader.upload(
        "telegram:channel:1:message:2:attachment:0",
        data,
        kind="image",
        content_type="image/jpeg",
        filename="chart image.jpg",
    )
    assert metadata["sha256"] == hashlib.sha256(data).hexdigest()
    assert metadata["size_bytes"] == len(data)
    assert metadata["durable"] is True
    assert len(metadata["ref"]) == 36
    downloaded = reader.download(metadata["ref"])
    assert downloaded.data == data
    assert downloaded.content_type == "image/jpeg"
    assert downloaded.filename == "chart_image.jpg"
    assert downloaded.kind == "image"
    assert downloaded.sha256 == metadata["sha256"]

    with pytest.raises(SourceMediaClientError) as upload_scope:
        reader.upload("source:2", data, kind="image", content_type="image/jpeg", filename="a.jpg")
    assert upload_scope.value.category == "unauthorized"
    with pytest.raises(SourceMediaClientError) as read_scope:
        uploader.download(metadata["ref"])
    assert read_scope.value.category == "unauthorized"


@pytest.mark.parametrize(
    "base_url",
    [
        "https://127.0.0.1:9130",
        "http://example.com:9130",
        "http://127.0.0.1:9130/path",
        "http://user:secret@127.0.0.1:9130",
        "http://127.0.0.1:9130?token=value",
    ],
)
def test_client_rejects_non_loopback_or_credential_bearing_urls(tmp_path, base_url):
    token = tmp_path / "token"
    token.write_text("private-token\n", encoding="utf-8")
    token.chmod(0o600)
    with pytest.raises(SourceMediaClientError) as error:
        SourceMediaClient(base_url, token)
    assert error.value.category == "invalid_configuration"


def test_client_requires_private_regular_token_file(tmp_path):
    token = tmp_path / "token"
    token.write_text("private-token\n", encoding="utf-8")
    token.chmod(0o644)
    with pytest.raises(SourceMediaClientError) as error:
        SourceMediaClient("http://127.0.0.1:9130", token)
    assert error.value.category == "invalid_token_file"


def test_client_rejects_malformed_reference_before_network(clients):
    base_url, _upload_token, read_token = clients
    reader = SourceMediaClient(base_url, read_token)
    with pytest.raises(SourceMediaClientError) as error:
        reader.download("https://storage.example/public/object")
    assert error.value.category == "invalid_reference"


def test_download_optional_bounds_preserve_existing_calls(clients):
    base_url, upload_token, read_token = clients
    uploader = SourceMediaClient(base_url, upload_token)
    reader = SourceMediaClient(base_url, read_token)
    data = b"\xff\xd8\xffbounded image bytes"
    metadata = uploader.upload("bounded:1", data, kind="image", content_type="image/jpeg", filename="chart.jpg")
    assert reader.download(metadata["ref"]).data == data
    assert reader.download(metadata["ref"], max_bytes=len(data), timeout_seconds=1).data == data
    with pytest.raises(SourceMediaClientError):
        reader.download(metadata["ref"], max_bytes=len(data)-1)
