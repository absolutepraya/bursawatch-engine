from __future__ import annotations

from pathlib import Path as _NewsPath
import sys as _news_sys
_news_bin = _NewsPath(__file__).resolve().parents[2] / "lib-news-format" / "bin"
if not _news_bin.is_dir():
    _news_bin = _NewsPath.home() / ".agents/skills/lib-news-format/bin"
if str(_news_bin) not in _news_sys.path:
    _news_sys.path.insert(0, str(_news_bin))
import news_format

import hashlib
import math
import mimetypes
import os
import re
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

from domain import CompanyCandidate, Destination, Provider, retry_delay_minutes, source_message_url
from market_data import fallback_company_name, get_market_snapshot
from selection import SelectionCandidate
from state import (
    StateBlockedError,
    clear_retry,
    mark_stock_status_delivered,
    mark_terminal,
    pending_stock_status_events,
    save_state,
    schedule_stock_status_retry,
)

try:
    from bursawatch_discord_delivery import (
        DELIVERY_RECEIPT_WAIT_SECONDS,
        Attachment,
        DeliveryClient,
        OperationIntent,
        OperationReceipt,
    )
    from bursawatch_discord_delivery.client import DeliveryClientError
except ModuleNotFoundError:
    # Development checkout fallback. Runtime wrappers add the installed shared
    # library path before invoking this package.
    _repository_root = Path(__file__).resolve().parents[2]
    _shared_library = _repository_root / "lib-bursawatch-discord-delivery" / "bin"
    if _shared_library.is_dir():
        sys.path.insert(0, str(_shared_library))
    from bursawatch_discord_delivery import (
        DELIVERY_RECEIPT_WAIT_SECONDS,
        Attachment,
        DeliveryClient,
        OperationIntent,
        OperationReceipt,
    )
    from bursawatch_discord_delivery.client import DeliveryClientError

_DISCORD_MESSAGE_LIMIT = 2_000
_DELIVERY_OWNER_PREFIX = "bursawatch-market-news"
_DELIVERY_OWNER_URL = "http://127.0.0.1:9140"
_DELIVERY_OWNER_TOKEN_FILE = ".hermes/secrets/bursawatch-discord-delivery-client-token"
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


def _issuer_entry(
    item: SelectionCandidate,
    heading: str,
    *,
    snapshot=None,
    load_market_data: bool = True,
    market_metadata: dict | None = None,
) -> str:
    summary = _render_tuntun_summary(item)
    if _contains_investment_language(summary):
        raise ValueError("delivery facts must not contain investment language")
    if load_market_data and item.route is Destination.ID_STOCKS_NEWS and item.ticker is not None:
        snapshot = get_market_snapshot(item.ticker, item.candidate.source_text)
    if market_metadata is not None:
        market_metadata.update(market_data_as_of=getattr(snapshot, "as_of", None), renderer_version=news_format.VERSION)
    messages = news_format.render_card(heading, summary, source_message_url(item.candidate), "Telegram", route=item.route.value, snapshot=snapshot)
    # This owner's historical contract remains one card per candidate.
    return "\n\n".join(messages)


def _tuntun_entry(item: SelectionCandidate, market_metadata=None) -> str:
    return _issuer_entry(item, f"### {_PROVIDER_EMOJIS['Tuntun']} {item.title}\n-# Tuntun", market_metadata=market_metadata)


def _phintraco_entry(item: SelectionCandidate, market_metadata=None) -> str:
    if item.route is not Destination.ID_STOCKS_NEWS or item.ticker is None:
        raise ValueError("Phintraco issuer entries require a ticker")
    snapshot = get_market_snapshot(item.ticker, item.candidate.source_text)
    company_name = (
        snapshot.company_name
        if snapshot is not None
        else fallback_company_name(item.ticker, item.candidate.source_text)
    )
    return _issuer_entry(
        item,
        f"### {_PROVIDER_EMOJIS['Phintraco']} {item.title or f'{item.ticker}: {company_name}'}\n-# Phintraco",
        snapshot=snapshot,
        load_market_data=False,
        market_metadata=market_metadata,
    )


