"""Start the loopback Source Media Owner API."""

from __future__ import annotations

import os
import stat

import uvicorn

from source_media.api import create_app
from source_media.config import Config
from source_media.provider import SupabaseStorageProvider
from source_media.store import MediaStore


def _read_service_role_key(path: str) -> str:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or stat.S_IMODE(details.st_mode) != 0o600:
            raise ValueError("service-role key must be a private regular file")
        raw = os.read(descriptor, 4097)
        if len(raw) > 4096:
            raise ValueError("service-role key is too large")
        key = raw.decode("utf-8").strip()
        if not key or any(character.isspace() for character in key):
            raise ValueError("service-role key is invalid")
        return key
    finally:
        if descriptor is not None:
            os.close(descriptor)


def main() -> None:
    config = Config.from_environment()
    provider = SupabaseStorageProvider(
        config.supabase_url,
        config.bucket,
        _read_service_role_key(os.fspath(config.service_role_key_path)),
    )
    store = MediaStore(config.state_path, provider)
    app = create_app(config, store)
    try:
        uvicorn.run(app, host="127.0.0.1", port=config.port, workers=1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
