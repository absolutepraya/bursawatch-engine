"""Receipt-backed Phintraco plan projection into the Published read model."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import scan


OWNER_ID = "bursawatch-tg-phintraco-swing"
RENDERER_VERSION = "phintraco-swing-v1"
_PDF_BOARD_KEY = re.compile(r"^phintraco:[0-9]+:weekly:([0-9]+):([A-Z]{4})$")
_PUBLICATION_LEDGER = "publication_projection"


class IncompletePublication(ValueError):
    """The owner lacks exact receipt evidence for all required delivery legs."""


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def publication_id(owner_key: str) -> str:
    return hashlib.sha256(_canonical([OWNER_ID, owner_key])).hexdigest()


def _ledger(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    projection = state.setdefault(_PUBLICATION_LEDGER, {"records": {}})
    if type(projection) is not dict or set(projection) != {"records"} or type(projection["records"]) is not dict:
        raise ValueError("Phintraco publication ledger is invalid")
    return projection["records"]


def _receipt_leg(
    operation: Any,
    receipt_document: object,
    *,
    text: str | None,
    attachments: list[dict[str, str | None]],
) -> dict[str, Any]:
    try:
        from bursawatch_discord_delivery import OperationReceipt

        receipt = OperationReceipt.from_json(receipt_document, operation)
    except (ImportError, TypeError, ValueError):
        raise IncompletePublication("stored Phintraco delivery receipt is invalid") from None
    destination = operation.target.get("channel_id")
    if (
        receipt.status != "delivered"
        or receipt.receipt is None
        or receipt.receipt.get("channel_id") != destination
    ):
        raise IncompletePublication("Phintraco delivery receipt does not confirm its destination")
    message_id = receipt.receipt.get("message_id")
    if not isinstance(message_id, str) or not message_id.isdigit():
        raise IncompletePublication("Phintraco delivery receipt has no Discord message ID")
    return {
        "operation_key": operation.key,
        "operation_digest": operation.digest,
        "receipt_operation_id": receipt.id,
        "destination": destination,
        "receipt_id": message_id,
        "status": "delivered",
        "message_url": None,
        "text": text,
        "attachments": attachments,
        "receipt_key": receipt.key,
        "receipt_digest": receipt.digest,
        "receipt_destination": destination,
        "receipt_message_id": message_id,
    }


def _linked_plan_owner_key(event: dict[str, Any]) -> str | None:
    match = _PDF_BOARD_KEY.fullmatch(str(event.get("matched_setup_event_key") or ""))
    if match is None:
        return None
    message_id, ticker = match.groups()
    return f"phintraco:pdf:{message_id}:{ticker}"


def publication_snapshot(
    state: dict[str, Any], event: dict[str, Any], confirmed_at: datetime
) -> dict[str, Any] | None:
    """Build a snapshot only for an exact delivered plan or known linked update."""
    if event.get("phase") not in {scan.PHASE_PENDING_BOARD, scan.PHASE_DELIVERED}:
        return None
    call = scan.deserialize_call(event["call"])
    text = event.get("text_output")
    destination = event.get("text_destination")
    if type(text) is not str or not text or type(destination) is not str:
        raise IncompletePublication("Phintraco source alert output is not durably recorded")
    text_operation = scan._channel_message_operation(text, destination, event["event_key"], leg="text")
    legs = [_receipt_leg(text_operation, event.get("text_receipt"), text=text, attachments=[])]
    required_operation_keys = [text_operation.key]

    if call.has_source_chart:
        chart_path = scan._cached_media_path(event)
        if chart_path is None or event.get("chart_receipt") is None:
            raise IncompletePublication("Phintraco source chart has no confirmed delivery receipt")
        chart_bytes = chart_path.read_bytes()
        if not chart_bytes:
            raise IncompletePublication("Phintraco source chart is empty")
        chart_name = event.get("chart_filename")
        chart_type = event.get("chart_content_type")
        chart_destination = event.get("chart_destination")
        if type(chart_name) is not str or not chart_name or chart_type != "image/jpeg" or type(chart_destination) is not str:
            raise IncompletePublication("Phintraco source chart metadata is incomplete")
        chart_operation = scan._channel_message_operation(
            "", chart_destination, event["event_key"], leg="chart",
            attachments=(scan.Attachment(chart_name, chart_type, chart_bytes),),
        )
        legs.append(_receipt_leg(
            chart_operation,
            event["chart_receipt"],
            text=None,
            attachments=[{"filename": chart_name, "content_type": chart_type, "discord_url": None}],
        ))
        required_operation_keys.append(chart_operation.key)

    parent_publication_id = None
    if call.event_kind == "BUY":
        if not call.entry or not call.stop_loss or not call.targets or not call.call_subtype:
            return None
        kind = "broker_swing_plan"
        owner_key = f"phintraco:{event['event_key']}"
        attribution = (
            f"{call.advisor_name}, {call.advisor_role} at Phintraco Sekuritas"
            if call.advisor_name and call.advisor_role
            else "Phintraco Sekuritas"
        )
        levels = {
            "entry": call.entry,
            "stop": call.stop_loss,
            "targets": [target.value for target in call.targets],
            "units": "Not stated by source",
            "attribution": attribution,
        }
        title = f"{call.ticker}: {call.call_subtype}"
    elif call.event_kind in {"STATUS", "REMINDER"}:
        parent_owner_key = _linked_plan_owner_key(event)
        if parent_owner_key is None:
            return None
        records = _ledger(state)
        parent = records.get(parent_owner_key)
        if not isinstance(parent, dict) or parent.get("snapshot", {}).get("type") != "broker_swing_plan":
            return None
        kind = "broker_swing_update"
        owner_key = f"phintraco:update:{event['event_key']}"
        parent_publication_id = publication_id(parent_owner_key)
        levels = None
        title = f"{call.ticker}: {call.status or '; '.join(call.outcomes) or 'Source update'}"
    else:
        return None

    if event.get("source_url") is None:
        return None
    now = confirmed_at.astimezone(timezone.utc)
    return {
        "api_version": 1,
        "owner_key": owner_key,
        "version": 1,
        "supersedes_version": None,
        "type": kind,
        "route": "id_stocks_swing",
        "source_event_key": event["event_key"],
        "source_name": "Phintraco Sekuritas",
        "source_url": event["source_url"],
        "source_published_at": call.signal_datetime.isoformat(),
        "market_data_as_of": None,
        "delivery_confirmed_at": now.isoformat(),
        "title": title[:300],
        "ticker": call.ticker,
        "broker_levels": levels,
        "parent_publication_id": parent_publication_id,
        "board_episode_id": None,
        "config_revision": event.get("config_revision"),
        "renderer_version": RENDERER_VERSION,
        "source_version": "phintraco-source-v1",
        "required_operation_keys": required_operation_keys,
        "legs": [{key: value for key, value in leg.items() if key not in {
            "receipt_key", "receipt_digest", "receipt_destination", "receipt_message_id"
        }} for leg in legs],
    }


def record_confirmed_outbox(state: dict[str, Any], now: datetime) -> int:
    if not _feature_enabled():
        return 0
    records = _ledger(state)
    created = 0
    for event in state.get("outbox", {}).values():
        if not isinstance(event, dict):
            continue
        try:
            snapshot = publication_snapshot(state, event, now)
        except (IncompletePublication, OSError):
            continue
        if snapshot is None:
            continue
        owner_key = snapshot["owner_key"]
        existing = records.get(owner_key)
        if existing is not None:
            if existing.get("snapshot") != snapshot:
                raise ValueError("Phintraco publication identity conflicts with its durable snapshot")
            continue
        records[owner_key] = {"snapshot": snapshot, "ack": None}
        scan.save_state(state)
        created += 1
    return created


def pending_publication_intents(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    records = _ledger(state)
    return sorted(
        [(key, item["snapshot"]) for key, item in records.items() if item["ack"] is None],
        key=lambda pair: (pair[1]["delivery_confirmed_at"], pair[0]),
    )


def checkpoint_comparison(state: dict[str, Any], compared_at: datetime) -> dict[str, Any]:
    records = _ledger(state)
    ordered = sorted(records.items(), key=lambda pair: (pair[1]["snapshot"]["delivery_confirmed_at"], pair[0]))
    confirmed = max((item["snapshot"]["delivery_confirmed_at"] for item in records.values()), default=None)
    accepted = None
    for _key, item in ordered:
        if item["ack"] is None:
            break
        accepted = item["snapshot"]["delivery_confirmed_at"]
    if confirmed is not None and all(item["ack"] is not None for item in records.values()):
        accepted = confirmed
    return {
        "compared_at": compared_at.astimezone(timezone.utc).isoformat(),
        "confirmed_through_at": confirmed,
        "accepted_through_at": accepted,
        "outstanding_count": sum(item["ack"] is None for item in records.values()),
    }


def _feature_enabled() -> bool:
    return os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_PUBLICATION_ENABLED") == "1"


def _client() -> Any:
    url = os.environ.get("BURSAWATCH_PUBLICATION_CONTROL_PLANE_URL")
    token_file = os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_PUBLICATION_TOKEN_FILE")
    if not url or not token_file:
        raise ValueError("Phintraco publication client configuration is incomplete")
    path = Path(token_file).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError("Phintraco publication token file permissions are too broad")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("Phintraco publication token file is empty")
    library = Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"
    if not library.is_dir():
        library = Path.home() / ".agents" / "skills" / "lib-bursawatch-control" / "bin"
    if str(library) not in sys.path:
        sys.path.insert(0, str(library))
    from publication_client import PublicationClient

    return PublicationClient(url, token)


def drain(
    state: dict[str, Any],
    now: datetime,
    *,
    dry_run: bool = False,
    client: Any | None = None,
) -> dict[str, int]:
    if (
        dry_run
        or os.environ.get("IDX_SWING_WATCH_PHINTRACO_DAILY_NO_POST") == "1"
        or os.environ.get("BURSAWATCH_RELEASE_NO_POST") == "1"
    ):
        return {"accepted": 0, "pending": len(pending_publication_intents(state))}
    if not _feature_enabled():
        return {"accepted": 0, "pending": len(pending_publication_intents(state))}
    try:
        client = client or _client()
    except Exception:
        return {"accepted": 0, "pending": len(pending_publication_intents(state))}
    records = _ledger(state)
    accepted_count = 0
    for owner_key, snapshot in pending_publication_intents(state):
        try:
            ack = client.submit(snapshot)
            if (
                set(ack) != {"publication_id", "version", "digest"}
                or ack.get("publication_id") != publication_id(owner_key)
                or ack.get("version") != snapshot["version"]
                or not isinstance(ack.get("digest"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", ack["digest"])
            ):
                continue
            records[owner_key]["ack"] = ack
            scan.save_state(state)
            accepted_count += 1
        except Exception:
            continue
    try:
        client.checkpoint(checkpoint_comparison(state, now))
    except Exception:
        pass
    return {"accepted": accepted_count, "pending": len(pending_publication_intents(state))}
