"""Private, lease-bound evidence for subject validation, never publication state."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


CONTRACT = "subject-v1"
MAX_BYTES = 256_000


def _path(storage: Path, event: dict) -> Path:
    identity = f"{event['profile_id']}:{event['post_id']}:{event.get('agent_lease_until')}"
    key = event.get("news_subject_context_key") or hashlib.sha256(identity.encode()).hexdigest()
    if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise ValueError("invalid subject context key")
    return storage.parent / "subject-context" / (key + ".txt")


def freeze(storage: Path, event: dict, item: dict) -> None:
    cleanup(storage, event)
    event.pop("news_subject_context_key", None)
    path = _path(storage, event)
    data = (str(item["post_text"]) + "\n\n" + str(item.get("quoted_post_text") or "")).encode()
    if len(data) > MAX_BYTES:
        raise ValueError("subject context exceeds its bound")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A reclaimed lease replaces its previous context; the accepted lease uses
    # this immutable snapshot instead of re-fetching a possibly changed URL.
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(data)
    temporary.replace(path)
    event["news_subject_context_key"] = path.stem
    event["news_subject_contract"] = CONTRACT
    event["news_subject_context_sha256"] = hashlib.sha256(data).hexdigest()


def read(storage: Path, event: dict) -> str | None:
    if "news_subject_contract" not in event:
        return None
    if event["news_subject_contract"] != CONTRACT:
        raise ValueError("unsupported subject contract")
    path = _path(storage, event)
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid subject context")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != event.get("news_subject_context_sha256"):
        raise ValueError("subject context changed after claim")
    return data.decode()


def cleanup(storage: Path, event: dict) -> None:
    _path(storage, event).unlink(missing_ok=True)
