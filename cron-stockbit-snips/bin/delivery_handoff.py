#!/usr/bin/env python3
"""Plan or explicitly apply a Stockbit Snips Delivery Owner handoff."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path
from typing import Mapping

_ROOT = Path(__file__).resolve().parents[2]
_DELIVERY_BIN = _ROOT / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents/skills/lib-bursawatch-discord-delivery/bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery import DeliveryClient, OperationIntent, OperationReceipt
from bursawatch_discord_delivery.client import DeliveryClientError
from bursawatch_discord_delivery.handoff import (
    HandoffError,
    HandoffItem,
    HandoffSnapshot,
    apply_handoff,
    plan_handoff,
    require_apply_authorization,
)

import config
import discord


_ACK_VERSION = 1


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _receipt_document(receipt: OperationReceipt) -> dict[str, object]:
    return {
        "id": receipt.id,
        "key": receipt.key,
        "digest": receipt.digest,
        "status": receipt.status,
        "receipt": dict(receipt.receipt) if receipt.receipt is not None else None,
    }


def _source_state(path: Path) -> tuple[bytes, dict[str, object]]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return _encode({"version": 2, "articles": {}}), {"version": 2, "articles": {}}
    except OSError:
        raise HandoffError("cannot read Stockbit Snips source state") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise HandoffError("Stockbit Snips source state is not a regular file")
    try:
        source = path.read_bytes()
        value = json.loads(source.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise HandoffError("Stockbit Snips source state is invalid") from None
    if (not isinstance(value, dict) or type(value.get("version")) is not int
            or value["version"] not in {1, 2} or not isinstance(value.get("articles"), dict)):
        raise HandoffError("Stockbit Snips source state is invalid")
    return source, value


class StockbitSnipsHandoffAdapter:
    """Translate frozen Stockbit delivery records without loading mutable config."""

    def __init__(self, state_path: Path, plan_path: Path) -> None:
        self.state_path = Path(state_path)
        self.plan_path = Path(plan_path)
        self.ack_path = Path(str(self.plan_path) + ".acks.json")
        self._operations: dict[str, OperationIntent] = {}

    def _acks(self) -> dict[str, object]:
        if not self.ack_path.exists():
            return {}
        try:
            value = json.loads(self.ack_path.read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or set(value) != {"version", "acknowledgments"}
                    or value["version"] != _ACK_VERSION
                    or not isinstance(value["acknowledgments"], dict)):
                raise ValueError("invalid acknowledgment file")
            return value["acknowledgments"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise HandoffError("Stockbit Snips handoff acknowledgment file is invalid") from None

    def _persist_acks(self, values: dict[str, object]) -> None:
        self.ack_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.ack_path.parent, 0o700)
        temporary = self.ack_path.with_name(f".{self.ack_path.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as target:
                target.write(_encode({"version": _ACK_VERSION, "acknowledgments": values}))
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.ack_path)
            os.chmod(self.ack_path, 0o600)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise HandoffError("cannot persist Stockbit Snips handoff acknowledgment") from None

    @staticmethod
    def _saved_receipt(record: Mapping[str, object], channel_id: str) -> str | None:
        delivery = record.get("delivery")
        if delivery is None:
            return None
        if not isinstance(delivery, dict):
            raise HandoffError("Stockbit Snips saved delivery receipt is invalid")
        message_id = delivery.get("message_id")
        saved_channel = delivery.get("channel_id")
        if (not isinstance(message_id, str) or not message_id.isdigit()
                or saved_channel != channel_id):
            raise HandoffError("Stockbit Snips saved delivery receipt does not match its frozen route")
        return message_id

    def build_handoff_snapshot(self) -> HandoffSnapshot:
        backup, value = _source_state(self.state_path)
        items: list[HandoffItem] = []
        self._operations = {}
        articles = value["articles"]
        for key, record in articles.items():
            if not isinstance(key, str) or not isinstance(record, dict):
                raise HandoffError("Stockbit Snips article state is invalid")
            phase = record.get("phase")
            if phase not in {"pending_delivery", "delivered"}:
                continue
            snapshot = record.get("config_snapshot")
            if (not isinstance(snapshot, dict)
                    or type(snapshot.get("revision")) is not int
                    or type(snapshot.get("id_stocks_news_channel_id")) is not str
                    or type(snapshot.get("macro_news_channel_id")) is not str):
                raise HandoffError("Stockbit article has no frozen live configuration")
            if any(not channel.isascii() or not channel.isdecimal() or not 17 <= len(channel) <= 20
                   for channel in (snapshot["id_stocks_news_channel_id"], snapshot["macro_news_channel_id"])):
                raise HandoffError("Stockbit article frozen destination is invalid")
            if snapshot["id_stocks_news_channel_id"] == snapshot["macro_news_channel_id"]:
                raise HandoffError("Stockbit article frozen destinations are invalid")
            analysis = record.get("analysis")
            if not isinstance(analysis, dict):
                raise HandoffError("Stockbit article has no saved analysis")
            route = analysis.get("route")
            if route == "id_stocks_news":
                channel_id = snapshot["id_stocks_news_channel_id"]
            elif route == "macro_news":
                channel_id = snapshot["macro_news_channel_id"]
            else:
                raise HandoffError("Stockbit pending article has no deliverable route")
            content = record.get("rendered")
            if not isinstance(content, str) or not content:
                raise HandoffError("Stockbit article has no saved rendered message")
            try:
                operation, nonce_value = discord._operation(content, channel_id, key, "news")
            except (TypeError, ValueError):
                raise HandoffError("Stockbit article delivery identity is invalid") from None
            message_id = self._saved_receipt(record, channel_id) if phase == "delivered" else None
            if message_id is None:
                operation = replace(operation, reconcile_before_first_create=True, legacy_nonce=nonce_value)
            else:
                operation = replace(operation, reconcile_before_first_create=False, legacy_nonce=None)
            receipt = {"channel_id": channel_id, "message_id": message_id} if message_id else None
            items.append(HandoffItem(operation, receipt=receipt))
            self._operations[operation.key] = operation

        acknowledgments = self._acks()
        for index, item in enumerate(items):
            stored = acknowledgments.get(item.operation.key)
            if stored is None:
                continue
            try:
                OperationReceipt.from_json(stored, item.operation)
            except (TypeError, ValueError):
                raise HandoffError("Stockbit Snips handoff acknowledgment does not match its operation") from None
            items[index] = HandoffItem(item.operation, receipt=item.receipt, acknowledged=True)
        return HandoffSnapshot(backup, backup, tuple(items))

    def acknowledge(self, receipt: OperationReceipt) -> None:
        operation = self._operations.get(receipt.key)
        if operation is None or operation.digest != receipt.digest:
            raise HandoffError("Stockbit Snips handoff acknowledgment does not match its operation")
        acknowledgments = self._acks()
        previous = acknowledgments.get(receipt.key)
        if previous is not None:
            try:
                stored = OperationReceipt.from_json(previous, operation)
            except (TypeError, ValueError):
                raise HandoffError("Stockbit Snips handoff acknowledgment is invalid") from None
            if stored.digest != receipt.digest:
                raise HandoffError("Stockbit Snips handoff digest changed")
            return
        acknowledgments[receipt.key] = _receipt_document(receipt)
        self._persist_acks(acknowledgments)


def _state_path() -> Path:
    return Path(os.environ.get(
        "STOCKBIT_SNIPS_STATE_PATH",
        str(Path.home() / ".hermes/state/stockbit-snips.json"),
    )).expanduser()


def _delivery_client(*, include_admin: bool) -> DeliveryClient:
    url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", "http://127.0.0.1:9120")
    token = Path(os.environ.get(
        "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
        str(Path.home() / ".hermes/secrets/bursawatch-discord-delivery-client-token"),
    )).expanduser()
    admin = None
    if include_admin:
        configured = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE")
        if not configured:
            raise DeliveryClientError("admin_credentials_required")
        admin = Path(configured).expanduser()
    return DeliveryClient(url, token, admin_token_file=admin)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", type=Path)
    group.add_argument("--apply", type=Path)
    args = parser.parse_args(argv)
    try:
        adapter = StockbitSnipsHandoffAdapter(_state_path(), args.plan or args.apply)
        if args.plan is not None:
            plan = plan_handoff(adapter, plan_path=args.plan)
            print(json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")))
            return 0
        require_apply_authorization(apply=True)
        result = apply_handoff(args.apply, adapter, _delivery_client(include_admin=True))
        print(json.dumps({"acknowledged_count": result.acknowledged_count, "skipped_count": result.skipped_count}, sort_keys=True, separators=(",", ":")))
        return 0
    except (DeliveryClientError, HandoffError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
