from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from source_media.api import create_app
from source_media.config import Config
from source_media.models import IdempotencyConflict, ObjectNotFound, StorageError, object_path_for_ref
from source_media.store import MediaStore


class MemoryProvider:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0
        self.get_calls = 0

    def put_if_absent(
        self,
        object_path: str,
        data: bytes,
        content_type: str,
        sha256: str,
        idempotency_metadata: bytes,
    ) -> None:
        self.put_calls += 1
        current = self.objects.get(object_path)
        if current is None:
            self.objects[object_path] = data
        elif hashlib.sha256(current).hexdigest() != sha256:
            raise IdempotencyConflict("upload key conflicts with an existing payload")
        marker = f"{object_path}.meta.json"
        previous_metadata = self.objects.get(marker)
        if previous_metadata is not None and previous_metadata != idempotency_metadata:
            raise IdempotencyConflict("upload key conflicts with an existing payload")
        self.objects[marker] = idempotency_metadata

    def get(self, object_path: str) -> bytes | None:
        self.get_calls += 1
        return self.objects.get(object_path)


def setup_service(tmp_path: Path):
    provider = MemoryProvider()
    config = Config(
        port=9130,
        upload_token="upload-secret",
        read_token="read-secret",
        state_path=tmp_path / "state" / "media.sqlite3",
        supabase_url="https://unit.test",
        bucket="private-bucket",
        service_role_key_path=tmp_path / "key",
    )
    store = MediaStore(config.state_path, provider)
    return TestClient(create_app(config, store)), store, provider


def upload(client, *, token="upload-secret", key="tg:channel:1:message:2:media:0", data=b"\xff\xd8\xffchart"):
    return client.post(
        "/v1/objects",
        content=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "X-Idempotency-Key": key,
            "X-Media-Kind": "image",
            "X-Media-Content-Type": "image/jpeg",
            "X-Media-Filename": "chart.jpg",
        },
    )


def test_upload_and_private_download_use_distinct_scoped_tokens(tmp_path):
    client, _store, provider = setup_service(tmp_path)
    assert upload(client, token="read-secret").status_code == 401
    accepted = upload(client)
    assert accepted.status_code == 201
    metadata = accepted.json()
    assert set(metadata) == {"ref", "sha256", "kind", "content_type", "size_bytes", "filename", "durable"}
    assert metadata["ref"].count("-") == 4
    assert metadata["sha256"] == hashlib.sha256(b"\xff\xd8\xffchart").hexdigest()
    assert metadata["content_type"] == "image/jpeg"
    assert metadata["size_bytes"] == len(b"\xff\xd8\xffchart")
    assert metadata["durable"] is True
    assert provider.put_calls == 1

    path = f"/v1/objects/{metadata['ref']}"
    assert client.get(path, headers={"Authorization": "Bearer upload-secret"}).status_code == 401
    downloaded = client.get(path, headers={"Authorization": "Bearer read-secret"})
    assert downloaded.status_code == 200
    assert downloaded.content == b"\xff\xd8\xffchart"
    assert downloaded.headers["content-type"] == "image/jpeg"
    assert downloaded.headers["x-media-filename"] == "chart.jpg"
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert "url" not in downloaded.headers


def test_same_key_same_payload_is_idempotent_and_changed_payload_conflicts(tmp_path):
    client, _store, provider = setup_service(tmp_path)
    first = upload(client)
    retry = upload(client)
    assert first.status_code == retry.status_code == 201
    assert first.json() == retry.json()
    assert provider.put_calls == 1

    changed = upload(client, data=b"\xff\xd8\xffdifferent")
    assert changed.status_code == 409
    assert provider.put_calls == 1

    changed_metadata = client.post(
        "/v1/objects",
        content=b"\xff\xd8\xffchart",
        headers={
            "Authorization": "Bearer upload-secret",
            "Content-Type": "application/octet-stream",
            "X-Idempotency-Key": "tg:channel:1:message:2:media:0",
            "X-Media-Kind": "image",
            "X-Media-Content-Type": "image/jpeg",
            "X-Media-Filename": "renamed.jpg",
        },
    )
    assert changed_metadata.status_code == 409


