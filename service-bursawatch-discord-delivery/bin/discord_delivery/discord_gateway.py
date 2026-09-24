"""The sole Discord REST boundary for typed delivery operations and reads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from .models import OperationIntent, ValidationError, validate_query, validate_receipt

BASE_URL = "https://discord.com/api/v10"
TIMEOUT = (3.05, 15)


@dataclass(frozen=True)
class StoredAttachment:
    filename: str
    mime_type: str
    path: Path
    sha256: str


class GatewayError(Exception):
    """Sanitized remote failure. Never contains a response body or URL."""

    def __init__(self, category: str, retry_after: float | None = None):
        self.category = category
        self.retry_after = retry_after
        super().__init__(category)


class DiscordGateway:
    def __init__(self, bot_token: str, *, session: requests.Session | None = None):
        if not isinstance(bot_token, str) or not bot_token.strip():
            raise ValueError("bot token is required")
        self._token = bot_token.strip()
        self._session = session if session is not None else requests.Session()

    @staticmethod
    def nonce(operation_key: str) -> str:
        return hashlib.sha256(operation_key.encode("utf-8")).hexdigest()[:25]

    @staticmethod
    def request_spec(intent: OperationIntent) -> tuple[str, str, dict[str, Any]]:
        """Build the exact typed mutation, with no user supplied REST path."""
        if not isinstance(intent, OperationIntent):
            raise ValidationError("invalid operation")
        kind, target = intent.kind, intent.target
        payload = dict(intent.payload)
        if kind in {"channel_message_create", "thread_message_create"}:
            channel = target.get("channel_id", target.get("thread_id"))
            payload["allowed_mentions"] = {"parse": []}
            payload.update(nonce=DiscordGateway.nonce(intent.key), enforce_nonce=True)
            return "POST", f"/channels/{channel}/messages", payload
        if kind in {"channel_message_edit", "thread_message_edit"}:
            channel = target.get("channel_id", target.get("thread_id"))
            payload["allowed_mentions"] = {"parse": []}
            if kind == "thread_message_edit":
                payload.pop("attachments_mode", None)
            return "PATCH", f"/channels/{channel}/messages/{target['message_id']}", payload
        if kind in {"channel_message_delete", "thread_message_delete"}:
            channel = target.get("channel_id", target.get("thread_id"))
            return "DELETE", f"/channels/{channel}/messages/{target['message_id']}", {}
        if kind == "forum_thread_create":
            message = {"content": payload.pop("content", ""), "allowed_mentions": {"parse": []}}
            payload.pop("allowed_mentions", None)
            return "POST", f"/channels/{target['forum_id']}/threads", {**payload, "message": message}
        if kind == "forum_thread_update":
            return "PATCH", f"/channels/{target['thread_id']}", payload
        if kind == "forum_thread_archive":
            return "PATCH", f"/channels/{target['thread_id']}", {"archived": True}
        if kind == "forum_channel_create":
            return "POST", f"/guilds/{target['guild_id']}/channels", {**payload, "type": 15}
        if kind == "forum_channel_edit":
            return "PATCH", f"/channels/{target['channel_id']}", payload
        if kind == "forum_channel_delete":
            return "DELETE", f"/channels/{target['channel_id']}", {}
        raise ValidationError("invalid operation kind")

    def _request(self, method: str, path: str, *, body: Mapping[str, Any] | None = None,
                 attachments: Sequence[StoredAttachment] = (), params: Mapping[str, Any] | None = None) -> Any:
        options: dict[str, Any] = {
            "headers": {"Authorization": f"Bot {self._token}"}, "timeout": TIMEOUT,
        }
        if params is not None:
            options["params"] = dict(params)
        if attachments:
            files = {}
            for index, attachment in enumerate(attachments):
                data = Path(attachment.path).read_bytes()
                if hashlib.sha256(data).hexdigest() != attachment.sha256:
                    raise GatewayError("attachment_changed")
                files[f"files[{index}]"] = (attachment.filename, data, attachment.mime_type)
            value = dict(body or {})
            if "message" in value:
                current = value["message"].get("attachments", [])
                if not isinstance(current, list):
                    raise GatewayError("invalid_attachment_state")
                value["message"] = {**value["message"], "attachments": [
                    *current,
                    *({"id": index, "filename": item.filename} for index, item in enumerate(attachments)),
                ]}
            else:
                current = value.get("attachments", [])
                if not isinstance(current, list):
                    raise GatewayError("invalid_attachment_state")
                value["attachments"] = [
                    *current,
                    *({"id": index, "filename": item.filename} for index, item in enumerate(attachments)),
                ]
            options["data"] = {"payload_json": json.dumps(value, separators=(",", ":"))}
            options["files"] = files
        elif body is not None and method != "DELETE":
            options["json"] = dict(body)
        try:
            response = self._session.request(method, BASE_URL + path, **options)
        except requests.Timeout as exc:
            raise GatewayError("timeout") from exc
        except requests.RequestException as exc:
            raise GatewayError("network") from exc
        status = response.status_code
        if status == 429:
            delay = 0.0
            try:
                data = response.json()
                if isinstance(data, dict):
                    delay = max(delay, float(data.get("retry_after", 0)))
            except (ValueError, TypeError):
                pass
            try:
                delay = max(delay, float(response.headers.get("Retry-After", 0)))
            except (ValueError, TypeError):
                pass
            raise GatewayError("rate_limited", max(delay, 1.0))
        if status == 404 and method == "DELETE":
            return {}
        if status in (401, 403, 404):
            raise GatewayError("permission" if status in (401, 403) else "destination_missing")
        if status >= 500:
            raise GatewayError("discord_unavailable")
        if status >= 400:
            raise GatewayError("rejected")
        if status == 204 or method == "DELETE":
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise GatewayError("invalid_response") from exc

    def execute(self, intent: OperationIntent, attachments: Sequence[StoredAttachment]) -> dict[str, str]:
        method, path, body = self.request_spec(intent)
        if attachments and intent.kind not in {
            "channel_message_create", "thread_message_create", "forum_thread_create", "thread_message_edit"
        }:
            raise ValidationError("attachments not supported for operation kind")
        if intent.kind == "thread_message_edit":
            mode = intent.payload["attachments_mode"]
            if mode == "keep":
                current = self._request(
                    "GET",
                    f"/channels/{intent.target['thread_id']}/messages/{intent.target['message_id']}",
                )
                body["attachments"] = self._attachment_refs(current)
            else:
                body["attachments"] = []
        result = self._request(method, path, body=body, attachments=attachments)
        target = intent.target
        if method == "DELETE":
            if intent.kind.endswith("message_delete"):
                return validate_receipt({"message_id": target["message_id"]}, intent.kind, target)
            return validate_receipt({"channel_id": target["channel_id"]}, intent.kind, target)
        if not isinstance(result, dict):
            raise GatewayError("invalid_response")
        try:
            if intent.kind == "forum_thread_create":
                receipt = {"thread_id": result["id"], "message_id": result["message"]["id"]}
            elif intent.kind.startswith("forum_thread_"):
                receipt = {"thread_id": result["id"]}
            elif intent.kind.startswith("forum_channel_"):
                receipt = {"channel_id": result["id"]}
            else:
                receipt = {"message_id": result["id"]}
            return validate_receipt(receipt, intent.kind, target)
        except (KeyError, TypeError, ValidationError) as exc:
            raise GatewayError("invalid_response") from exc

    @staticmethod
    def _attachment_refs(message: object) -> list[dict[str, str]]:
        if not isinstance(message, dict) or not isinstance(message.get("attachments"), list):
            raise GatewayError("invalid_attachment_state")
        result = []
        for attachment in message["attachments"]:
            if not isinstance(attachment, dict):
                raise GatewayError("invalid_attachment_state")
            attachment_id = attachment.get("id")
            filename = attachment.get("filename")
            if (not isinstance(attachment_id, str) or not attachment_id.isdigit()
                    or not isinstance(filename, str) or not filename or len(filename) > 255):
                raise GatewayError("invalid_attachment_state")
            result.append({"id": attachment_id, "filename": filename})
        return result

    def query(self, query: Mapping[str, Any]) -> object:
        value = validate_query(dict(query))
        kind = value["kind"]
        if kind == "forum_threads":
            channel = self._request("GET", f"/channels/{value['channel_id']}")
            if not isinstance(channel, dict) or not isinstance(channel.get("guild_id"), str) or not channel["guild_id"].isdigit():
                raise GatewayError("invalid_response")
            active = self._request("GET", f"/guilds/{channel['guild_id']}/threads/active")
            archived = self._request("GET", f"/channels/{value['channel_id']}/threads/archived/public",
                                     params={"limit": value.get("limit", 100)})
            if (not isinstance(active, dict) or not isinstance(active.get("threads"), list)
                    or not isinstance(archived, dict) or not isinstance(archived.get("threads"), list)
                    or not isinstance(archived.get("has_more"), bool)):
                raise GatewayError("invalid_response")
            threads = [thread for thread in active["threads"]
                       if isinstance(thread, dict) and thread.get("parent_id") == value["channel_id"]]
            threads.extend(archived["threads"])
            return {"threads": threads, "has_more": archived["has_more"]}
        if kind in {"forum_thread_read", "forum_channel_read"}:
            path = f"/channels/{value.get('thread_id', value.get('channel_id'))}"
        elif kind == "thread_message_read":
            path = f"/channels/{value['thread_id']}/messages/{value['message_id']}"
        elif kind in {"channel_messages", "thread_messages"}:
            path = f"/channels/{value.get('channel_id', value.get('thread_id'))}/messages"
        else:
            path = f"/channels/{value['channel_id']}/threads/archived/public"
        params = {key: value[key] for key in ("before", "after", "limit") if key in value}
        return self._request("GET", path, params=params or None)
