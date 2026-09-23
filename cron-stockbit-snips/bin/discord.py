from __future__ import annotations

import hashlib
import os

import requests


API = "https://discord.com/api/v10"


class DiscordRateLimited(RuntimeError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Discord rate limited for {retry_after:g} seconds")


def nonce(event_key: str, leg: str) -> str:
    return hashlib.sha256(f"stockbit-snips:{event_key}:{leg}".encode()).hexdigest()[:24]


def _token(configured: str | None) -> str:
    token = configured or os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN is unavailable")
    return token


def post_text(content: str, channel_id: str, *, token: str | None, dry_run: bool, event_key: str, leg: str) -> str | None:
    if len(content) > 2000:
        raise ValueError("Discord text exceeds 2,000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}:\n{content}")
        return "dry-run"
    response = requests.post(
        f"{API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {_token(token)}"},
        json={"content": content, "nonce": nonce(event_key, leg), "allowed_mentions": {"parse": []}},
        timeout=30,
    )
    if response.status_code == 429:
        raise DiscordRateLimited(float(response.json().get("retry_after", 1)))
    if response.status_code >= 400:
        raise RuntimeError(f"Discord HTTP {response.status_code}")
    return response.json().get("id")
