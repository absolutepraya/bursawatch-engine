from __future__ import annotations

import hashlib
import os
from pathlib import Path

import requests


API = "https://discord.com/api/v10"


class DiscordRetryAfter(RuntimeError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Discord rate limited for {retry_after:g} seconds")


def nonce(event_key: str, leg: str) -> str:
    return hashlib.sha256(f"whatsapp-channel-watch:{event_key}:{leg}".encode()).hexdigest()[:24]


def _token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is unavailable")
    return token


def _request(channel_id: str, *, json=None, files=None):
    response = requests.post(
        f"{API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {_token()}"},
        json=json,
        files=files,
        timeout=30,
    )
    if response.status_code == 429:
        raise DiscordRetryAfter(float(response.json().get("retry_after", 1)))
    if response.status_code >= 400:
        raise RuntimeError(f"Discord HTTP {response.status_code}")
    return response.json().get("id")


def post_text(content: str, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}: {content}")
        return "dry-run"
    return _request(channel_id, json={"content": content, "nonce": nonce_value, "allowed_mentions": {"parse": []}})


def post_media(path: Path, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    if not path.is_file():
        raise FileNotFoundError(f"source media is unavailable: {path.name}")
    if dry_run:
        print(f"[dry-run] Discord media {channel_id}: {path.name}")
        return "dry-run"
    with path.open("rb") as stream:
        return _request(
            channel_id,
            files={"files[0]": (path.name, stream, "application/octet-stream")},
            json={"nonce": nonce_value, "allowed_mentions": {"parse": []}},
        )
