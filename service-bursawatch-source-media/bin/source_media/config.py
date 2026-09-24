"""Environment configuration for the private source-media service."""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path


_BUCKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")


@dataclass(frozen=True)
class Config:
    port: int
    upload_token: str
    read_token: str
    state_path: Path
    supabase_url: str
    bucket: str
    service_role_key_path: Path

    @classmethod
    def from_environment(cls) -> "Config":
        try:
            port = int(os.environ.get("SOURCE_MEDIA_PORT", "9130"))
        except ValueError as exc:
            raise ValueError("invalid source-media port") from exc
        upload_token = os.environ.get("SOURCE_MEDIA_UPLOAD_TOKEN", "")
        read_token = os.environ.get("SOURCE_MEDIA_READ_TOKEN", "")
        raw_url = os.environ.get("SOURCE_MEDIA_SUPABASE_URL", "")
        bucket = os.environ.get("SOURCE_MEDIA_SUPABASE_BUCKET", "")
        key_path = os.environ.get("SOURCE_MEDIA_SUPABASE_SERVICE_ROLE_KEY_PATH", "")
        state_path = os.environ.get("SOURCE_MEDIA_STATE_PATH", "")
        parts = urllib.parse.urlsplit(raw_url)
        if (
            not 1 <= port <= 65535
            or not upload_token
            or not read_token
            or upload_token == read_token
            or parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
            or not _BUCKET.fullmatch(bucket)
            or not key_path
            or not state_path
        ):
            raise ValueError("invalid source-media service configuration")
        return cls(
            port=port,
            upload_token=upload_token,
            read_token=read_token,
            state_path=Path(state_path),
            supabase_url=f"https://{parts.netloc}",
            bucket=bucket,
            service_role_key_path=Path(key_path),
        )
