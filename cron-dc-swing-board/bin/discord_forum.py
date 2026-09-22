"""The IDX Swing board's only Discord forum REST surface.

The client has no store access.  It receives already-durable owner intents and
either executes exactly one REST operation or, in no-post mode, returns stable
placeholder identities without making an HTTP request.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

# The board deliberately owns a short ``calendar`` module name.  Pytest adds
# this directory to ``sys.path`` before importing requests, whose stdlib
# cookiejar dependency imports ``calendar.timegm``.  Supply that one standard
# helper on the already-loaded board module so the HTTP dependency cannot
# accidentally fail during import because of the intentional local name.
import calendar as _board_calendar
if not hasattr(_board_calendar, "timegm"):
    def _timegm(parts: tuple[int, ...]) -> int:
        from datetime import datetime, timezone

        return int(datetime(*parts[:6], tzinfo=timezone.utc).timestamp())

    _board_calendar.timegm = _timegm

import requests


DISCORD_API = "https://discord.com/api/v10"
DISCORD_GUILD_ID = "940285152335110204"
FORUM_CHANNEL_ID = "1548273399069933720"
DISCORD_TIMEOUT_SECONDS = 30
_RETRY_FALLBACK_SECONDS = 60.0
_RETRY_CAP_SECONDS = 15 * 60.0


def forum_thread_url(thread_id: str) -> str:
    """Return the stable deep link for one forum topic."""
    value = _identifier(thread_id)
    if value is None:
        raise ValueError("thread_id must be a Discord identifier")
    return f"https://discord.com/channels/{DISCORD_GUILD_ID}/{value}"


class DiscordForumError(RuntimeError):
    """A safe Discord forum operation failure, suitable for owner retry state."""


class DiscordRateLimitError(DiscordForumError):
    def __init__(self, retry_after: float) -> None:
        super().__init__("Discord rate limited")
        self.retry_after = retry_after


class DiscordRejectedError(DiscordForumError):
    """A definite client rejection that did not create a Discord object."""


@dataclass(frozen=True)
class ForumThread:
    thread_id: str
    starter_message_id: str


class DiscordForumClient:
    """Perform idempotent forum operations for the deterministic board owner."""

    def __init__(self, *, token: str | None = None, no_post: bool | None = None) -> None:
        self._token_override = token
        self.before_create = None
        self.no_post = (
            os.environ.get("IDX_SWING_PLAN_BOARD_NO_POST") == "1"
            if no_post is None
            else no_post
        )

    def create_forum_thread(
        self,
        name: str,
        content: str,
        tag_names: tuple[str, ...] | list[str],
        chart: Path | str | None,
        nonce_value: str,
    ) -> ForumThread:
        """Create one forum post and its Yanto-owned starter card."""
        if self.no_post:
            return ForumThread("dry-run-thread", "dry-run-starter")
        message = self._message(content, nonce_value)
        payload: dict[str, object] = {
            "name": _text(name, "thread name"),
            "applied_tags": self._resolve_tag_names(tag_names),
            "message": message,
        }
        response = self._request_with_media(
            "POST", f"/channels/{FORUM_CHANNEL_ID}/threads", payload, chart
        )
        body = _json_object(response, "Discord returned an invalid forum thread")
        thread_id = _identifier(body.get("id"))
        starter = body.get("message")
        if thread_id is None or not isinstance(starter, Mapping):
            raise DiscordForumError("Discord returned an invalid forum thread")
        starter_message_id = _identifier(starter.get("id"))
        if starter_message_id is None:
            raise DiscordForumError("Discord returned an invalid forum thread")
        return ForumThread(thread_id, starter_message_id)

    def edit_starter(
        self,
        thread_id: str,
        message_id: str,
        content: str,
        chart: Path | str | None,
        *,
        clear_attachments: bool = False,
    ) -> None:
        """Edit a card, retaining charts unless replaced or explicitly cleared."""
        if self.no_post:
            return
        _bool(clear_attachments, "clear_attachments")
        path = _media_path(chart)
        if clear_attachments and path is not None:
            raise ValueError("cannot clear attachments and provide a chart")
        payload: dict[str, object] = {
            "content": _content(content),
            "allowed_mentions": {"parse": []},
        }
        if clear_attachments:
            payload["attachments"] = []
        elif path is None:
            existing = self._request("GET", f"/channels/{_id(thread_id)}/messages/{_id(message_id)}")
            payload["attachments"] = _retained_attachments(existing)
        else:
            payload["attachments"] = [{"id": "0", "filename": path.name}]
        self._request_with_media(
            "PATCH",
            f"/channels/{_id(thread_id)}/messages/{_id(message_id)}",
            payload,
            path,
        )

    def post_reply(
        self,
        thread_id: str,
        content: str,
        media: Path | str | None,
        nonce_value: str,
    ) -> str:
        """Create one normal source or quoted-history reply within a thread."""
        if self.no_post:
            return "dry-run-message"
        response = self._request_with_media(
            "POST",
            f"/channels/{_id(thread_id)}/messages",
            self._message(content, nonce_value, allow_empty=media is not None),
            media,
        )
        message_id = _identifier(_json_object(response, "Discord returned an invalid message").get("id"))
        if message_id is None:
            raise DiscordForumError("Discord returned an invalid message")
        return message_id

    def delete_message(self, thread_id: str, message_id: str) -> None:
        """Delete one approved legacy history reply from a forum thread."""
        if self.no_post:
            return
        self._request(
            "DELETE",
            f"/channels/{_id(thread_id)}/messages/{_id(message_id)}",
        )

    def patch_thread(
        self,
        thread_id: str,
        name: str,
        tag_names: tuple[str, ...] | list[str],
        archived: bool,
    ) -> None:
        """Write the complete desired title, lifecycle/market tags, and archive state."""
        if self.no_post:
            return
        if not isinstance(archived, bool):
            raise ValueError("archived must be a boolean")
        self._request(
            "PATCH",
            f"/channels/{_id(thread_id)}",
            json={
                "name": _text(name, "thread name"),
                "applied_tags": self._resolve_tag_names(tag_names),
                "archived": archived,
            },
        )

    def post_heartbeat(self, channel_id: str, content: str) -> None:
        """Direct-post one scheduler heartbeat outside the board's forum outbox."""
        if self.no_post:
            return
        self._request(
            "POST",
            f"/channels/{_id(channel_id)}/messages",
            json={"content": _text(content, "heartbeat content"), "allowed_mentions": {"parse": []}},
        )

    def execute(
        self, operation: object, payload: Mapping[str, object] | None = None
    ) -> dict[str, str]:
        """Dispatch one persisted owner operation without touching its store state."""
        operation_name, operation_payload = _operation(operation, payload)
        if operation_name == "create_thread":
            created = self.create_forum_thread(
                _required(operation_payload, "name"),
                _required(operation_payload, "content"),
                _tag_names(operation_payload),
                operation_payload.get("chart"),
                _nonce(operation_payload),
            )
            return {"thread_id": created.thread_id, "starter_message_id": created.starter_message_id}
        if operation_name == "edit_starter":
            self.edit_starter(
                _required(operation_payload, "thread_id"),
                _required(operation_payload, "message_id"),
                _required(operation_payload, "content"),
                operation_payload.get("chart"),
                clear_attachments=_bool(operation_payload.get("clear_attachments", False), "clear_attachments"),
            )
            return {}
        if operation_name in {"post_source_reply", "post_history_reply"}:
            return {
                "message_id": self.post_reply(
                    _required(operation_payload, "thread_id"),
                    _reply_content(operation_payload),
                    operation_payload.get("media"),
                    _nonce(operation_payload),
                )
            }
        if operation_name == "delete_message":
            self.delete_message(
                _required(operation_payload, "thread_id"),
                _required(operation_payload, "message_id"),
            )
            return {}
        if operation_name == "patch_thread":
            self.patch_thread(
                _required(operation_payload, "thread_id"),
                _required(operation_payload, "name"),
                _tag_names(operation_payload),
                _bool(operation_payload.get("archived"), "archived"),
            )
            return {}
        raise ValueError(f"unsupported forum operation: {operation_name}")

    def create_snapshot(self, operation: str, payload: Mapping[str, object]) -> dict:
        """Read a pre-POST boundary; the engine persists it before sending.

        The immutable intent contains the source URL/operation key and content.
        No recovery marker or internal identifier is added to visible messages.
        """
        own = _json_object(self._request("GET", "/users/@me"), "Discord identity unavailable")
        bot_id = _id(own.get("id"))
        started = datetime.now(timezone.utc)
        after_id = str(max(0, int(started.timestamp() * 1000) - 1420070400000) << 22)
        if operation != "create_thread":
            page = self._request("GET", f"/channels/{_id(payload['thread_id'])}/messages", params={"limit": 1}).json()
            if not isinstance(page, list):
                raise DiscordForumError("Discord recovery boundary unavailable")
            after_id = _id(page[0].get("id")) if page else "0"
        media = payload.get("chart") if operation == "create_thread" else payload.get("media")
        return {"after_id": after_id, "started_at": started.isoformat(), "bot_id": bot_id,
                "content": payload["content"], "filename": Path(str(media)).name if media else None,
                "operation_key": _nonce(payload)}

    def recover_create(self, operation: str, payload: Mapping[str, object]) -> dict[str, str]:
        """Recover ambiguous success, never blindly repeat a possibly accepted POST.

        Discord enforces nonce uniqueness for only a few minutes. Read back
        exact bot-authored content and attachment identity beyond the persisted
        boundary instead. An incomplete search or no unique match stays pending
        for review, because absence is not proof that a timed-out POST failed.
        """
        snapshot = payload["create_snapshot"]
        matches = []
        if operation == "create_thread":
            channel = _json_object(self._request("GET", f"/channels/{FORUM_CHANNEL_ID}"), "Discord forum unavailable")
            guild_id = _id(channel.get("guild_id"))
            active = _json_object(self._request("GET", f"/guilds/{guild_id}/threads/active"), "Discord threads unavailable")
            threads = _thread_list(active)
            before = None
            for _ in range(10):
                params = {"limit": 100}
                if before:
                    params["before"] = before
                archived = _json_object(self._request("GET", f"/channels/{FORUM_CHANNEL_ID}/threads/archived/public", params=params), "Discord threads unavailable")
                batch = _thread_list(archived)
                threads.extend(batch)
                if not archived.get("has_more"):
                    break
                next_before = batch[-1].get("thread_metadata", {}).get("archive_timestamp") if batch else None
                if not next_before or next_before == before:
                    raise DiscordForumError("Discord recovery pagination unavailable")
                if datetime.fromisoformat(next_before) < datetime.fromisoformat(snapshot["started_at"]):
                    break
                before = next_before
            else:
                raise DiscordForumError("Discord recovery search limit reached")
            for thread in {str(item["id"]): item for item in threads}.values():
                if str(thread.get("parent_id")) != FORUM_CHANNEL_ID or int(thread["id"]) <= int(snapshot["after_id"]):
                    continue
                thread_id = _id(thread["id"])
                message = _json_object(self._request("GET", f"/channels/{thread_id}/messages/{thread_id}"), "Discord starter unavailable")
                if _matches_create(message, snapshot):
                    matches.append({"thread_id": thread_id, "starter_message_id": _id(message["id"])})
        else:
            before = None
            for _ in range(10):
                params = {"limit": 100}
                if before:
                    params["before"] = before
                batch = self._request("GET", f"/channels/{_id(payload['thread_id'])}/messages", params=params).json()
                if not isinstance(batch, list):
                    raise DiscordForumError("Discord recovery messages unavailable")
                for message in batch:
                    if int(message["id"]) > int(snapshot["after_id"]) and _matches_create(message, snapshot):
                        matches.append({"message_id": _id(message["id"])})
                if not batch or len(batch) < 100 or int(batch[-1]["id"]) <= int(snapshot["after_id"]):
                    break
                next_before = _id(batch[-1]["id"])
                if next_before == before:
                    raise DiscordForumError("Discord recovery pagination unavailable")
                before = next_before
            else:
                raise DiscordForumError("Discord recovery search limit reached")
        if len(matches) != 1:
            raise DiscordForumError("Discord create outcome remains uncertain")
        return matches[0]

    def _message(self, content: str, nonce_value: str, *, allow_empty: bool = False) -> dict[str, object]:
        return {
            "content": _content(content, allow_empty=allow_empty),
            "nonce": stable_nonce(nonce_value),
            "enforce_nonce": True,
            "allowed_mentions": {"parse": []},
        }

    def _token(self) -> str:
        token = self._token_override or os.environ.get("DISCORD_BOT_TOKEN")
        if not token:
            raise DiscordForumError("Discord bot token is unavailable")
        return token

    def _resolve_tag_names(self, tag_names: tuple[str, ...] | list[str]) -> list[str]:
        """Resolve reviewed canonical names against the forum's current tag catalog."""
        required_names = _validated_tag_names(tag_names)
        response = self._request("GET", f"/channels/{FORUM_CHANNEL_ID}")
        channel = _json_object(response, "Discord returned an invalid forum channel")
        available_tags = channel.get("available_tags")
        if not isinstance(available_tags, list):
            raise DiscordForumError("Discord returned an invalid forum tag catalog")

        resolved: list[str] = []
        for required_name in required_names:
            matches = [
                _identifier(tag.get("id"))
                for tag in available_tags
                if isinstance(tag, Mapping) and tag.get("name") == required_name
            ]
            if len(matches) != 1 or matches[0] is None:
                raise DiscordForumError(f"Discord forum tag is not uniquely available: {required_name}")
            resolved.append(matches[0])
        return resolved

    def _request_with_media(
        self,
        method: str,
        path: str,
        payload: dict[str, object],
        media: Path | str | None,
    ) -> Any:
        source = _media_path(media)
        if source is None:
            return self._request(method, path, json=payload)
        try:
            with source.open("rb") as file:
                return self._request(
                    method,
                    path,
                    data={"payload_json": json.dumps(payload, separators=(",", ":"))},
                    files={"files[0]": (source.name, file)},
                )
        except OSError as exc:
            raise DiscordForumError("Discord media upload failed") from exc

    def _request(self, method: str, path: str, **kwargs: object) -> Any:
        headers = {"Authorization": f"Bot {self._token()}"}
        if "json" in kwargs:
            headers["Content-Type"] = "application/json"
        if method == "POST" and self.before_create is not None:
            self.before_create()
        try:
            response = requests.request(
                method,
                f"{DISCORD_API}{path}",
                headers=headers,
                timeout=DISCORD_TIMEOUT_SECONDS,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise DiscordForumError("Discord request failed") from exc
        status = getattr(response, "status_code", None)
        if status == 429:
            error = DiscordRateLimitError(_retry_after(response))
            error.create_rejected = method == "POST"
            raise error
        if isinstance(status, int) and 400 <= status < 500:
            error = DiscordRejectedError("Discord API request was rejected")
            error.create_rejected = method == "POST"
            raise error
        if not isinstance(status, int) or not 200 <= status < 300:
            raise DiscordForumError("Discord API request was rejected")
        return response


def stable_nonce(value: str) -> str:
    """Derive one Discord-safe, stable nonce from durable owner identity."""
    return hashlib.sha256(_text(value, "nonce").encode("utf-8")).hexdigest()[:24]


def _thread_list(payload: Mapping) -> list[dict]:
    value = payload.get("threads")
    if not isinstance(value, list) or any(not isinstance(item, dict) or "id" not in item for item in value):
        raise DiscordForumError("Discord recovery threads unavailable")
    return value


def _matches_create(message: Mapping, snapshot: Mapping) -> bool:
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return False
    filenames = [item.get("filename") for item in attachments]
    expected = [snapshot["filename"]] if snapshot["filename"] else []
    return (str(message.get("author", {}).get("id")) == snapshot["bot_id"]
            and message.get("content") == snapshot["content"] and filenames == expected
            and (message.get("nonce") is None or str(message["nonce"]) == stable_nonce(snapshot["operation_key"])))


def _content(value: object, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    value = _text(value, "message content")
    if len(value.encode("utf-16-le")) // 2 > 2000:
        raise ValueError("Discord message content exceeds 2000 characters")
    return value


def _retry_after(response: object) -> float:
    try:
        payload = response.json()  # type: ignore[union-attr]
        value = payload.get("retry_after") if isinstance(payload, Mapping) else None
        delay = float(value)
    except (AttributeError, TypeError, ValueError, requests.RequestException):
        delay = _RETRY_FALLBACK_SECONDS
    if not math.isfinite(delay) or delay <= 0:
        return _RETRY_FALLBACK_SECONDS
    return min(delay, _RETRY_CAP_SECONDS)


def _json_object(response: object, error: str) -> Mapping[str, object]:
    try:
        payload = response.json()  # type: ignore[union-attr]
    except (AttributeError, ValueError, requests.RequestException) as exc:
        raise DiscordForumError(error) from exc
    if not isinstance(payload, Mapping):
        raise DiscordForumError(error)
    return payload


def _retained_attachments(response: object) -> list[dict[str, str]]:
    payload = _json_object(response, "Discord returned an invalid starter message")
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        raise DiscordForumError("Discord returned an invalid starter message")
    retained: list[dict[str, str]] = []
    for attachment in attachments:
        if not isinstance(attachment, Mapping):
            raise DiscordForumError("Discord returned an invalid starter message")
        attachment_id = _identifier(attachment.get("id"))
        filename = attachment.get("filename")
        if attachment_id is None or not isinstance(filename, str) or not filename:
            raise DiscordForumError("Discord returned an invalid starter message")
        kept = {"id": attachment_id, "filename": filename}
        description = attachment.get("description")
        if isinstance(description, str) and description:
            kept["description"] = description
        retained.append(kept)
    return retained


def _media_path(value: Path | str | object | None) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, (Path, str)) or not str(value):
        raise ValueError("Discord media path is invalid")
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError("Discord media file is unavailable")
    return path


def _operation(
    operation: object, payload: Mapping[str, object] | None
) -> tuple[str, Mapping[str, object]]:
    if isinstance(operation, str):
        return operation, payload or {}
    name = getattr(operation, "operation", None)
    operation_payload = getattr(operation, "payload", None)
    if not isinstance(name, str) or not isinstance(operation_payload, Mapping):
        raise ValueError("forum operation is invalid")
    return name, operation_payload


def _required(payload: Mapping[str, object], key: str) -> str:
    return _text(payload.get(key), key)


def _reply_content(payload: Mapping[str, object]) -> str:
    """Allow an attachment-only reply while retaining normal content validation."""
    if payload.get("content") == "" and payload.get("media") is not None:
        return ""
    return _required(payload, "content")


def _nonce(payload: Mapping[str, object]) -> str:
    value = payload.get("nonce", payload.get("nonce_value"))
    return _text(value, "nonce")


def _tag_names(payload: Mapping[str, object]) -> list[str]:
    return _validated_tag_names(payload.get("tag_names"))


def _validated_tag_names(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("forum tag names must be a non-empty list")
    names = [_text(tag, "forum tag name") for tag in value]
    if len(names) != len(set(names)):
        raise ValueError("forum tag names must be unique")
    return names


def _id(value: object) -> str:
    identifier = _identifier(value)
    if identifier is None:
        raise ValueError("Discord identifier is invalid")
    return identifier


def _identifier(value: object) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    if isinstance(value, str) and value and len(value) <= 128 and not any(ord(char) < 32 for char in value):
        return value
    return None


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value