def _phintraco_macro_entry(item: SelectionCandidate, market_metadata=None) -> str:
    if item.route is not Destination.MACRO_NEWS:
        raise ValueError("Phintraco macro entries require the macro_news route")
    return _issuer_entry(
        item,
        f"### {_PROVIDER_EMOJIS['Phintraco']} {item.title or 'Phintraco Sekuritas'}\n-# Phintraco",
        load_market_data=False,
        market_metadata=market_metadata,
    )


def _entry(item: SelectionCandidate, market_metadata=None) -> str:
    if item.provider is Provider.TUNTUN and item.title:
        return _tuntun_entry(item, market_metadata)
    if item.provider is Provider.PHINTRACO:
        if item.route is Destination.MACRO_NEWS:
            return _phintraco_macro_entry(item, market_metadata)
        if item.route is Destination.ID_STOCKS_NEWS:
            return _phintraco_entry(item, market_metadata)
        raise ValueError("excluded Phintraco item cannot be delivered")
    return _legacy_entry(item)


def _require_discord_length(content: str) -> None:
    if news_format.discord_length(content) > _DISCORD_MESSAGE_LIMIT:
        raise ValueError("Discord content exceeds the 2,000-character limit")


def format_news_item(item: SelectionCandidate, *, market_metadata=None) -> str:
    """Render one factual company-news alert without delivery-window grouping."""
    item = _require_selection_candidate(item)
    content = _entry(item, market_metadata)
    _require_discord_length(content)
    return content


def discord_nonce(event_key: str, leg: str) -> str:
    if not isinstance(event_key, str) or not event_key or not isinstance(leg, str) or not leg:
        raise ValueError("nonce identity requires nonempty event key and leg")
    return hashlib.sha256(f"idx-market-news:{event_key}:{leg}".encode("utf-8")).hexdigest()[:24]


def delivery_client_from_environment(*, include_admin: bool = False) -> DeliveryClient:
    """Build the shared client from its URL and private token-file paths."""
    base_url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", _DELIVERY_OWNER_URL)
    token_path = Path(
        os.environ.get(
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
            str(Path.home() / _DELIVERY_OWNER_TOKEN_FILE),
        )
    ).expanduser()
    admin_path = None
    if include_admin:
        configured_admin_path = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE")
        if not configured_admin_path:
            raise DeliveryClientError("admin_credentials_required")
        admin_path = Path(configured_admin_path).expanduser()
    return DeliveryClient(base_url, token_path, admin_token_file=admin_path)


def _operation_key(event_key: str, leg: str) -> str:
    if not isinstance(event_key, str) or not event_key or not isinstance(leg, str) or not leg:
        raise ValueError("delivery identity requires a nonempty event key and leg")
    leg_key = event_key if event_key.endswith(f":{leg}") else f"{event_key}:{leg}"
    # Keep caller event/leg identity stable while encoding characters that the
    # shared operation-key contract does not permit (notably the WIB '+' offset).
    safe_leg_key = re.sub(
        r"[^A-Za-z0-9:_./-]",
        lambda match: f"_u{ord(match.group()):04x}_",
        leg_key,
    )
    return f"{_DELIVERY_OWNER_PREFIX}:{safe_leg_key}"


def _channel_message_operation(
    content: str,
    channel_id: str,
    event_key: str,
    *,
    leg: str = "text",
    attachments: Sequence[Attachment] = (),
    reconcile_before_first_create: bool = False,
    legacy_nonce: str | None = None,
) -> OperationIntent:
    if not isinstance(content, str):
        raise ValueError("Discord content must be text")
    _require_discord_length(content)
    if not isinstance(channel_id, str) or not channel_id:
        raise ValueError("Discord channel id must be nonempty text")
    return OperationIntent(
        key=_operation_key(event_key, leg),
        kind="channel_message_create",
        ordering_key=f"channel:{channel_id}",
        target={"channel_id": channel_id},
        payload={"content": content, "allowed_mentions": {"parse": []}},
        attachments=tuple(attachments),
        reconcile_before_first_create=reconcile_before_first_create,
        legacy_nonce=legacy_nonce,
    )


