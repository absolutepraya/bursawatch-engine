"""Durable source-media idempotency metadata and private object coordination."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from pathlib import Path

from .models import (
    IdempotencyConflict,
    MediaMetadata,
    ObjectNotFound,
    StorageError,
    StoredMedia,
    metadata_from_row,
    object_path_for_ref,
    ref_for_idempotency_key,
    validate_upload,
)
from .provider import StorageProvider


class MediaStore:
    def __init__(self, state_path: Path, provider: StorageProvider) -> None:
        self.state_path = Path(state_path)
        self.provider = provider
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_path.parent, 0o700)
        self._db = sqlite3.connect(self.state_path, timeout=30, check_same_thread=False)
        os.chmod(self.state_path, 0o600)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS media_objects (
                key_digest TEXT PRIMARY KEY,
                ref TEXT NOT NULL UNIQUE,
                request_digest TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                kind TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL CHECK(size_bytes > 0 AND size_bytes <= 8388608),
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS media_objects_ref_idx ON media_objects(ref);
            """
        )
        self._lock = threading.RLock()

    def upload(
        self,
        idempotency_key: str,
        data: bytes,
        *,
        kind: str,
        content_type: str,
        filename: str,
    ) -> MediaMetadata:
        key_digest, data, kind, content_type, filename, request_digest = validate_upload(
            idempotency_key=idempotency_key,
            data=data,
            kind=kind,
            content_type=content_type,
            filename=filename,
        )
        content_digest = hashlib.sha256(data).hexdigest()
        ref = ref_for_idempotency_key(idempotency_key)
        object_path = object_path_for_ref(ref)
        idempotency_metadata = json.dumps(
            {
                "request_digest": request_digest,
                "sha256": content_digest,
                "kind": kind,
                "content_type": content_type,
                "size_bytes": len(data),
                "filename": filename,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM media_objects WHERE key_digest = ?", (key_digest,)
            ).fetchone()
            if row is not None:
                if row["request_digest"] != request_digest:
                    raise IdempotencyConflict("upload key conflicts with an existing payload")
                return metadata_from_row(row)

            self.provider.put_if_absent(
                object_path,
                data,
                content_type,
                content_digest,
                idempotency_metadata,
            )
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    """INSERT INTO media_objects
                       (key_digest, ref, request_digest, sha256, kind, content_type, size_bytes, filename)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (key_digest, ref, request_digest, content_digest, kind, content_type, len(data), filename),
                )
                self._db.commit()
            except sqlite3.IntegrityError:
                self._db.rollback()
                existing = self._db.execute(
                    "SELECT * FROM media_objects WHERE key_digest = ?", (key_digest,)
                ).fetchone()
                if existing is None or existing["request_digest"] != request_digest:
                    raise IdempotencyConflict("upload key conflicts with an existing payload") from None
                return metadata_from_row(existing)
            except Exception:
                self._db.rollback()
                raise
            row = self._db.execute(
                "SELECT * FROM media_objects WHERE key_digest = ?", (key_digest,)
            ).fetchone()
            return metadata_from_row(row)

    def download(self, ref: str) -> StoredMedia:
        object_path = object_path_for_ref(ref)
        with self._lock:
            row = self._db.execute("SELECT * FROM media_objects WHERE ref = ?", (ref,)).fetchone()
            if row is None:
                raise ObjectNotFound("media reference not found")
            metadata = metadata_from_row(row)
            data = self.provider.get(object_path)
        if data is None:
            raise StorageError("stored media object is missing")
        if len(data) != metadata.size_bytes or hashlib.sha256(data).hexdigest() != metadata.sha256:
            raise StorageError("stored media object failed integrity validation")
        return StoredMedia(metadata=metadata, data=data)

    def close(self) -> None:
        with self._lock:
            self._db.close()
