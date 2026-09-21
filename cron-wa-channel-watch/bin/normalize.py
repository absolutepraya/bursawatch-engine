from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import urlparse

from models import ChannelEvent, ChannelMedia


_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
_LINK_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_ALLOWED_MEDIA = {"image", "video"}
_MAX_TEXT = 16_000
_MAX_MEDIA = 8


def _timestamp(value: object, label: str) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000
        if seconds <= 0:
            raise ValueError(f"{label} must be a positive timestamp")
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO timestamp") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise ValueError(f"{label} must be a timestamp")


def _links(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for candidate in _LINK_RE.findall(text):
        candidate = candidate.rstrip(".,!?;:)")
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if candidate not in found:
            found.append(candidate)
    return tuple(found)


def normalize_bridge_event(payload: object, *, received_at: datetime | None = None) -> ChannelEvent:
    if type(payload) is not dict:
        raise ValueError("bridge event must be an object")
    required = {"channel_jid", "message_id", "published_at", "text", "media"}
    if set(payload) != required:
        raise ValueError("bridge event has unexpected or missing fields")
    channel_jid = payload["channel_jid"]
    message_id = payload["message_id"]
    text = payload["text"]
    media_value = payload["media"]
    if not isinstance(channel_jid, str) or not channel_jid.endswith("@newsletter"):
        raise ValueError("bridge event must belong to a WhatsApp Channel")
    if not isinstance(message_id, str) or not _MESSAGE_ID_RE.fullmatch(message_id):
        raise ValueError("bridge event message ID is invalid")
    if type(text) is not str:
        raise ValueError("bridge event text must be text")
    if len(text) > _MAX_TEXT:
        raise ValueError("bridge event text is too long")
    if type(media_value) is not list or len(media_value) > _MAX_MEDIA:
        raise ValueError("bridge event media is invalid")
    media: list[ChannelMedia] = []
    for index, item in enumerate(media_value):
        if type(item) is not dict or set(item) - {"kind", "mime", "path"} or "kind" not in item:
            raise ValueError("bridge event media item is invalid")
        kind = item["kind"]
        if kind not in _ALLOWED_MEDIA:
            raise ValueError("bridge event contains unsupported media")
        mime = item.get("mime")
        path = item.get("path")
        if mime is not None and type(mime) is not str:
            raise ValueError("media MIME type must be text")
        if path is not None and type(path) is not str:
            raise ValueError("media path must be text")
        media.append(ChannelMedia(kind=kind, index=index, mime=mime, path=path))
    if not text.strip() and not media:
        raise ValueError("bridge event has no supported content")
    published_at = _timestamp(payload["published_at"], "published_at")
    return ChannelEvent(
        channel_jid=channel_jid,
        message_id=message_id,
        published_at=published_at,
        text=text,
        links=_links(text),
        media=tuple(media),
        received_at=received_at or datetime.now(timezone.utc),
    )


def deserialize_queue_event(payload: object) -> ChannelEvent:
    if type(payload) is not dict:
        raise ValueError("queue event must be an object")
    required = {"schema_version", "event_key", "channel_jid", "message_id", "published_at", "text", "links", "media", "received_at"}
    if set(payload) - required - {"_path"} or not required.issubset(payload) or payload["schema_version"] != 1:
        raise ValueError("queue event has unexpected or missing fields")
    event = normalize_bridge_event({
        "channel_jid": payload["channel_jid"],
        "message_id": payload["message_id"],
        "published_at": payload["published_at"],
        "text": payload["text"],
        "media": [
            {key: item[key] for key in ("kind", "mime", "path") if key in item}
            if type(item) is dict else item
            for item in payload["media"]
        ],
    }, received_at=_timestamp(payload["received_at"], "received_at"))
    if payload["event_key"] != event.event_key:
        raise ValueError("queue event key does not match its Channel identity")
    if payload["links"] != list(event.links):
        raise ValueError("queue event links do not match its source text")
    return event
