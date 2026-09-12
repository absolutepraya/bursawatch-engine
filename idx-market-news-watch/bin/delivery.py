from __future__ import annotations

import hashlib
import json
import math
import mimetypes
import os
import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests

from domain import CompanyCandidate, Provider, retry_delay_minutes, source_message_url
from market_data import fallback_company_name, get_market_snapshot
from selection import SelectionCandidate
from state import StateBlockedError, mark_terminal, save_state


DISCORD_API_V10 = "https://discord.com/api/v10"
_DISCORD_MESSAGE_LIMIT = 2_000
_INVESTMENT_TERMS = (
    "buy",
    "sell",
    "hold",
    "target price",
    "stop loss",
    "entry price",
    "recommend",
    "recommendation",
)
_PROVIDER_EMOJIS = {
    "Tuntun": "<:tuntun:1531272430985937086>",
    "Phintraco": "<:phintraco:1531272488645038091>",
}
_DIRECTION_EMOJIS = {
    "positive": "<:green:1531274822221434911>",
    "negative": "<:red:1531274756853202974>",
    "flat": "<:grey:1531279158913536182>",
}
_ENTRY_SEPARATOR = "┈" * 13
_RINGKASAN_PREFIX = "*(Ringkasan)* "


class DiscordRateLimited(RuntimeError):
    """Discord rejected the request with a delay that the caller must respect."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Discord rate limited for {retry_after:g} seconds")


class DiscordRejected(RuntimeError):
    """Discord returned a non-success response other than rate limiting."""


def _require_selection_candidate(item: object) -> SelectionCandidate:
    if not isinstance(item, SelectionCandidate):
        raise ValueError("delivery requires a SelectionCandidate")
    return item


def _source_name(item: SelectionCandidate) -> str:
    return item.provider.value.title()


def _contains_investment_language(value: str) -> bool:
    normalized = " ".join(value.casefold().split())
    return any(re.search(rf"\b{re.escape(term)}\b", normalized) is not None for term in _INVESTMENT_TERMS)


def _idr(value: float, *, signed: bool = False) -> str:
    rounded = round(abs(value))
    prefix = "+" if signed and value > 0 else "-" if signed and value < 0 else ""
    return f"{prefix}{rounded:,}".replace(",", ".")


def _change(value: float, percent: float, *, decimal_separator: str = ",") -> str:
    percent_text = f"{percent:+.2f}".replace(".", decimal_separator)
    return f"{_idr(value, signed=True)} ({percent_text}%)"


def _direction_emoji(value: float | None) -> str:
    if value is None:
        return _DIRECTION_EMOJIS["flat"]
    if value > 0:
        return _DIRECTION_EMOJIS["positive"]
    if value < 0:
        return _DIRECTION_EMOJIS["negative"]
    return _DIRECTION_EMOJIS["flat"]


def _render_tuntun_summary(item: SelectionCandidate) -> str:
    return f"{_RINGKASAN_PREFIX}{item.summary}"


def _legacy_entry(item: SelectionCandidate) -> str:
    summary = item.summary
    if _contains_investment_language(summary):
        raise ValueError("delivery facts must not contain investment language")
    snapshot = get_market_snapshot(item.ticker, item.candidate.source_text)
    company_name = snapshot.company_name if snapshot is not None else fallback_company_name(item.ticker, item.candidate.source_text)
    lines = [
        f"### {_PROVIDER_EMOJIS[_source_name(item)]} {item.ticker} ({company_name})",
        summary,
        _ENTRY_SEPARATOR,
    ]
    if snapshot is not None:
        lines.append(
            f"*Harga terakhir (IDR):* {_idr(snapshot.latest_price)}\n"
            f"{_direction_emoji(snapshot.one_day_change)}1D: {_change(snapshot.one_day_change, snapshot.one_day_percent)}\n"
            f"{_direction_emoji(snapshot.one_week_change)}1W: {_change(snapshot.one_week_change, snapshot.one_week_percent)}"
        )
    else:
        lines.append(
            "Harga terakhir (IDR): -\n"
            f"{_DIRECTION_EMOJIS['flat']}1D: -\n"
            f"{_DIRECTION_EMOJIS['flat']}1W: -"
        )
    return "\n".join(lines)


def _tuntun_change(value: float | None, percent: float | None, label: str) -> str:
    if value is None or percent is None:
        return f"{_DIRECTION_EMOJIS['flat']} {label}: **-**"
    return f"{_direction_emoji(value)} {label}: **{_change(value, percent, decimal_separator='.')}**"


def _tuntun_entry(item: SelectionCandidate) -> str:
    summary = _render_tuntun_summary(item)
    if _contains_investment_language(summary):
        raise ValueError("delivery facts must not contain investment language")
    snapshot = get_market_snapshot(item.ticker, item.candidate.source_text)
    market_lines = [
        f"Harga terakhir (IDR): **{_idr(snapshot.latest_price) if snapshot is not None else '-'}**",
        ", ".join(
            (
                _tuntun_change(snapshot.one_day_change, snapshot.one_day_percent, "1D"),
                _tuntun_change(snapshot.one_week_change, snapshot.one_week_percent, "1W"),
                _tuntun_change(snapshot.one_month_change, snapshot.one_month_percent, "1M"),
                _tuntun_change(snapshot.three_month_change, snapshot.three_month_percent, "3M"),
            )
            if snapshot is not None
            else (
                _tuntun_change(None, None, "1D"),
                _tuntun_change(None, None, "1W"),
                _tuntun_change(None, None, "1M"),
                _tuntun_change(None, None, "3M"),
            )
        ),
    ]
    return "\n\n".join((f"### {_PROVIDER_EMOJIS['Tuntun']} {item.title}", summary, "\n".join(market_lines)))


def _entry(item: SelectionCandidate) -> str:
    if item.provider is Provider.TUNTUN and item.title:
        return _tuntun_entry(item)
    return _legacy_entry(item)


def _require_discord_length(content: str) -> None:
    if len(content) > _DISCORD_MESSAGE_LIMIT:
        raise ValueError("Discord content exceeds the 2,000-character limit")


def format_news_item(item: SelectionCandidate) -> str:
    """Render one factual company-news alert without delivery-window grouping."""
    item = _require_selection_candidate(item)
    content = _entry(item)
    _require_discord_length(content)
    return content


def discord_nonce(event_key: str, leg: str) -> str:
    if not isinstance(event_key, str) or not event_key or not isinstance(leg, str) or not leg:
        raise ValueError("nonce identity requires nonempty event key and leg")
    return hashlib.sha256(f"idx-market-news:{event_key}:{leg}".encode("utf-8")).hexdigest()[:24]


def _discord_token() -> str | None:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    return token if token else None


def _retry_after(response: object) -> float:
    delay = 1.0
    try:
        payload = response.json()  # type: ignore[attr-defined]
        delay = float(payload.get("retry_after", delay))
    except (AttributeError, TypeError, ValueError):
        try:
            delay = float(response.headers.get("Retry-After", delay))  # type: ignore[attr-defined]
        except (AttributeError, TypeError, ValueError):
            delay = 1.0
    return delay if math.isfinite(delay) and delay >= 0 else 1.0


def _discord_request(*, headers: dict[str, str], **kwargs: object):
    response = requests.request("POST", kwargs.pop("url"), headers=headers, timeout=20, **kwargs)
    if response.status_code == 429:
        raise DiscordRateLimited(_retry_after(response))
    return response


def _message_id(response: object) -> str | None:
    if response is None:
        raise DiscordRejected("Discord returned no response")
    status = getattr(response, "status_code", None)
    if status not in (200, 201):
        detail = "unknown error"
        try:
            message = response.json().get("message")  # type: ignore[attr-defined]
            if isinstance(message, str) and message.strip():
                detail = message.strip()[:180]
        except (AttributeError, TypeError, ValueError):
            pass
        raise DiscordRejected(f"Discord HTTP {status}: {detail}")
    try:
        identifier = response.json()["id"]  # type: ignore[attr-defined]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise DiscordRejected("Discord success response omitted a message id")
    return str(identifier)


def post_discord_text(content: str, channel_id: str, event_key: str, dry_run: bool = False) -> str | None:
    """Post a Discord text message using an idempotency nonce."""
    if not isinstance(content, str):
        raise ValueError("Discord content must be text")
    _require_discord_length(content)
    if not isinstance(channel_id, str) or not channel_id:
        raise ValueError("Discord channel id must be nonempty text")
    payload = {
        "content": content,
        "nonce": discord_nonce(event_key, "text"),
        "enforce_nonce": True,
    }
    if dry_run:
        return f"dry-text-{event_key}"
    token = _discord_token()
    if token is None:
        return None
    response = _discord_request(
        url=f"{DISCORD_API_V10}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json=payload,
    )
    return _message_id(response)


def post_discord_image(path: str | os.PathLike[str], channel_id: str, event_key: str, dry_run: bool = False) -> str | None:
    """Upload one cached source photo, never a media preview or derived image."""
    image_path = Path(path)
    try:
        if not image_path.is_file() or image_path.stat().st_size == 0:
            return None
    except OSError:
        return None
    if not isinstance(channel_id, str) or not channel_id:
        raise ValueError("Discord channel id must be nonempty text")
    if dry_run:
        return f"dry-image-{event_key}"
    token = _discord_token()
    if token is None:
        return None
    payload = {
        "content": "",
        "nonce": discord_nonce(event_key, "image"),
        "enforce_nonce": True,
    }
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    with image_path.open("rb") as image:
        response = _discord_request(
            url=f"{DISCORD_API_V10}/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {token}"},
            data={"payload_json": json.dumps(payload)},
            files={"files[0]": (image_path.name, image, mime_type)},
        )
    return _message_id(response)


def _default_media_directory() -> Path:
    state_path = os.environ.get("IDX_MARKET_NEWS_STATE_PATH")
    if state_path:
        return Path(state_path).expanduser().parent / "media"
    return Path(__file__).resolve().parents[1] / "media"


def _write_private_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    with NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            os.fchmod(temporary.fileno(), 0o600)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        except BaseException:
            temporary_path.unlink(missing_ok=True)
            raise
    os.replace(temporary_path, path)
    os.chmod(path, 0o600)


async def capture_direct_image(
    client: object,
    entity: object,
    candidate: object,
    media_directory: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Cache only a photo returned for this candidate's exact source-message id."""
    source = candidate.candidate if isinstance(candidate, SelectionCandidate) else candidate
    if not isinstance(source, CompanyCandidate):
        raise ValueError("image capture requires a company candidate")
    source_message_id = source.source_message_id
    provider = source.provider
    message = await client.get_messages(entity, ids=source_message_id)  # type: ignore[attr-defined]
    if message is None or getattr(message, "id", None) != source_message_id or not getattr(message, "photo", None):
        return None
    content = await client.download_media(message, file=bytes)  # type: ignore[attr-defined]
    if not isinstance(content, bytes) or not content:
        return None
    directory = Path(media_directory) if media_directory is not None else _default_media_directory()
    path = directory / f"{provider.value}-{source_message_id}.jpg"
    _write_private_bytes(path, content)
    return path