def _require_matching_receipt(operation: OperationIntent, receipt: object) -> OperationReceipt:
    if (not isinstance(receipt, OperationReceipt) or receipt.key != operation.key
            or receipt.digest != operation.digest):
        raise DeliveryClientError("invalid_response")
    return receipt


def _delivered_message_id(receipt: OperationReceipt, channel_id: str) -> str | None:
    if receipt.status != "delivered" or not isinstance(receipt.receipt, dict):
        return None
    if receipt.receipt.get("channel_id") not in (None, channel_id):
        raise DeliveryClientError("invalid_response")
    message_id = receipt.receipt.get("message_id")
    return message_id if isinstance(message_id, str) and message_id.isdigit() else None


def _submit_or_lookup(
    operation: OperationIntent,
    client: object,
) -> OperationReceipt:
    receipt = client.status(operation.key)  # type: ignore[attr-defined]
    if receipt is None:
        receipt = client.submit(operation)  # type: ignore[attr-defined]
    accepted = _require_matching_receipt(operation, receipt)
    if accepted.status in {"pending", "pending_reconciliation", "retrying", "delivering"}:
        accepted = _require_matching_receipt(
            operation,
            client.wait(operation.key, DELIVERY_RECEIPT_WAIT_SECONDS),  # type: ignore[attr-defined]
        )
    return accepted


def post_discord_text(
    content: str,
    channel_id: str,
    event_key: str,
    dry_run: bool = False,
    *,
    client: object | None = None,
) -> str | None:
    """Submit one idempotent text operation to the shared Delivery Owner."""
    operation = _channel_message_operation(content, channel_id, event_key)
    if dry_run:
        return f"dry-text-{event_key}"
    owner = client if client is not None else delivery_client_from_environment()
    receipt = _submit_or_lookup(operation, owner)
    return _delivered_message_id(receipt, channel_id)


def post_discord_image(
    path: str | os.PathLike[str],
    channel_id: str,
    event_key: str,
    dry_run: bool = False,
    *,
    client: object | None = None,
) -> str | None:
    """Submit the exact cached source-photo bytes as one ordered owner operation."""
    image_path = Path(path)
    try:
        if not image_path.is_file() or image_path.stat().st_size == 0:
            return None
        content = image_path.read_bytes()
    except OSError:
        return None
    if not isinstance(channel_id, str) or not channel_id:
        raise ValueError("Discord channel id must be nonempty text")
    if dry_run:
        return f"dry-image-{event_key}"
    mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    attachment = Attachment(image_path.name, mime_type, content)
    operation = _channel_message_operation(
        "", channel_id, event_key, leg="image", attachments=(attachment,)
    )
    owner = client if client is not None else delivery_client_from_environment()
    receipt = _submit_or_lookup(operation, owner)
    return _delivered_message_id(receipt, channel_id)


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
    channel_id: str,
    market_metadata=None,
) -> None:
    records = _delivery_records(state)
    nonce = discord_nonce(event_key, "text")
    for item in items:
        records[item.key] = {
            "content": content,
            "nonce": nonce,
            "enforce_nonce": True,
            "channel_id": channel_id,
            "required_operation_keys": [_operation_key(event_key, "text")],
            "text_discord_id": None,
            "image_discord_id": None,
            "image_error": None,
            "delivery_handoff": {
                "state": "unknown",
                "operation_key": _operation_key(event_key, "text"),
                "receipt": None,
            },
        }
        if market_metadata is not None:
            records[item.key].update(market_metadata)
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


def _receipt_document(receipt: OperationReceipt) -> dict[str, object]:
    return {
        "id": receipt.id,
        "key": receipt.key,
        "digest": receipt.digest,
        "status": receipt.status,
        "receipt": dict(receipt.receipt) if receipt.receipt is not None else None,
    }


def _store_handoff_receipt(
    state: dict[str, object], item: SelectionCandidate, receipt: OperationReceipt
) -> None:
    _update_delivery_record(
        state,
        item,
        delivery_handoff={
            "state": "accepted",
            "operation_key": receipt.key,
            "receipt": _receipt_document(receipt),
        },
    )


