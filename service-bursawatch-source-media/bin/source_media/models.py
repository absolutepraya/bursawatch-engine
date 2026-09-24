"""Media metadata validation and stable reference models."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Any


MAX_OBJECT_BYTES = 8 * 1024 * 1024
KINDS = frozenset({"image", "video", "document", "audio"})
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
MEDIA_REF = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
CONTENT_TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "audio/x-wav": "audio/wav",
    "application/x-pdf": "application/pdf",
    "application/x-zip-compressed": "application/zip",
}


class ValidationError(ValueError):
    """A source-media input failed the service contract."""


class IdempotencyConflict(RuntimeError):
    """An immutable upload key was reused with different content or metadata."""


class ObjectNotFound(LookupError):
    """A requested reference is not present in the service ledger."""


class StorageError(RuntimeError):
    """The private storage provider failed without exposing provider details."""


@dataclass(frozen=True)
class MediaMetadata:
    ref: str
    sha256: str
    kind: str
    content_type: str
    size_bytes: int
    filename: str
    durable: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "sha256": self.sha256,
            "kind": self.kind,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "filename": self.filename,
            "durable": self.durable,
        }


@dataclass(frozen=True)
class StoredMedia:
    metadata: MediaMetadata
    data: bytes


def normalize_content_type(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("invalid content type")
    media_type = value.split(";", 1)[0].strip().lower()
    if "/" not in media_type or any(character.isspace() for character in media_type):
        raise ValidationError("invalid content type")
    return CONTENT_TYPE_ALIASES.get(media_type, media_type)


def normalize_filename(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("invalid filename")
    filename = unicodedata.normalize("NFKD", value.strip())
    if not filename or "/" in filename or "\\" in filename:
        raise ValidationError("invalid filename")
    safe = "".join(character if character.isascii() and (character.isalnum() or character in "._-") else "_" for character in filename)
    safe = re.sub(r"_+", "_", safe).strip("._-")
    if not safe or not safe[0].isalnum():
        safe = f"file_{safe}" if safe else "file"
    return safe[:128]


def _is_plain_text(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if "\x00" in text:
        return False
    return all(character.isprintable() or character in "\r\n\t" for character in text)


def sniff_content_type(data: bytes, kind: str) -> str:
    if kind not in KINDS:
        raise ValidationError("invalid media kind")
    if not data:
        raise ValidationError("empty media object")

    if kind == "image":
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp"
        if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
            return "image/avif"
    elif kind == "video":
        if data.startswith(b"\x1aE\xdf\xa3"):
            return "video/webm"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            if data[8:12] == b"qt  ":
                return "video/quicktime"
            return "video/mp4"
    elif kind == "audio":
        if data.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
            return "audio/mpeg"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
            return "audio/wav"
        if data.startswith(b"OggS"):
            return "audio/ogg"
        if data.startswith(b"fLaC"):
            return "audio/flac"
        if len(data) >= 12 and data[4:8] == b"ftyp":
            return "audio/mp4"
    elif kind == "document":
        if data.startswith(b"%PDF-"):
            return "application/pdf"
        if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            return "application/zip"
        if _is_plain_text(data):
            return "text/plain"

    raise ValidationError("media bytes do not match a supported kind")


def validate_upload(
    *,
    idempotency_key: str,
    data: bytes,
    kind: str,
    content_type: str,
    filename: str,
) -> tuple[str, bytes, str, str, str, str]:
    if not isinstance(idempotency_key, str) or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise ValidationError("invalid idempotency key")
    if not isinstance(data, bytes) or not data or len(data) > MAX_OBJECT_BYTES:
        raise ValidationError("media object must be between 1 byte and 8 MiB")
    if kind not in KINDS:
        raise ValidationError("invalid media kind")
    canonical_type = normalize_content_type(content_type)
    detected_type = sniff_content_type(data, kind)
    if canonical_type != detected_type:
        raise ValidationError("declared content type does not match media bytes")
    safe_filename = normalize_filename(filename)
    content_digest = hashlib.sha256(data).hexdigest()
    request_digest = hashlib.sha256(
        "\0".join((kind, canonical_type, safe_filename, str(len(data)), content_digest)).encode("utf-8")
    ).hexdigest()
    key_digest = hashlib.sha256(b"bursawatch-source-media-v1\0" + idempotency_key.encode("utf-8")).hexdigest()
    return key_digest, data, kind, canonical_type, safe_filename, request_digest


def metadata_from_row(row: Any) -> MediaMetadata:
    return MediaMetadata(
        ref=row["ref"],
        sha256=row["sha256"],
        kind=row["kind"],
        content_type=row["content_type"],
        size_bytes=int(row["size_bytes"]),
        filename=row["filename"],
        durable=True,
    )


def object_path_for_ref(ref: str) -> str:
    if not isinstance(ref, str) or not MEDIA_REF.fullmatch(ref):
        raise ValidationError("invalid media reference")
    return f"source/v1/{ref[:2]}/{ref}"


def ref_for_idempotency_key(idempotency_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bursawatch-source-media:v1:{idempotency_key}"))