def _delivery_records(state: dict[str, object]) -> dict[str, object]:
    stats = state.get("stats")
    if not isinstance(stats, dict):
        raise StateBlockedError("malformed state: stats must be an object")
    records = stats.get("delivery_payloads")
    if records is None:
        records = {}
        stats["delivery_payloads"] = records
    if not isinstance(records, dict):
        raise StateBlockedError("malformed state: delivery payloads must be an object")
    return records


def _persist_text_payload(
    state: dict[str, object],
    items: Sequence[SelectionCandidate],
    content: str,
    event_key: str,
) -> None:
    records = _delivery_records(state)
    nonce = discord_nonce(event_key, "text")
    for item in items:
        records[item.key] = {
            "content": content,
            "nonce": nonce,
            "enforce_nonce": True,
            "text_discord_id": None,
            "image_discord_id": None,
            "image_error": None,
        }
    save_state(state)


def _existing_text_payload(state: dict[str, object], item: SelectionCandidate) -> str | None:
    records = _delivery_records(state)
    record = records.get(item.key)
    if not isinstance(record, dict):
        return None
    content = record.get("content")
    return content if isinstance(content, str) and content else None


def _update_delivery_record(state: dict[str, object], item: SelectionCandidate, **changes: object) -> None:
    records = _delivery_records(state)
    record = records.get(item.key)
    if not isinstance(record, dict):
        raise StateBlockedError(f"candidate {item.key!r} has no persisted delivery payload")
    record.update(changes)
    save_state(state)


