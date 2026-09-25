#!/usr/bin/env python3
"""Plan or explicitly apply the Instagram watcher Delivery Owner handoff."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Mapping

_ROOT = Path(__file__).resolve().parents[2]
_DELIVERY_BIN = _ROOT / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents/skills/lib-bursawatch-discord-delivery/bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery import Attachment, DeliveryClient, OperationIntent, OperationReceipt
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

import config
import discord
import render
import scan
import state


_ACK_VERSION = 1


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _state_source(path: Path) -> tuple[bytes, dict]:
    if not path.exists():
        value = state.new_state()
        encoded = _encode(value)
        return encoded, value
    try:
        encoded = path.read_bytes()
        value = state.load_state(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise HandoffError("cannot read Instagram watcher source state") from None
    if not isinstance(value, dict):
        raise HandoffError("Instagram watcher source state is invalid")
    return encoded, value


def _receipt(receipt: OperationReceipt) -> dict[str, object]:
    return {
        "id": receipt.id,
        "key": receipt.key,
        "digest": receipt.digest,
        "status": receipt.status,
        "receipt": dict(receipt.receipt) if receipt.receipt is not None else None,
    }


class InstagramAccountWatchHandoffAdapter:
    """Translate archived Instagram outbox cursors into owner operations."""

    def __init__(
        self,
        state_path: Path,
        plan_path: Path,
        profiles: Mapping[str, object] | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.plan_path = Path(plan_path)
        self.ack_path = Path(str(self.plan_path) + ".acks.json")
        self.profiles = dict(profiles) if profiles is not None else {
            profile.id: profile for profile in config.load_watch_config_for_run().config.profiles
        }
        self._operations: dict[str, OperationIntent] = {}

    def _acks(self) -> dict[str, object]:
        if not self.ack_path.exists():
            return {}
        try:
            value = json.loads(self.ack_path.read_text(encoding="utf-8"))
            if set(value) != {"version", "acknowledgments"} or value["version"] != _ACK_VERSION:
                raise ValueError("invalid acknowledgment file")
            acknowledgments = value["acknowledgments"]
            if not isinstance(acknowledgments, dict):
                raise ValueError("invalid acknowledgment file")
            return acknowledgments
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise HandoffError("Instagram watcher handoff acknowledgment file is invalid") from None

    def _persist_acks(self, values: dict[str, object]) -> None:
        self.ack_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
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
            raise HandoffError("cannot persist Instagram watcher handoff acknowledgment") from None

    @staticmethod
    def _operation(
        event_key: str,
        leg: str,
        nonce_value: str,
        channel_id: str,
        content: str,
        attachment: Attachment | None,
        *,
        unknown_outcome: bool,
    ) -> OperationIntent:
        operation = OperationIntent(
            key=discord.operation_key_for_nonce(nonce_value),
            kind="channel_message_create",
            ordering_key=f"channel:{channel_id}",
            target={"channel_id": channel_id},
            payload={"content": content, "allowed_mentions": {"parse": []}},
            attachments=() if attachment is None else (attachment,),
        )
        if unknown_outcome:
            from dataclasses import replace

            operation = replace(
                operation,
                reconcile_before_first_create=True,
                legacy_nonce=nonce_value,
            )
        return operation

    def build_handoff_snapshot(self) -> HandoffSnapshot:
        backup, value = _state_source(self.state_path)
        items: list[HandoffItem] = []
        self._operations = {}

        for event in value.get("outbox", []):
            if not isinstance(event, dict):
                raise HandoffError("Instagram watcher outbox entry is invalid")
            try:
                profile = self.profiles[event["profile_id"]]
                post = state.deserialize_post(event["post"])
                channel_id = scan._target_channel(profile, event)
                messages = render.render_publication(
                    profile,
                    post,
                    event.get("summary") if profile.enable_llm_summary else None,
                    event.get("title") if profile.enable_llm_title else None,
                )
                downloaded_raw = event.get("downloaded_publication")
                if downloaded_raw is None and post.media:
                    raise ValueError("archived media is unavailable")
                downloaded = (
                    state.deserialize_downloaded_publication(downloaded_raw)
                    if downloaded_raw is not None
                    else None
                )
                assets = scan._delivery_media(post, downloaded) if downloaded is not None else ()
            except (KeyError, TypeError, ValueError, OSError):
                raise HandoffError("Instagram watcher outbox payload cannot be reconstructed") from None

            text_cursor = event.get("text_index")
            text_ids = event.get("text_message_ids", [])
            media_cursor = event.get("media_index")
            media_ids = event.get("media_message_ids", [])
            if (
                type(text_cursor) is not int
                or not isinstance(text_ids, list)
                or text_cursor != len(text_ids)
                or type(media_cursor) is not int
                or not isinstance(media_ids, list)
                or media_cursor != len(media_ids)
            ):
                raise HandoffError("Instagram watcher delivery cursors do not match saved receipts")

            event_key = event["event_key"]
            for index, content in enumerate(messages):
                nonce_value = discord.nonce(event_key, f"text:{index}")
                operation = self._operation(
                    event_key,
                    f"text:{index}",
                    nonce_value,
                    channel_id,
                    content,
                    None,
                    unknown_outcome=index >= text_cursor,
                )
                known_id = text_ids[index] if index < text_cursor else None
                receipt = {"channel_id": channel_id, "message_id": known_id} if known_id is not None else None
                self._append(items, operation, receipt)

            if profile.forward_media:
                if media_cursor > len(assets):
                    raise HandoffError("Instagram watcher media cursor exceeds archived source media")
                for index, asset in enumerate(assets):
                    nonce_value = discord.nonce(event_key, f"media:{index}")
                    attachment = discord.read_media_attachment(asset.path)
                    operation = self._operation(
                        event_key,
                        f"media:{index}",
                        nonce_value,
                        channel_id,
                        "",
                        attachment,
                        unknown_outcome=index >= media_cursor,
                    )
                    known_id = media_ids[index] if index < media_cursor else None
                    receipt = {"channel_id": channel_id, "message_id": known_id} if known_id is not None else None
                    self._append(items, operation, receipt)
                if media_cursor != len(media_ids) or media_cursor > len(assets):
                    raise HandoffError("Instagram watcher media receipt count is inconsistent")
            elif media_cursor or media_ids:
                raise HandoffError("Instagram watcher has media receipts while media forwarding is disabled")

        acknowledgments = self._acks()
        items = [self._with_ack(item, acknowledgments) for item in items]
        return HandoffSnapshot(backup, backup, tuple(items))

    def _append(
        self,
        items: list[HandoffItem],
        operation: OperationIntent,
        receipt: dict[str, str] | None,
    ) -> None:
        item = HandoffItem(operation, receipt=receipt)
        items.append(item)
        self._operations[operation.key] = operation

    @staticmethod
    def _with_ack(item: HandoffItem, acknowledgments: dict[str, object]) -> HandoffItem:
        saved = acknowledgments.get(item.operation.key)
        if saved is None:
            return item
        try:
            receipt = OperationReceipt.from_json(saved, item.operation)
        except (TypeError, ValueError):
            raise HandoffError("Instagram watcher handoff acknowledgment does not match its operation") from None
        del receipt
        return HandoffItem(item.operation, receipt=item.receipt, acknowledged=True)

    def acknowledge(self, receipt: OperationReceipt) -> None:
        operation = self._operations.get(receipt.key)
        if operation is None or operation.digest != receipt.digest:
            raise HandoffError("Instagram watcher handoff acknowledgment does not match its operation")
        acknowledgments = self._acks()
        previous = acknowledgments.get(receipt.key)
        if previous is not None:
            try:
                stored = OperationReceipt.from_json(previous, operation)
            except (TypeError, ValueError):
                raise HandoffError("Instagram watcher handoff acknowledgment is invalid") from None
            if stored.digest != receipt.digest:
                raise HandoffError("Instagram watcher handoff digest changed")
            return
        acknowledgments[receipt.key] = _receipt(receipt)
        self._persist_acks(acknowledgments)


def apply_instagram_handoff(plan_path: Path, adapter: InstagramAccountWatchHandoffAdapter, client: object, *, apply: bool, environment=None):
    require_apply_authorization(apply=apply, environment=environment)
    return apply_handoff(plan_path, adapter, client)  # type: ignore[arg-type]


def _client(*, include_admin: bool) -> DeliveryClient:
    url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", "http://127.0.0.1:9140")
    token = Path(
        os.environ.get(
            "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
            str(Path.home() / ".hermes/secrets/bursawatch-discord-delivery-client-token"),
        )
    ).expanduser()
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
        adapter = InstagramAccountWatchHandoffAdapter(scan.state_path(), args.plan or args.apply)
        if args.plan is not None:
            plan = plan_handoff(adapter, plan_path=args.plan)
            print(json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")))
            return 0
        require_apply_authorization(apply=True)
        result = apply_handoff(args.apply, adapter, _client(include_admin=True))
        print(json.dumps({"acknowledged_count": result.acknowledged_count, "skipped_count": result.skipped_count}, sort_keys=True, separators=(",", ":")))
        return 0
    except (DeliveryClientError, HandoffError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
