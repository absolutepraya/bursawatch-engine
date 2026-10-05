#!/usr/bin/env python3
"""Plan or explicitly apply the Kelas Investasi Delivery Owner state handoff."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery import Attachment, OperationIntent, OperationReceipt
from bursawatch_discord_delivery.client import DeliveryClientError
from bursawatch_discord_delivery.handoff import (
    APPLY_ENVIRONMENT_VARIABLE,
    HandoffError,
    HandoffItem,
    HandoffSnapshot,
    apply_handoff,
    plan_handoff,
    require_apply_authorization,
)

import discord
import state as watcher_state


_ACKS_VERSION = 1


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _source_state(path: Path, media_root: Path) -> tuple[bytes, dict[str, Any]]:
    if not path.exists():
        source = watcher_state.new_state()
        encoded = _encode(source)
        return encoded, source
    try:
        encoded = path.read_bytes()
        source = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise HandoffError("Kelas Investasi source state is invalid") from None
    if not watcher_state._is_state(source, media_root):
        raise HandoffError("Kelas Investasi source state is invalid")
    return encoded, source


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _receipt_document(receipt: OperationReceipt) -> dict[str, object]:
    return {
        "id": receipt.id,
        "key": receipt.key,
        "digest": receipt.digest,
        "status": receipt.status,
        "receipt": dict(receipt.receipt) if receipt.receipt is not None else None,
    }


class KelasInvestasiHandoffAdapter:
    """Translate stored Kelas text/image cursors into ordered owner operations."""

    def __init__(
        self,
        state_path: Path,
        plan_path: Path,
        *,
        media_root: Path | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.plan_path = Path(plan_path)
        self.media_root = (media_root or discord._configured_media_root(self.state_path)).resolve()
        self.ack_path = Path(str(self.plan_path) + ".acks.json")
        self._operations: dict[str, OperationIntent] = {}

    def _acks(self) -> dict[str, dict[str, object]]:
        if not self.ack_path.exists():
            return {}
        try:
            value = json.loads(self.ack_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise HandoffError("Kelas Investasi handoff acknowledgment file is invalid") from None
        if not isinstance(value, dict) or set(value) != {"version", "acknowledgments"}:
            raise HandoffError("Kelas Investasi handoff acknowledgment file is invalid")
        acknowledgments = value.get("acknowledgments")
        if value.get("version") != _ACKS_VERSION or not isinstance(acknowledgments, dict):
            raise HandoffError("Kelas Investasi handoff acknowledgment file is invalid")
        return acknowledgments

    def _leg(
        self,
        event_key: str,
        leg: str,
        content: str,
        channel_id: str,
        *,
        completed_message_id: str | None,
        attachment: Attachment | None = None,
    ) -> HandoffItem:
        completed = completed_message_id is not None
        operation = OperationIntent(
            key=discord.operation_key(event_key, leg),
            kind="channel_message_create",
            ordering_key=f"channel:{channel_id}",
            target={"channel_id": channel_id},
            payload={"content": content, "allowed_mentions": {"parse": []}},
            attachments=() if attachment is None else (attachment,),
            reconcile_before_first_create=not completed,
            legacy_nonce=None if completed else discord.nonce(event_key, leg),
        )
        self._operations[operation.key] = operation
        receipt = (
            {"channel_id": channel_id, "message_id": completed_message_id}
            if completed_message_id is not None
            else None
        )
        return HandoffItem(
            operation,
            receipt=receipt,
            preflight=None,
        )

    def build_handoff_snapshot(self) -> HandoffSnapshot:
        backup_bytes, source = _source_state(self.state_path, self.media_root)
        outbox = source.get("outbox")
        if not isinstance(outbox, list):
            raise HandoffError("Kelas Investasi source outbox is invalid")
        acknowledgments = self._acks()
        self._operations = {}
        items: list[HandoffItem] = []
        channel_id = discord.DISCORD_CHANNEL_ID
        for event in outbox:
            if not isinstance(event, dict):
                raise HandoffError("Kelas Investasi source event is invalid")
            if not isinstance(event.get("title"), str) or not isinstance(event.get("summary"), str):
                continue
            event_key = event.get("event_key")
            if not isinstance(event_key, str):
                raise HandoffError("Kelas Investasi source event key is invalid")
            chunks = discord.render_event(event)
            from render import saved_presentation
            presentation = saved_presentation(event)
            channel_id = presentation["destination"] if presentation else discord.DISCORD_CHANNEL_ID
            text_index = event.get("text_index")
            text_ids = event.get("text_message_ids")
            media_index = event.get("next_media_index")
            if (type(text_index) is not int or not 0 <= text_index <= len(chunks)
                    or not isinstance(text_ids, list) or len(text_ids) != text_index
                    or type(media_index) is not int or not 0 <= media_index <= len(discord._media(event))):
                raise HandoffError("Kelas Investasi delivery cursor is invalid")
            for index, content in enumerate(chunks):
                completed_id = text_ids[index] if index < text_index else None
                if completed_id is not None and (not isinstance(completed_id, str) or not completed_id.isdigit()):
                    raise HandoffError("Kelas Investasi text receipt is invalid")
                items.append(
                    self._leg(
                        event_key,
                        f"text:{index}",
                        content,
                        channel_id,
                        completed_message_id=completed_id,
                    )
                )
            for index, media_item in enumerate(discord._media(event)):
                media_path = discord._media_path(media_item, self.media_root)
                try:
                    data = media_path.read_bytes()
                except OSError:
                    raise HandoffError("Kelas Investasi cached source image is unavailable") from None
                if not data:
                    raise HandoffError("Kelas Investasi cached source image is empty")
                attachment = Attachment(media_path.name, discord._mime_type(media_path), data)
                # Kelas did not persist Discord image IDs. Reconcile its old
                # nonce before creating anything so a completed image is not replayed.
                items.append(
                    self._leg(
                        event_key,
                        f"media:{index}",
                        "",
                        channel_id,
                        completed_message_id=None,
                        attachment=attachment,
                    )
                )
        for index, item in enumerate(items):
            saved = acknowledgments.get(item.operation.key)
            if saved is None:
                continue
            try:
                accepted = OperationReceipt.from_json(saved, item.operation)
            except (TypeError, ValueError):
                raise HandoffError("Kelas Investasi handoff acknowledgment does not match its operation") from None
            if accepted.key != item.operation.key or accepted.digest != item.operation.digest:
                raise HandoffError("Kelas Investasi handoff acknowledgment does not match its operation")
            items[index] = HandoffItem(
                item.operation,
                receipt=item.receipt,
                preflight=item.preflight,
                acknowledged=True,
            )
        return HandoffSnapshot(
            backup_bytes=backup_bytes,
            source_hash_bytes=backup_bytes,
            items=tuple(items),
        )

    def acknowledge(self, receipt: OperationReceipt) -> None:
        operation = self._operations.get(receipt.key)
        if operation is None or receipt.digest != operation.digest:
            raise HandoffError("Kelas Investasi handoff acknowledgment key does not match its operation")
        acknowledgments = self._acks()
        previous = acknowledgments.get(receipt.key)
        if previous is not None:
            try:
                accepted = OperationReceipt.from_json(previous, operation)
            except (TypeError, ValueError):
                raise HandoffError("Kelas Investasi handoff acknowledgment is invalid") from None
            if accepted.digest != receipt.digest:
                raise HandoffError("Kelas Investasi handoff operation digest changed")
            return
        acknowledgments[receipt.key] = _receipt_document(receipt)
        _atomic_write(
            self.ack_path,
            _encode({"version": _ACKS_VERSION, "acknowledgments": acknowledgments}),
        )


def apply_kelas_investasi_handoff(
    plan_path: Path,
    adapter: KelasInvestasiHandoffAdapter,
    client: object,
    *,
    apply: bool,
    environment: Mapping[str, str] | None = None,
):
    require_apply_authorization(apply=apply, environment=environment)
    return apply_handoff(plan_path, adapter, client)  # type: ignore[arg-type]


def _state_path_from_environment() -> Path:
    configured = os.environ.get("KELAS_INVESTASI_GTW_STATE_PATH")
    return Path(configured).expanduser() if configured else Path.home() / ".hermes" / "state" / "kelas-investasi-gtw-watch.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", type=Path, metavar="PATH", help="write a private read-only handoff plan")
    mode.add_argument("--apply", type=Path, metavar="PATH", help="apply a previously reviewed plan")
    args = parser.parse_args(argv)
    if args.plan is not None:
        try:
            plan_path = args.plan
            state_path = _state_path_from_environment()
            media_root = discord._configured_media_root(state_path)
            adapter = KelasInvestasiHandoffAdapter(state_path, plan_path, media_root=media_root)
            plan = plan_handoff(adapter, plan_path=plan_path)
        except HandoffError as error:
            print(str(error), file=sys.stderr)
            return 1
        print(json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")))
        return 0
    try:
        require_apply_authorization(apply=True)
        state_path = _state_path_from_environment()
        adapter = KelasInvestasiHandoffAdapter(state_path, args.apply)
        client = discord.delivery_client_from_environment(include_admin=True)
        result = apply_handoff(args.apply, adapter, client)
    except (HandoffError, DeliveryClientError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps({
        "acknowledged_count": result.acknowledged_count,
        "skipped_count": result.skipped_count,
        "backup_created": result.backup_path.is_file(),
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