def _mark_text_delivered(state: dict[str, object], items: Sequence[SelectionCandidate], message_id: str, now: datetime) -> None:
    for item in items:
        mark_terminal(state, item.key, "delivered")
        _update_delivery_record(state, item, text_discord_id=message_id)
    state["last_delivery_success"] = now.isoformat()
    save_state(state)


def _schedule_delivery_retry(
    state: dict[str, object],
    items: Sequence[SelectionCandidate],
    now: datetime,
    error: str,
    minimum_delay_seconds: float = 0,
) -> None:
    """Atomically retain an event in delivery with its durable payload and retry metadata."""
    if not math.isfinite(minimum_delay_seconds) or minimum_delay_seconds < 0:
        raise ValueError("minimum retry delay must be a finite non-negative number")
    candidates = state.get("candidates")
    if not isinstance(candidates, dict):
        raise StateBlockedError("malformed state: candidates must be an object")
    retry_floor = now + timedelta(seconds=minimum_delay_seconds)
    for item in items:
        record = candidates.get(item.key)
        if not isinstance(record, dict) or record.get("phase") != "pending_delivery":
            raise StateBlockedError(f"candidate {item.key!r} is not awaiting delivery")
        retry = record.get("retry")
        if not isinstance(retry, dict):
            raise StateBlockedError(f"candidate {item.key!r} has invalid retry state")
        attempts = retry.get("attempts")
        if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 0:
            raise StateBlockedError(f"candidate {item.key!r} has invalid retry attempts")
        due_at = max(now + timedelta(minutes=retry_delay_minutes(attempts)), retry_floor)
        retry["attempts"] = attempts + 1
        retry["next_attempt_at"] = due_at.isoformat()
        retry["last_error"] = error
        record["agent_lease_until"] = None
    save_state(state)


async def deliver_event(
    state: dict[str, object],
    event: SelectionCandidate,
    channel_id: str,
    now: datetime,
    *,
    dry_run: bool = False,
    client: object | None = None,
    entity: object | None = None,
    media_directory: str | os.PathLike[str] | None = None,
) -> bool:
    """Persist, post, and terminally mark one standalone company-news alert."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("delivery time must be timezone-aware")
    item = _require_selection_candidate(event)
    items = [item]
    event_key = f"{item.key}:text"
    content = _existing_text_payload(state, item)
    if content is None:
        content = format_news_item(item)
        _persist_text_payload(state, items, content, event_key)
    try:
        message_id = post_discord_text(content, channel_id, event_key, dry_run=dry_run)
    except DiscordRateLimited as error:
        _schedule_delivery_retry(state, items, now, str(error), minimum_delay_seconds=error.retry_after)
        return False
    except Exception as error:
        _schedule_delivery_retry(state, items, now, str(error))
        return False
    if message_id is None:
        _schedule_delivery_retry(state, items, now, "Discord text delivery failed")
        return False
    _mark_text_delivered(state, items, message_id, now)
    return True