@pytest.mark.parametrize(
    ("kind", "content_type", "data"),
    [
        ("image", "image/png", b"\xff\xd8\xffnot-png"),
        ("video", "image/jpeg", b"\xff\xd8\xffimage"),
        ("document", "application/pdf", b"plain text"),
        ("image", "image/jpeg", b"\x89PNG\r\n\x1a\nwrong-type"),
    ],
)
def test_type_and_signature_mismatch_are_rejected_before_storage(tmp_path, kind, content_type, data):
    client, _store, provider = setup_service(tmp_path)
    response = client.post(
        "/v1/objects",
        content=data,
        headers={
            "Authorization": "Bearer upload-secret",
            "Content-Type": "application/octet-stream",
            "X-Idempotency-Key": "source:1",
            "X-Media-Kind": kind,
            "X-Media-Content-Type": content_type,
            "X-Media-Filename": "file.bin",
        },
    )
    assert response.status_code == 422
    assert provider.put_calls == 0


def test_upload_size_limit_is_enforced_without_storage_call(tmp_path):
    client, _store, provider = setup_service(tmp_path)
    too_large = b"\xff\xd8\xff" + b"x" * (8 * 1024 * 1024)
    response = upload(client, data=too_large)
    assert response.status_code == 422
    assert provider.put_calls == 0


def test_filename_is_safely_normalized_to_control_plane_metadata_contract(tmp_path):
    client, _store, _provider = setup_service(tmp_path)
    response = client.post(
        "/v1/objects",
        content=b"\xff\xd8\xffchart",
        headers={
            "Authorization": "Bearer upload-secret",
            "Content-Type": "application/octet-stream",
            "X-Idempotency-Key": "source:filename",
            "X-Media-Kind": "image",
            "X-Media-Content-Type": "image/jpeg",
            "X-Media-Filename": "chart image.jpg",
        },
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "chart_image.jpg"


def test_retry_recovers_storage_object_uploaded_before_ledger_commit(tmp_path):
    _client, store, provider = setup_service(tmp_path)
    data = b"\xff\xd8\xffchart"
    first = store.upload(
        "source:crash-window",
        data,
        kind="image",
        content_type="image/jpeg",
        filename="chart.jpg",
    )
    assert provider.objects[object_path_for_ref(first.ref)] == data
    assert store.upload(
        "source:crash-window",
        data,
        kind="image",
        content_type="image/jpeg",
        filename="chart.jpg",
    ) == first
    assert provider.put_calls == 1


def test_provider_marker_detects_metadata_conflict_after_local_ledger_loss(tmp_path):
    _client, first_store, provider = setup_service(tmp_path)
    data = b"\xff\xd8\xffchart"
    original = first_store.upload(
        "source:metadata-crash-window",
        data,
        kind="image",
        content_type="image/jpeg",
        filename="chart.jpg",
    )
    second_store = MediaStore(tmp_path / "recovered.sqlite3", provider)
    assert second_store.upload(
        "source:metadata-crash-window",
        data,
        kind="image",
        content_type="image/jpeg",
        filename="chart.jpg",
    ) == original
    with pytest.raises(IdempotencyConflict):
        second_store.upload(
            "source:metadata-crash-window",
            data,
            kind="image",
            content_type="image/jpeg",
            filename="renamed.jpg",
        )


def test_preexisting_deterministic_path_with_other_bytes_conflicts(tmp_path):
    _client, store, provider = setup_service(tmp_path)
    first_key = "source:conflict-window"
    from source_media.models import ref_for_idempotency_key

    path = object_path_for_ref(ref_for_idempotency_key(first_key))
    provider.objects[path] = b"\xff\xd8\xffother"
    with pytest.raises(IdempotencyConflict):
        store.upload(
            first_key,
            b"\xff\xd8\xffchart",
            kind="image",
            content_type="image/jpeg",
            filename="chart.jpg",
        )


def test_download_requires_ledger_reference_and_checks_storage_integrity(tmp_path):
    client, store, provider = setup_service(tmp_path)
    assert client.get(
        "/v1/objects/123e4567-e89b-12d3-a456-426614174000",
        headers={"Authorization": "Bearer read-secret"},
    ).status_code == 404
    metadata = upload(client).json()
    provider.objects[object_path_for_ref(metadata["ref"])] = b"\xff\xd8\xfftampered"
    with pytest.raises(StorageError):
        store.download(metadata["ref"])
    with pytest.raises(ObjectNotFound):
        store.download("123e4567-e89b-12d3-a456-426614174000")
    assert (tmp_path / "state" / "media.sqlite3").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "state").stat().st_mode & 0o777 == 0o700
