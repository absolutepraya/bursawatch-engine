from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path

import requests


API = "https://discord.com/api/v10"


class DiscordRetryAfter(RuntimeError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Discord rate limited for {retry_after:g} seconds")


def nonce(event_key: str, leg: str) -> str:
    return hashlib.sha256(f"x-post-watch:{event_key}:{leg}".encode()).hexdigest()[:24]


def _token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token: raise RuntimeError("DISCORD_BOT_TOKEN is unavailable")
    return token


def _request(channel_id: str, *, json=None, files=None, nonce_value: str):
    response = requests.post(f"{API}/channels/{channel_id}/messages", headers={"Authorization": f"Bot {_token()}"}, json=json, files=files, timeout=30)
    if response.status_code == 429:
        raise DiscordRetryAfter(float(response.json().get("retry_after", 1)))
    if response.status_code >= 400: raise RuntimeError(f"Discord HTTP {response.status_code}")
    return response.json().get("id")


def post_text(content: str, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    if len(content) > 2000: raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}: {content}")
        return "dry-run"
    return _request(channel_id, json={"content": content, "nonce": nonce_value}, nonce_value=nonce_value)


def post_media(url: str, channel_id: str, dry_run: bool, nonce_value: str, directory: Path) -> str | None:
    if dry_run:
        print(f"[dry-run] Discord media {channel_id}: {url}")
        return "dry-run"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
    extension = mimetypes.guess_extension(content_type) or ".bin"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"x-post-{nonce_value}{extension}"
    path.write_bytes(response.content)
    try:
        with path.open("rb") as content:
            result = _request(channel_id, files={"files[0]": (path.name, content, content_type)}, nonce_value=nonce_value)
    finally:
        path.unlink(missing_ok=True)
    return result
