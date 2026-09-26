#!/usr/bin/env python3
"""Plan or explicitly apply a WhatsApp Channel Watch delivery handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Mapping

_ROOT = Path(__file__).resolve().parents[2]
for _package in ("lib-bursawatch-discord-delivery", "lib-bursawatch-control"):
    _path = _ROOT / _package / "bin"
    if not _path.exists():
        _path = Path.home() / ".agents" / "skills" / _package / "bin"
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from bursawatch_discord_delivery import Attachment, DeliveryClient, OperationIntent, OperationReceipt
from bursawatch_discord_delivery.client import DeliveryClientError
from bursawatch_discord_delivery.handoff import (
    HandoffError,
    HandoffItem,
    HandoffSnapshot,
    apply_handoff,
    plan_handoff,
    require_apply_authorization,
)

import archive
import config
import discord
import event_queue
import render
import scan
import state
from classification import is_technical_review
from normalize import deserialize_queue_event


_ACK_VERSION = 1
_MAX_MEDIA_BYTES = archive.MAX_ARCHIVE_MEDIA_BYTES


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
        value = state.empty_state()
        return _encode(value), value
    except OSError:
        raise HandoffError("cannot read WhatsApp Channel source state") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise HandoffError("WhatsApp Channel source state is not a regular file")
    try:
        source = path.read_bytes()
        value = json.loads(source.decode("utf-8"))
        if not isinstance(value, dict) or value.get("version") != state.STATE_VERSION:
            raise ValueError("invalid state")
        if not isinstance(value.get("profiles"), dict) or not isinstance(value.get("outbox"), list):
            raise ValueError("invalid state")
        # This validates the current watcher schema without changing its bytes.
        state.load(path)
        return source, value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise HandoffError("WhatsApp Channel source state is invalid") from None


def _terminal_legacy_delivery(record: dict[str, object]) -> bool:
    """Return whether a pre-items record is provably terminal and needs no owner work."""
    delivered_at = record.get("delivered_at")
    if record.get("agent_phase") != "delivered" or not isinstance(delivered_at, str) or not delivered_at.strip():
        return False
    if record.get("board_phase") == "pending" or record.get("board_link_phase") == "pending":
        return False
    if record.get("board_phase") == "accepted" and record.get("board_link_phase") != "patched":
        return False
    if record.get("media_delivery_status") in {"pending", "retrying"}:
        return False
    return True


class WhatsAppChannelWatchHandoffAdapter:
    """Translate saved WhatsApp text/media cursors into owner operations."""

    def __init__(
        self,
        state_path: Path,
        plan_path: Path,
        *,
        archive_root: Path | None = None,
        profiles: Mapping[str, object] | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.plan_path = Path(plan_path)
        self.ack_path = Path(str(self.plan_path) + ".acks.json")
        self.archive_root = Path(archive_root or os.environ.get(
            "WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT",
            str(Path.home() / ".hermes/state/whatsapp-channel-watch/archive"),
        ))
        if profiles is None:
            loaded = config.load_for_run()
            profiles = {profile.id: profile for profile in loaded.config.profiles}
        self.profiles = dict(profiles)
        self._operations: dict[str, OperationIntent] = {}
        self.skipped_terminal_legacy_count = 0

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
            raise HandoffError("WhatsApp Channel handoff acknowledgment file is invalid") from None

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
            raise HandoffError("cannot persist WhatsApp Channel handoff acknowledgment") from None

    def _archive_media(self, event) -> dict[int, tuple[str, str | None, Attachment]]:
        try:
            records = archive.query(self.archive_root, event_key=event.event_key)
        except (OSError, ValueError):
            raise HandoffError("WhatsApp Channel archive record is invalid") from None
        if len(records) != 1:
            return {}
        raw_media = records[0].data.get("media")
        if type(raw_media) is not list:
            raise HandoffError("WhatsApp Channel archive media is invalid")
        result: dict[int, tuple[str, str | None, Attachment]] = {}
        for item in raw_media:
            if type(item) is not dict or item.get("capture_status") != "captured":
                continue
            index, kind = item.get("index"), item.get("kind")
            mime, relative = item.get("mime"), item.get("archive_path")
            digest = item.get("sha256")
            if type(index) is not int or not isinstance(kind, str) or not isinstance(relative, str):
                raise HandoffError("WhatsApp Channel archived media metadata is invalid")
            if mime is not None and not isinstance(mime, str):
                raise HandoffError("WhatsApp Channel archived media MIME type is invalid")
            safe_relative = PurePosixPath(relative)
            if safe_relative.is_absolute() or ".." in safe_relative.parts or not safe_relative.parts:
                raise HandoffError("WhatsApp Channel archived media path is invalid")
            path = self.archive_root.joinpath(*safe_relative.parts)
            try:
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_size < 1 or metadata.st_size > _MAX_MEDIA_BYTES:
                    raise ValueError("invalid archive file")
                if not path.resolve(strict=True).is_relative_to(self.archive_root.resolve(strict=True)):
                    raise ValueError("archive path escaped its root")
                content = path.read_bytes()
            except (OSError, ValueError):
                raise HandoffError("WhatsApp Channel archived media is unavailable") from None
            if not isinstance(digest, str) or hashlib.sha256(content).hexdigest() != digest:
                raise HandoffError("WhatsApp Channel archived media checksum is invalid")
            if type(item.get("bytes")) is not int or item["bytes"] != len(content):
                raise HandoffError("WhatsApp Channel archived media size is invalid")
            mime_value = mime or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            filename = discord.media_filename(kind, mime, index)
            result[index] = (kind, mime, Attachment(filename, mime_value, content))
        return result

    @staticmethod
    def _operation(nonce_value: str, channel_id: str, content: str, attachment: Attachment | None = None, *, pending: bool) -> OperationIntent:
        operation = OperationIntent(
            key=discord.operation_key_for_nonce(nonce_value),
            kind="channel_message_create",
            ordering_key=f"channel:{channel_id}",
            target={"channel_id": channel_id},
            payload={"content": content, "allowed_mentions": {"parse": []}},
            attachments=() if attachment is None else (attachment,),
        )
        if pending:
            operation = replace(operation, reconcile_before_first_create=True, legacy_nonce=nonce_value)
        return operation

    def _append(
        self, items: list[HandoffItem], operation: OperationIntent, message_id: str | None,
    ) -> None:
        receipt = None
        if message_id is not None:
            if not isinstance(message_id, str) or not message_id.isdigit():
                raise HandoffError("WhatsApp Channel saved Discord receipt is invalid")
            receipt = {"channel_id": str(operation.target["channel_id"]), "message_id": message_id}
        elif not operation.reconcile_before_first_create:
            nonce_value = operation.key.rsplit(":", 1)[-1]
            operation = replace(
                operation,
                reconcile_before_first_create=True,
                legacy_nonce=nonce_value,
            )
        items.append(HandoffItem(operation, receipt=receipt))
        self._operations[operation.key] = operation

    def build_handoff_snapshot(self) -> HandoffSnapshot:
        backup, value = _source_state(self.state_path)
        items: list[HandoffItem] = []
        self._operations = {}
        self.skipped_terminal_legacy_count = 0
        for record in value["outbox"]:
            if not isinstance(record, dict):
                continue
            phase = record.get("agent_phase")
            if phase not in {"ready", "delivered"}:
                continue
            if phase == "delivered" and "items" not in record:
                if _terminal_legacy_delivery(record):
                    self.skipped_terminal_legacy_count += 1
                    continue
                raise HandoffError("WhatsApp Channel legacy delivery has unresolved work")
            try:
                profile = self.profiles[str(record["profile_id"])]
                event = deserialize_queue_event(record["event"])
                raw_items = record["items"]
                if type(raw_items) is not list or not raw_items:
                    raise ValueError("missing ready items")
            except (KeyError, TypeError, ValueError):
                raise HandoffError("WhatsApp Channel outbox cannot be reconstructed") from None
            event_key = str(record.get("event_key", ""))
            if not event_key or event_key != event.event_key:
                raise HandoffError("WhatsApp Channel outbox event identity is invalid")

            messages_by_item: list[tuple[str, list[str]]] = []
            for item in raw_items:
                if type(item) is not dict:
                    raise HandoffError("WhatsApp Channel ready item is invalid")
                try:
                    channel_id = scan._delivery_channel(profile, item)
                    sentiment = item.get("sentiment") if isinstance(item.get("sentiment"), str) else None
                    if profile.id == scan.BRI_PROFILE_ID and is_technical_review(event.text) and sentiment is None:
                        sentiment = scan._legacy_sentiment(event)
                    messages = render.render_post(
                        profile,
                        event,
                        title=item.get("title") if profile.enable_llm_title else None,
                        summary=item.get("summary") if profile.enable_llm_summary else None,
                        route=item.get("route") if isinstance(item.get("route"), str) else None,
                        sentiment=sentiment,
                        # Board URL patch is a separate edit after initial message creation.
                        board_url=None,
                    )
                except (KeyError, TypeError, ValueError):
                    raise HandoffError("WhatsApp Channel rendered message is invalid") from None
                messages_by_item.append((channel_id, messages))

            item_cursor = record.get("item_index", 0)
            text_cursor = record.get("text_index", 0)
            text_ids = record.get("text_message_ids")
            if not isinstance(text_ids, list):
                text_ids = scan._message_ids(record)
            if (type(item_cursor) is not int or not 0 <= item_cursor <= len(messages_by_item)
                    or type(text_cursor) is not int or text_cursor < 0
                    or any(not isinstance(value, str) or not value.isdigit() for value in text_ids)):
                raise HandoffError("WhatsApp Channel text delivery cursor is invalid")
            text_operations: list[tuple[OperationIntent, bool]] = []
            completed_text_count = 0
            for current_item, (channel_id, messages) in enumerate(messages_by_item):
                if record.get("agent_phase") == "delivered" or current_item < item_cursor:
                    completed = len(messages)
                elif current_item == item_cursor:
                    completed = min(text_cursor, len(messages))
                else:
                    completed = 0
                completed_text_count += completed
                for message_index, content in enumerate(messages):
                    nonce_value = discord.nonce(event_key, f"item:{current_item}:text:{message_index}")
                    pending = message_index >= completed
                    operation = self._operation(nonce_value, channel_id, content, pending=pending)
                    text_operations.append((operation, not pending))
            if item_cursor < len(messages_by_item) and text_cursor > len(messages_by_item[item_cursor]):
                raise HandoffError("WhatsApp Channel text cursor exceeds rendered messages")
            if item_cursor == len(messages_by_item) and text_cursor != 0:
                raise HandoffError("WhatsApp Channel text cursor exceeds rendered messages")
            if len(text_ids) > completed_text_count:
                raise HandoffError("WhatsApp Channel has more text receipts than its cursor")
            for ordinal, (operation, complete) in enumerate(text_operations):
                known_id = text_ids[ordinal] if complete and ordinal < len(text_ids) else None
                self._append(items, operation if known_id is None else replace(operation, reconcile_before_first_create=False, legacy_nonce=None), known_id)

            media_index = record.get("media_index", 0)
            skipped_value = record.get("media_skipped_indexes", [])
            media_ids = record.get("media_message_ids", [])
            if (type(media_index) is not int or media_index < 0 or type(skipped_value) is not list
                    or any(type(index) is not int for index in skipped_value)
                    or type(media_ids) is not list
                    or any(not isinstance(value, str) or not value.isdigit() for value in media_ids)):
                raise HandoffError("WhatsApp Channel media delivery cursor is invalid")
            technical_review = profile.id == scan.BRI_PROFILE_ID and is_technical_review(event.text)
            archived = self._archive_media(event)
            if technical_review:
                image_indexes = [index for index, (kind, _mime, _attachment) in archived.items() if kind == "image"]
                if len(image_indexes) != 1:
                    if text_cursor or item_cursor:
                        raise HandoffError("WhatsApp Channel TechnicalReview image does not match delivered text")
                    continue
                media_indexes = tuple(image_indexes)
            elif profile.forward_media:
                media_indexes = scan.agent_protocol.media_delivery_indexes(
                    item_count=len(raw_items), media_count=len(event.media)
                )
            else:
                media_indexes = ()
            skipped = set(skipped_value)
            eligible_indexes = [index for index in media_indexes if index not in skipped and index in archived]
            if record.get("agent_phase") == "delivered":
                completed_media = len(eligible_indexes)
            else:
                completed_media = sum(
                    1 for position, source_index in enumerate(media_indexes)
                    if position < media_index and source_index not in skipped and source_index in archived
                )
            if len(media_ids) > completed_media:
                raise HandoffError("WhatsApp Channel has more media receipts than its cursor")
            target = messages_by_item[0][0]
            for ordinal, source_index in enumerate(eligible_indexes):
                _kind, _mime, attachment = archived[source_index]
                nonce_value = discord.nonce(event_key, f"media:{source_index}")
                complete = ordinal < completed_media
                operation = self._operation(nonce_value, target, "", attachment, pending=not complete)
                known_id = media_ids[ordinal] if complete and ordinal < len(media_ids) else None
                self._append(items, operation if known_id is None else replace(operation, reconcile_before_first_create=False, legacy_nonce=None), known_id)

        acknowledgments = self._acks()
        for index, item in enumerate(items):
            stored = acknowledgments.get(item.operation.key)
            if stored is None:
                continue
            try:
                accepted = OperationReceipt.from_json(stored, item.operation)
            except (TypeError, ValueError):
                raise HandoffError("WhatsApp Channel handoff acknowledgment does not match its operation") from None
            del accepted
            items[index] = HandoffItem(item.operation, receipt=item.receipt, acknowledged=True)
        return HandoffSnapshot(backup, backup, tuple(items))

    def acknowledge(self, receipt: OperationReceipt) -> None:
        operation = self._operations.get(receipt.key)
        if operation is None or operation.digest != receipt.digest:
            raise HandoffError("WhatsApp Channel handoff acknowledgment does not match its operation")
        acknowledgments = self._acks()
        previous = acknowledgments.get(receipt.key)
        if previous is not None:
            try:
                stored = OperationReceipt.from_json(previous, operation)
            except (TypeError, ValueError):
                raise HandoffError("WhatsApp Channel handoff acknowledgment is invalid") from None
            if stored.digest != receipt.digest:
                raise HandoffError("WhatsApp Channel handoff digest changed")
            return
        acknowledgments[receipt.key] = _receipt_document(receipt)
        self._persist_acks(acknowledgments)


def _state_path() -> Path:
    return Path(os.environ.get(
        "WHATSAPP_CHANNEL_WATCH_STATE_PATH",
        str(Path.home() / ".hermes/state/whatsapp-channel-watch/state.json"),
    )).expanduser()


def _delivery_client(*, include_admin: bool) -> DeliveryClient:
    url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", "http://127.0.0.1:9140")
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
        adapter = WhatsAppChannelWatchHandoffAdapter(_state_path(), args.plan or args.apply)
        if args.plan is not None:
            plan = plan_handoff(adapter, plan_path=args.plan)
            summary = plan.as_dict()
            summary["skipped_terminal_legacy_count"] = adapter.skipped_terminal_legacy_count
            print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
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
