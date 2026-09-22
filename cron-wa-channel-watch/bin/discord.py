from __future__ import annotations

import hashlib
import mimetypes
import os
from pathlib import Path

import requests


API = "https://discord.com/api/v10"
BOARD_URL = "https://discord.com/channels/940285152335110204/1548273399069933720"
BOARD_MENTION = "<#1548273399069933720>"


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


def _response(method: str, url: str, *, json=None, files=None, data=None, params=None):
    response = requests.request(
        method,
        url,
        headers={"Authorization": f"Bot {_token()}"},
        json=json,
        files=files,
        data=data,
        params=params,
        timeout=30,
    )
    if response.status_code == 429:
        raise DiscordRetryAfter(float(response.json().get("retry_after", 1)))
    if response.status_code >= 400:
        raise RuntimeError(f"Discord HTTP {response.status_code}")
    return response


def _request(channel_id: str, *, json=None, files=None):
    response = _response("POST", f"{API}/channels/{channel_id}/messages", json=json, files=files)
    return response.json().get("id")


def post_text(content: str, channel_id: str, dry_run: bool, nonce_value: str) -> str | None:
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord text {channel_id}: {content}")
        return "dry-run"
    return _request(channel_id, json={
        "content": content,
        "nonce": nonce_value,
        "enforce_nonce": True,
        "allowed_mentions": {"parse": []},
    })


def media_filename(kind: str, mime: str | None, index: int = 0, *, prefix: str = "whatsapp-channel") -> str:
    extension = mimetypes.guess_extension(mime or "") if mime else None
    if extension == ".jpe":
        extension = ".jpg"
    if not extension:
        extension = {"image": ".jpg", "video": ".mp4"}.get(kind, ".bin")
    return f"{prefix}-{index}{extension}"


def post_media(
    path: Path,
    channel_id: str,
    dry_run: bool,
    nonce_value: str,
    *,
    filename: str | None = None,
    mime: str | None = None,
) -> str | None:
    if not path.is_file():
        raise FileNotFoundError(f"source media is unavailable: {path.name}")
    upload_name = filename or path.name
    if dry_run:
        print(f"[dry-run] Discord media {channel_id}: {upload_name}")
        return "dry-run"
    with path.open("rb") as stream:
        return _request(
            channel_id,
            files={"files[0]": (upload_name, stream, mime or "application/octet-stream")},
            json={
                "nonce": nonce_value,
                "enforce_nonce": True,
                "allowed_mentions": {"parse": []},
            },
        )


def get_message(channel_id: str, message_id: str) -> dict[str, object] | None:
    response = _response("GET", f"{API}/channels/{channel_id}/messages/{message_id}")
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def list_messages(channel_id: str, *, limit: int = 100, before: str | None = None) -> list[dict[str, object]]:
    if not 1 <= limit <= 100:
        raise ValueError("Discord message limit must be between 1 and 100")
    params = {"limit": str(limit)}
    if before:
        params["before"] = before
    response = _response("GET", f"{API}/channels/{channel_id}/messages", params=params)
    payload = response.json()
    return payload if isinstance(payload, list) else []


def _replace_board_topic_link(content: str, board_url: str) -> str:
    if not board_url.startswith("https://discord.com/channels/"):
        raise ValueError("board_url must be a Discord channel or topic URL")
    replacement = f"**Board:** {board_url}"
    legacy = {
        f"**Board:** {BOARD_MENTION}",
        f"**Board:** {BOARD_URL}",
        f"**Board:** <{BOARD_URL}>",
    }
    lines = content.split("\n")
    changed = False
    for index, line in enumerate(lines):
        if line.strip() in legacy:
            lines[index] = replacement
            changed = True
    return "\n".join(lines) if changed else content


def edit_board_link(
    channel_id: str,
    message_ids: list[str] | tuple[str, ...],
    board_url: str | None,
    dry_run: bool,
    nonce_value: str,
) -> bool:
    """Patch only the generic Board marker, preserving message IDs and media."""
    if not board_url or not message_ids:
        return True
    for message_id in message_ids:
        if dry_run:
            print(f"[dry-run] Discord board link {channel_id}/{message_id} -> {board_url} ({nonce_value})")
            continue
        current = get_message(channel_id, str(message_id))
        content = current.get("content") if current else None
        if not isinstance(content, str):
            return False
        updated = _replace_board_topic_link(content, board_url)
        if updated == content:
            continue
        response = _response(
            "PATCH",
            f"{API}/channels/{channel_id}/messages/{message_id}",
            json={"content": updated, "allowed_mentions": {"parse": []}},
        )
        if response.status_code != 200:
            return False
    return True


def edit_message_content(channel_id: str, message_id: str, content: str, *, dry_run: bool = False) -> bool:
    """Replace one message body without touching its existing attachments."""
    if len(content) > 2_000:
        raise ValueError("Discord text exceeds 2000 characters")
    if dry_run:
        print(f"[dry-run] Discord edit {channel_id}/{message_id}: {content}")
        return True
    response = _response(
        "PATCH",
        f"{API}/channels/{channel_id}/messages/{message_id}",
        json={"content": content, "allowed_mentions": {"parse": []}},
    )
    return response.status_code == 200