def _delivery_error_category(error: Exception) -> str:
    if isinstance(error, DeliveryClientError):
        return f"Delivery Owner request failed ({error.category})"
    return "Delivery Owner acceptance could not be confirmed"


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
    delivery_client: object | None = None,
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
        market_metadata = {}
        content = format_news_item(item, market_metadata=market_metadata)
        _persist_text_payload(state, items, content, event_key, channel_id, market_metadata)
    records = _delivery_records(state)
    record = records.get(item.key)
    if not isinstance(record, dict):
        raise StateBlockedError(f"candidate {item.key!r} has no persisted delivery payload")
    saved_channel_id = record.get("channel_id")
    if isinstance(saved_channel_id, str) and saved_channel_id:
        channel_id = saved_channel_id
    else:
        record["channel_id"] = channel_id
        save_state(state)

    operation = _channel_message_operation(content, channel_id, event_key)
    raw_handoff = record.get("delivery_handoff")
    if not isinstance(raw_handoff, dict):
        # A known legacy Discord ID can be adopted only by the separately
        # gated handoff command. Never replay it from an ordinary cron run.
        if isinstance(record.get("text_discord_id"), str) and record["text_discord_id"]:
            return False
        raw_handoff = {
            "state": "unknown",
            "operation_key": operation.key,
            "receipt": None,
        }
        record["delivery_handoff"] = raw_handoff
        save_state(state)
    if set(raw_handoff) != {"state", "operation_key", "receipt"}:
        raise StateBlockedError(f"candidate {item.key!r} has invalid delivery handoff metadata")
    if raw_handoff.get("operation_key") != operation.key:
        raise StateBlockedError(f"candidate {item.key!r} has a different accepted operation key")
    if raw_handoff.get("state") == "accepted":
        saved_receipt = raw_handoff.get("receipt")
        saved_digest = saved_receipt.get("digest") if isinstance(saved_receipt, dict) else None
        if saved_digest != operation.digest:
            try:
                migrated_operation = _channel_message_operation(
                    content,
                    channel_id,
                    event_key,
                    reconcile_before_first_create=True,
                    legacy_nonce=record.get("nonce") if isinstance(record.get("nonce"), str) else None,
                )
            except ValueError:
                raise StateBlockedError(f"candidate {item.key!r} has an invalid accepted operation") from None
            if migrated_operation.digest != saved_digest:
                raise StateBlockedError(f"candidate {item.key!r} has a different accepted operation digest")
            operation = migrated_operation

    if dry_run:
        message_id = f"dry-text-{item.key}"
        _mark_text_delivered(state, items, message_id, now)
        return True

    owner = delivery_client if delivery_client is not None else delivery_client_from_environment()
    accepted_state = raw_handoff.get("state") == "accepted"
    try:
        if accepted_state:
            raw_receipt = raw_handoff.get("receipt")
            try:
                stored_receipt = OperationReceipt.from_json(raw_receipt, operation)
            except (TypeError, ValueError):
                raise DeliveryClientError("invalid_response") from None
            if stored_receipt.status == "delivered" and _delivered_message_id(stored_receipt, channel_id):
                latest = stored_receipt
            else:
                latest = _require_matching_receipt(operation, owner.status(operation.key))  # type: ignore[attr-defined]
                if latest is None:
                    return False
        else:
            latest = owner.status(operation.key)  # type: ignore[attr-defined]
            if latest is None:
                latest = owner.submit(operation)  # type: ignore[attr-defined]
            latest = _require_matching_receipt(operation, latest)
            _store_handoff_receipt(state, item, latest)
            clear_retry(state, item.key)
            accepted_state = True
        if latest.status in {"pending", "pending_reconciliation", "retrying", "delivering"}:
            latest = _require_matching_receipt(
                operation,
                owner.wait(operation.key, DELIVERY_RECEIPT_WAIT_SECONDS),  # type: ignore[attr-defined]
            )
            _store_handoff_receipt(state, item, latest)
        message_id = _delivered_message_id(latest, channel_id)
    except Exception as error:
        if not accepted_state:
            _schedule_delivery_retry(state, items, now, _delivery_error_category(error))
        return False
    if message_id is None:
        return False
    _store_handoff_receipt(state, item, latest)
    from publication_projection import record_news_intent

    record_news_intent(state, item, now)
    _mark_text_delivered(state, items, message_id, now)
    return True


