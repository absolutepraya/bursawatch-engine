from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path
import sys

import requests

_SHARED_FORMAT_BIN = Path(__file__).resolve().parents[2] / "swing-format" / "bin"
if not _SHARED_FORMAT_BIN.exists():
    _SHARED_FORMAT_BIN = Path.home() / ".agents" / "skills" / "swing-format" / "bin"
if str(_SHARED_FORMAT_BIN) not in sys.path:
    sys.path.insert(0, str(_SHARED_FORMAT_BIN))

from swing_format import replace_board_topic_link


API = "https://discord.com/api/v10"


class DiscordRetryAfter(RuntimeError):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Discord rate limited for {retry_after:g} seconds")


class MediaUnavailable(RuntimeError):
    """A source media URL returned a confirmed permanent absence."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"media unavailable HTTP {status_code}")


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


def edit_board_links(channel_id: str, message_ids: object, board_url: object, dry_run: bool) -> bool:
    """Patch delivered All Swing text messages to the exact forum topic."""
    if not isinstance(board_url, str) or not board_url:
        return True
    if not isinstance(message_ids, list):
        return False
    if dry_run:
        print(f"[dry-run] Discord board links {channel_id} -> {board_url}")
        return True
    headers = {"Authorization": f"Bot {_token()}", "Content-Type": "application/json"}
    for message_id in message_ids:
        if not isinstance(message_id, str) or not message_id:
            return False
        try:
            response = requests.get(
                f"{API}/channels/{channel_id}/messages/{message_id}",
                headers=headers,
                timeout=30,
            )
            if response.status_code == 429:
                raise DiscordRetryAfter(float(response.json().get("retry_after", 1)))
            if response.status_code != 200:
                return False
            current = response.json().get("content")
            if not isinstance(current, str):
                return False
            updated = replace_board_topic_link(current, board_url)
            if updated == current:
                continue
            response = requests.patch(
                f"{API}/channels/{channel_id}/messages/{message_id}",
                headers=headers,
                json={"content": updated, "allowed_mentions": {"parse": []}},
                timeout=30,
            )
            if response.status_code == 429:
                raise DiscordRetryAfter(float(response.json().get("retry_after", 1)))
            if response.status_code != 200:
                return False
        except requests.RequestException:
            return False
    return True


def post_media(url: str, channel_id: str, dry_run: bool, nonce_value: str, directory: Path) -> str | None:
    if dry_run:
        print(f"[dry-run] Discord media {channel_id}: {url}")
        return "dry-run"
    response = requests.get(url, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        if response.status_code in {404, 410}:
            raise MediaUnavailable(response.status_code) from error
        raise
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


def delete_message(channel_id: str, message_id: str, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] Discord delete {channel_id}/{message_id}")
        return
    response = requests.delete(
        f"{API}/channels/{channel_id}/messages/{message_id}",
        headers={"Authorization": f"Bot {_token()}"},
        timeout=30,
    )
    if response.status_code not in {204, 404}:
        if response.status_code == 429:
            raise DiscordRetryAfter(float(response.json().get("retry_after", 1)))
        raise RuntimeError(f"Discord delete HTTP {response.status_code}")
    verification = requests.get(
        f"{API}/channels/{channel_id}/messages/{message_id}",
        headers={"Authorization": f"Bot {_token()}"},
        timeout=30,
    )
    if verification.status_code != 404:
        raise RuntimeError(f"Discord delete verification HTTP {verification.status_code}")
