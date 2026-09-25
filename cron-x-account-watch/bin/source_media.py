"""Resolve durable X source images without persisting their provider locators."""
from __future__ import annotations

import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


REF_PREFIX = "source-media-ref:"
REF_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
SUFFIX = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def reference_url(ref: str) -> str:
    if not isinstance(ref, str) or not REF_RE.fullmatch(ref):
        raise ValueError("source image reference is invalid")
    return REF_PREFIX + ref


def reference_id(url: str) -> str | None:
    if not isinstance(url, str) or not url.startswith(REF_PREFIX):
        return None
    return reference_url(url[len(REF_PREFIX):])[len(REF_PREFIX):]


def client_from_environment():
    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    token = os.environ.get("BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE")
    if not url or not token:
        raise RuntimeError("Source Media Owner read access is unavailable")
    root = Path(__file__).resolve().parents[2] / "lib-bursawatch-source-media" / "bin"
    if not root.is_dir():
        root = Path.home() / ".agents" / "skills" / "lib-bursawatch-source-media" / "bin"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(url, Path(token))


def verified_download(reference: dict[str, Any], client: Any) -> tuple[bytes, str]:
    if (not isinstance(reference, dict) or reference.get("kind") != "image"
            or reference.get("content_type") not in SUFFIX or reference.get("durable") is not True
            or not isinstance(reference.get("sha256"), str)
            or not isinstance(reference.get("size_bytes"), int)):
        raise ValueError("source image metadata is invalid")
    ref = reference["ref"]
    reference_url(ref)
    downloaded = client.download(ref)
    data = downloaded.data
    if (downloaded.kind != "image" or downloaded.content_type != reference["content_type"]
            or downloaded.sha256 != reference["sha256"] or len(data) != reference["size_bytes"]
            or hashlib.sha256(data).hexdigest() != reference["sha256"]):
        raise ValueError("source image does not match its durable reference")
    return data, SUFFIX[reference["content_type"]]


def cache_reference(state_path: Path, reference: dict[str, Any], client: Any) -> Path:
    """Keep a checked local derivative for the Board's existing path contract."""
    ref = reference["ref"]
    reference_url(ref)
    suffix = SUFFIX.get(reference.get("content_type"))
    if suffix is None:
        raise ValueError("source image type is unsupported")
    root = state_path.parent / "source-media-cache"
    if root.is_symlink():
        raise ValueError("source image cache path is invalid")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    target = root / f"{ref}{suffix}"
    if target.is_symlink():
        raise ValueError("source image cache path is invalid")
    if target.is_file():
        data = target.read_bytes()
        if len(data) == reference["size_bytes"] and hashlib.sha256(data).hexdigest() == reference["sha256"]:
            return target.resolve()
    data, _suffix = verified_download(reference, client)
    descriptor, temporary = tempfile.mkstemp(prefix=".source-media-", dir=root)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target.resolve()