async def deliver_stock_status_event(
    state: dict[str, object],
    event_key: str,
    now: datetime,
    *,
    dry_run: bool = False,
    delivery_client: object | None = None,
) -> bool:
    """Deliver one frozen status event through the shared Delivery Owner."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("delivery time must be timezone-aware")
    due_events = dict(pending_stock_status_events(state, now))
    event = due_events.get(event_key)
    if event is None:
        stats = state.get("stats")
        records = stats.get("stock_status_events") if isinstance(stats, dict) else None
        record = records.get(event_key) if isinstance(records, dict) else None
        if isinstance(record, dict) and record.get("phase") == "pending_delivery":
            return False
        raise StateBlockedError(f"status event {event_key!r} is not pending delivery")
    content = event.get("content")
    channel_id = event.get("channel_id")
    if not isinstance(content, str) or not content or len(content) > _DISCORD_MESSAGE_LIMIT:
        raise StateBlockedError(f"status event {event_key!r} has invalid persisted content")
    if not isinstance(channel_id, str) or not channel_id:
        raise StateBlockedError(f"status event {event_key!r} has no frozen destination")

    operation = _channel_message_operation(content, channel_id, event_key)
    raw_handoff = event.get("delivery_handoff")
    if raw_handoff is None:
        raw_handoff = {
            "state": "unknown",
            "operation_key": operation.key,
            "receipt": None,
        }
        event["delivery_handoff"] = raw_handoff
        save_state(state)
    if not isinstance(raw_handoff, dict) or set(raw_handoff) != {
        "state", "operation_key", "receipt"
    }:
        raise StateBlockedError(f"status event {event_key!r} has invalid delivery handoff metadata")
    if raw_handoff.get("operation_key") != operation.key:
        raise StateBlockedError(f"status event {event_key!r} has a different operation key")

    if dry_run:
        message_id = post_discord_text(content, channel_id, event_key, dry_run=True)
        if message_id is None:
            return False
        mark_stock_status_delivered(state, event_key, message_id, now)
        state["last_delivery_success"] = now.isoformat()
        save_state(state)
        return True

    owner = delivery_client if delivery_client is not None else delivery_client_from_environment()
    accepted_state = raw_handoff.get("state") == "accepted"
    try:
        if accepted_state:
            try:
                stored_receipt = OperationReceipt.from_json(raw_handoff.get("receipt"), operation)
            except (TypeError, ValueError):
                raise DeliveryClientError("invalid_response") from None
            if stored_receipt.status == "delivered" and _delivered_message_id(stored_receipt, channel_id):
                latest = stored_receipt
            else:
                latest = _require_matching_receipt(operation, owner.status(operation.key))  # type: ignore[attr-defined]
                if latest is None:
                    return False
        else:
            latest = owner.status(operation.key)  # type: ignore[attr-defined]
            if latest is None:
                latest = owner.submit(operation)  # type: ignore[attr-defined]
            latest = _require_matching_receipt(operation, latest)
            _store_stock_status_handoff(event, latest)
            save_state(state)
            accepted_state = True
        if latest.status in {"pending", "pending_reconciliation", "retrying", "delivering"}:
            latest = _require_matching_receipt(
                operation,
                owner.wait(operation.key, DELIVERY_RECEIPT_WAIT_SECONDS),  # type: ignore[attr-defined]
            )
            _store_stock_status_handoff(event, latest)
            save_state(state)
        message_id = _delivered_message_id(latest, channel_id)
    except Exception as error:
        if not accepted_state:
            schedule_stock_status_retry(
                state, event_key, now, _delivery_error_category(error)
            )
        return False
    if message_id is None:
        return False

    _store_stock_status_handoff(event, latest)
    from publication_projection import record_stock_status_intent

    record_stock_status_intent(state, event_key, now)
    mark_stock_status_delivered(state, event_key, message_id, now)
    state["last_delivery_success"] = now.isoformat()
    save_state(state)
    return True


def _store_stock_status_handoff(event: dict[str, object], receipt: OperationReceipt) -> None:
    event["delivery_handoff"] = {
        "state": "accepted",
        "operation_key": receipt.key,
        "receipt": _receipt_document(receipt),
    }
