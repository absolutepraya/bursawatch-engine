#!/usr/bin/env python3
"""Plan or explicitly apply the Market News Delivery Owner state handoff."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from bursawatch_discord_delivery.handoff import (
        HandoffError,
        HandoffItem,
        HandoffSnapshot,
        apply_handoff,
        plan_handoff,
        require_apply_authorization,
    )
    from bursawatch_discord_delivery.client import DeliveryClientError
    from bursawatch_discord_delivery.models import Attachment, OperationIntent, OperationReceipt
except ModuleNotFoundError:
    _repository_root = Path(__file__).resolve().parents[2]
    _shared_library = _repository_root / "lib-bursawatch-discord-delivery" / "bin"
    if _shared_library.is_dir():
        sys.path.insert(0, str(_shared_library))
    from bursawatch_discord_delivery.handoff import (
        HandoffError,
        HandoffItem,
        HandoffSnapshot,
        apply_handoff,
        plan_handoff,
        require_apply_authorization,
    )
    from bursawatch_discord_delivery.client import DeliveryClientError
    from bursawatch_discord_delivery.models import Attachment, OperationIntent, OperationReceipt

import delivery
import scan
import state as scanner_state


_HANDOFF_FIELDS = ("delivery_handoff", "image_delivery_handoff")


def _without_handoff_acknowledgments(source: Mapping[str, Any]) -> bytes:
    copied = json.loads(json.dumps(source))
    stats = copied.get("stats")
    records = stats.get("delivery_payloads") if isinstance(stats, dict) else None
    if isinstance(records, dict):
        for record in records.values():
            if isinstance(record, dict):
                for name in _HANDOFF_FIELDS:
                    record.pop(name, None)
    return json.dumps(copied, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _state_source(path: Path) -> tuple[bytes, dict[str, Any]]:
    if not path.exists():
        loaded = scanner_state.empty_state()
        encoded = json.dumps(loaded, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return encoded, loaded
    try:
        encoded = path.read_bytes()
        loaded = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise HandoffError("cannot read Market News source state") from None
    try:
        scanner_state._validate_state(loaded)
    except scanner_state.StateBlockedError:
        raise HandoffError("Market News source state is invalid") from None
    return encoded, loaded


def _read_handoff_ack(record: Mapping[str, Any], leg: str, operation: OperationIntent) -> bool:
    field = "delivery_handoff" if leg == "text" else "image_delivery_handoff"
    value = record.get(field)
    if value is None:
        return False
    if not isinstance(value, dict) or set(value) != {"state", "operation_key", "receipt"}:
        raise HandoffError("Market News source has invalid handoff metadata")
    if value.get("operation_key") != operation.key:
        raise HandoffError("Market News source handoff key does not match its event")
    stored = value.get("receipt")
    if not isinstance(stored, dict):
        raise HandoffError("Market News source handoff receipt is missing")
    try:
        accepted = OperationReceipt.from_json(stored, operation)
    except (TypeError, ValueError):
        raise HandoffError("Market News source handoff receipt is invalid") from None
    return value.get("state") == "accepted" and accepted.key == operation.key


class MarketNewsHandoffAdapter:
    """Translate the existing `stats.delivery_payloads` records into owner intents."""

    def __init__(self, state_path: Path, plan_path: Path) -> None:
        self.state_path = Path(state_path)
        self.plan_path = Path(plan_path)
        self._source_by_key: dict[str, tuple[str, str]] = {}

    def _channel_id(self, item: object, record: Mapping[str, Any]) -> str:
        stored = record.get("channel_id")
        if isinstance(stored, str) and stored:
            return stored
        # Legacy v1 payloads did not persist their selected channel. Their
        # source route maps through the checked-in package defaults.
        return scan._delivery_channel(item)

    def _intent(
        self,
        candidate_key: str,
        leg: str,
        channel_id: str,
        content: str,
        *,
        attachment: Attachment | None = None,
        completed: bool,
        legacy_nonce: str | None = None,
    ) -> OperationIntent:
        event_key = f"{candidate_key}:{leg}"
        return delivery._channel_message_operation(
            content,
            channel_id,
            event_key,
            leg=leg,
            attachments=() if attachment is None else (attachment,),
            reconcile_before_first_create=not completed,
            legacy_nonce=legacy_nonce if not completed else None,
        )

    @staticmethod
    def _preflight(record: Mapping[str, Any], leg: str) -> Mapping[str, Any] | None:
        specific = record.get(f"{leg}_preflight")
        if specific is not None:
            return specific
        shared = record.get("preflight")
        return shared if leg == "text" else None

    def build_handoff_snapshot(self) -> HandoffSnapshot:
        backup_bytes, source = _state_source(self.state_path)
        stats = source.get("stats")
        payloads = stats.get("delivery_payloads", {}) if isinstance(stats, dict) else None
        candidates = source.get("candidates")
        if not isinstance(payloads, dict) or not isinstance(candidates, dict):
            raise HandoffError("Market News source state has no delivery payload map")

        items: list[HandoffItem] = []
        self._source_by_key = {}
        for candidate_key, payload in payloads.items():
            if not isinstance(candidate_key, str) or not isinstance(payload, dict):
                raise HandoffError("Market News delivery payload record is invalid")
            candidate_record = candidates.get(candidate_key)
            item = scan._selection_item_from_record(candidate_key, candidate_record)
            if item is None:
                raise HandoffError("Market News delivery payload has no classified source item")
            channel_id = self._channel_id(item, payload)
            text_id = payload.get("text_discord_id")
            if text_id is not None and (not isinstance(text_id, str) or not text_id.isdigit()):
                raise HandoffError("Market News text receipt is invalid")
            content = payload.get("content")
            if not isinstance(content, str) or not content:
                raise HandoffError("Market News saved text payload is missing")
            text_operation = self._intent(
                candidate_key,
                "text",
                channel_id,
                content,
                completed=text_id is not None,
                legacy_nonce=payload.get("nonce") if isinstance(payload.get("nonce"), str) else None,
            )
            text_receipt = {"channel_id": channel_id, "message_id": text_id} if text_id is not None else None
            text_preflight = None if text_receipt is not None else self._preflight(payload, "text")
            items.append(
                HandoffItem(
                    text_operation,
                    receipt=text_receipt,
                    preflight=text_preflight,
                    acknowledged=_read_handoff_ack(payload, "text", text_operation),
                )
            )
            self._source_by_key[text_operation.key] = (candidate_key, "text")

            image_id = payload.get("image_discord_id")
            if image_id is None:
                continue
            if not isinstance(image_id, str) or not image_id.isdigit():
                raise HandoffError("Market News image receipt is invalid")
            image_path = (
                self.state_path.expanduser().resolve().parent
                / "media"
                / f"{item.provider.value}-{item.candidate.source_message_id}.jpg"
            )
            try:
                image_bytes = image_path.read_bytes()
            except OSError:
                raise HandoffError("Market News cached image is unavailable for handoff") from None
            if not image_bytes:
                raise HandoffError("Market News cached image is empty")
            import mimetypes

            mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
            image_operation = self._intent(
                candidate_key,
                "image",
                channel_id,
                "",
                attachment=Attachment(image_path.name, mime_type, image_bytes),
                completed=True,
            )
            image_receipt = {"channel_id": channel_id, "message_id": image_id}
            items.append(
                HandoffItem(
                    image_operation,
                    receipt=image_receipt,
                    acknowledged=_read_handoff_ack(payload, "image", image_operation),
                )
            )
            self._source_by_key[image_operation.key] = (candidate_key, "image")

        return HandoffSnapshot(
            backup_bytes=backup_bytes,
            source_hash_bytes=_without_handoff_acknowledgments(source),
            items=tuple(items),
        )

    def acknowledge(self, receipt: OperationReceipt) -> None:
        source = self._source_by_key.get(receipt.key)
        if source is None:
            raise HandoffError("Market News acknowledgment key is not in the source snapshot")
        candidate_key, leg = source
        raw_bytes, loaded = _state_source(self.state_path)
        del raw_bytes
        stats = loaded.get("stats")
        payloads = stats.get("delivery_payloads") if isinstance(stats, dict) else None
        payload = payloads.get(candidate_key) if isinstance(payloads, dict) else None
        if not isinstance(payload, dict):
            raise HandoffError("Market News delivery payload disappeared during handoff")
        field = "delivery_handoff" if leg == "text" else "image_delivery_handoff"
        current = payload.get(field)
        if isinstance(current, dict) and current.get("state") == "accepted":
            if current.get("operation_key") != receipt.key:
                raise HandoffError("Market News accepted operation key changed")
            try:
                previous = OperationReceipt.from_json(current.get("receipt"), None)
            except (TypeError, ValueError):
                raise HandoffError("Market News accepted receipt is invalid") from None
            if previous.digest != receipt.digest:
                raise HandoffError("Market News accepted operation digest changed")
            return
        payload[field] = {
            "state": "accepted",
            "operation_key": receipt.key,
            "receipt": delivery._receipt_document(receipt),
        }
        scanner_state.save_state(loaded, self.state_path)


def apply_market_news_handoff(
    plan_path: Path,
    adapter: MarketNewsHandoffAdapter,
    client: object,
    *,
    apply: bool,
    environment: Mapping[str, str] | None = None,
):
    require_apply_authorization(apply=apply, environment=environment)
    return apply_handoff(plan_path, adapter, client)  # type: ignore[arg-type]


def _state_path_from_environment() -> Path:
    configured = os.environ.get("IDX_MARKET_NEWS_STATE_PATH")
    return Path(configured).expanduser() if configured else Path(__file__).resolve().parents[1] / "state.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", type=Path, metavar="PATH", help="write a private read-only handoff plan")
    mode.add_argument("--apply", type=Path, metavar="PATH", help="apply a previously reviewed plan")
    args = parser.parse_args(argv)
    if args.plan is not None:
        try:
            plan = plan_handoff(
                MarketNewsHandoffAdapter(_state_path_from_environment(), args.plan),
                plan_path=args.plan,
            )
        except HandoffError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")))
        return 0
    try:
        require_apply_authorization(apply=True)
        adapter = MarketNewsHandoffAdapter(_state_path_from_environment(), args.apply)
        result = apply_handoff(args.apply, adapter, delivery.delivery_client_from_environment(include_admin=True))
    except (HandoffError, DeliveryClientError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "acknowledged_count": result.acknowledged_count,
                "skipped_count": result.skipped_count,
                "backup_created": result.backup_path.is_file(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
