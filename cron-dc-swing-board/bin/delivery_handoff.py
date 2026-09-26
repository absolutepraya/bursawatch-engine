#!/usr/bin/env python3
"""Plan or explicitly apply the Swing Board Delivery Owner state handoff."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

_DELIVERY_BIN = Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"
if not _DELIVERY_BIN.exists():
    _DELIVERY_BIN = Path.home() / ".agents" / "skills" / "lib-bursawatch-discord-delivery" / "bin"
if str(_DELIVERY_BIN) not in sys.path:
    sys.path.insert(0, str(_DELIVERY_BIN))

from bursawatch_discord_delivery import Attachment, DeliveryClient, DiscordQuery, OperationIntent, OperationReceipt
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

from discord_forum import DiscordForumClient, FORUM_CHANNEL_ID, operation_key, stable_nonce
from store import episode_sources_from_connection
from tags import LEGACY_SOURCE_PLAN, desired_lifecycle_tag

_ACK_VERSION = 1
_MAX_MEDIA_BYTES = 8 * 1024 * 1024


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _readonly_snapshot(path: Path) -> tuple[bytes, sqlite3.Connection]:
    try:
        metadata = path.lstat()
    except OSError:
        raise HandoffError("Swing Board source database is unavailable") from None
    if not stat.S_ISREG(metadata.st_mode):
        raise HandoffError("Swing Board source database is unavailable")
    lock_path = Path(f"{path}.lock")
    try:
        lock_metadata = lock_path.lstat()
        if not stat.S_ISREG(lock_metadata.st_mode):
            raise ValueError("invalid Board lock file")
        lock = lock_path.open("rb")
    except (OSError, ValueError):
        raise HandoffError("cannot coordinate a read-only Board snapshot") from None
    source = None
    snapshot = sqlite3.connect(":memory:")
    temporary_directory = None
    try:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        temporary_directory = tempfile.TemporaryDirectory(prefix="swing-board-handoff-")
        copied_path = Path(temporary_directory.name) / path.name
        shutil.copyfile(path, copied_path)
        wal_path = Path(f"{path}-wal")
        if wal_path.exists():
            shutil.copyfile(wal_path, Path(f"{copied_path}-wal"))
        source = sqlite3.connect(f"{copied_path.as_uri()}?mode=ro", uri=True)
        source.execute("PRAGMA query_only=ON")
        source.backup(snapshot)
        snapshot.row_factory = sqlite3.Row
        check = snapshot.execute("PRAGMA quick_check").fetchone()
        if check is None or check[0] != "ok":
            raise HandoffError("Swing Board source database failed integrity check")
        return snapshot.serialize(), snapshot
    except HandoffError:
        snapshot.close()
        raise
    except (OSError, sqlite3.Error, ValueError):
        snapshot.close()
        raise HandoffError("cannot read Swing Board source database") from None
    finally:
        if source is not None:
            source.close()
        if temporary_directory is not None:
            temporary_directory.cleanup()
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def _receipt_document(receipt: OperationReceipt) -> dict[str, object]:
    return {
        "id": receipt.id,
        "key": receipt.key,
        "digest": receipt.digest,
        "status": receipt.status,
        "receipt": dict(receipt.receipt) if receipt.receipt is not None else None,
    }


def _cached_media(media_root: Path, dedupe_key: str, media_url: object) -> Path | None:
    if not isinstance(media_url, str) or not media_url:
        return None
    cache_key = hashlib.sha256(f"{dedupe_key}\n{media_url}".encode("utf-8")).hexdigest()
    candidates = list(media_root.glob(f"{cache_key}.*")) if media_root.is_dir() else []
    if len(candidates) > 1:
        raise HandoffError("Swing Board cached media identity is ambiguous")
    return candidates[0] if candidates else None


def _attachment(path: Path | None) -> Attachment | None:
    if path is None:
        return None
    try:
        metadata = path.lstat()
        if not path.is_file() or path.is_symlink() or metadata.st_size < 1 or metadata.st_size > _MAX_MEDIA_BYTES:
            raise ValueError("media is not a valid regular file")
        data = path.read_bytes()
    except (OSError, ValueError):
        raise HandoffError("Swing Board persisted media is unavailable") from None
    return Attachment(path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream", data)


class SwingBoardHandoffAdapter:
    """Read Board SQLite state and acknowledge only through a private sidecar."""

    def __init__(
        self,
        state_path: Path,
        plan_path: Path,
        *,
        media_root: Path,
        delivery_client: object,
    ) -> None:
        self.state_path = Path(state_path)
        self.plan_path = Path(plan_path)
        self.ack_path = Path(str(self.plan_path) + ".acks.json")
        self.media_root = Path(media_root)
        self.delivery_client = delivery_client
        self.transport = DiscordForumClient(delivery_client=delivery_client, no_post=False)
        self._operations: dict[str, OperationIntent] = {}

    def _acks(self) -> dict[str, dict[str, object]]:
        if not self.ack_path.exists():
            return {}
        try:
            value = json.loads(self.ack_path.read_text(encoding="utf-8"))
            acknowledgments = value.get("acknowledgments") if isinstance(value, dict) else None
            if (set(value) != {"version", "acknowledgments"} or value["version"] != _ACK_VERSION
                    or not isinstance(acknowledgments, dict)):
                raise ValueError("invalid acknowledgment file")
            return acknowledgments
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            raise HandoffError("Swing Board handoff acknowledgment file is invalid") from None

    def _persist_acks(self, acknowledgments: dict[str, dict[str, object]]) -> None:
        self.ack_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.ack_path.with_name(f".{self.ack_path.name}.{os.getpid()}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            with os.fdopen(descriptor, "wb") as target:
                target.write(_encode({"version": _ACK_VERSION, "acknowledgments": acknowledgments}))
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.ack_path)
            os.chmod(self.ack_path, 0o600)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise HandoffError("cannot persist Swing Board handoff acknowledgment") from None

    def _operation_payload(
        self,
        snapshot_db: sqlite3.Connection,
        operation: str,
        dedupe_key: str,
        payload_json: str,
        episode: sqlite3.Row | None,
    ) -> dict[str, object]:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            raise HandoffError("Swing Board outbox payload is invalid") from None
        if not isinstance(payload, dict):
            raise HandoffError("Swing Board outbox payload is invalid")
        payload = dict(payload)
        tag_names = payload.get("tag_names")
        if isinstance(tag_names, list) and LEGACY_SOURCE_PLAN in tag_names:
            try:
                current_tag = desired_lifecycle_tag(
                    str(episode["lifecycle"]),
                    episode["lifecycle_tag"],
                    episode_sources_from_connection(snapshot_db, int(episode["id"])),
                )
            except (KeyError, TypeError, ValueError):
                raise HandoffError(
                    "Swing Board legacy source tag cannot be resolved from episode state"
                ) from None
            payload["tag_names"] = [
                current_tag if name == LEGACY_SOURCE_PLAN else name for name in tag_names
            ]
        payload["_delivery_key"] = dedupe_key
        payload.setdefault("nonce_value", dedupe_key)
        if operation != "create_thread":
            if episode is None or not episode["thread_id"]:
                raise HandoffError("Swing Board operation has no stored thread identity")
            if operation == "delete_message":
                payload.setdefault("thread_id", episode["thread_id"])
            else:
                payload.update(
                    thread_id=episode["thread_id"],
                    message_id=payload.pop("target_message_id", episode["starter_message_id"]),
                )
        media_field = "chart" if operation in {"create_thread", "edit_starter"} else "media"
        media_value = payload.get(media_field)
        if media_value is None and payload.get("media_url"):
            media_path = _cached_media(self.media_root, dedupe_key, payload["media_url"])
            if media_path is None:
                raise HandoffError("Swing Board create media has no persisted cache copy")
            payload[media_field] = str(media_path)
        media_value = payload.get(media_field)
        if media_value is not None:
            _attachment(Path(str(media_value)))
        return payload

    def _intent(
        self,
        operation: str,
        dedupe_key: str,
        payload: dict[str, object],
        *,
        pending_create: bool,
        create_snapshot: object,
    ) -> tuple[OperationIntent, Mapping[str, Any] | None]:
        prepared = self.transport.prepare_payload(operation, payload)
        base = self.transport._intent(operation, prepared, dedupe_key)
        attachment = base.attachments[0] if base.attachments else None
        snapshot = create_snapshot if isinstance(create_snapshot, dict) else None
        preflight: Mapping[str, Any] | None = None
        legacy_nonce: str | None = None
        if pending_create:
            boundary = None
            if snapshot is not None:
                if (snapshot.get("content") != prepared.get("content")
                        or snapshot.get("filename") != (attachment.filename if attachment else None)
                        or not isinstance(snapshot.get("after_id"), str)
                        or not snapshot["after_id"].isdigit()):
                    raise HandoffError("Swing Board persisted create snapshot does not match its intent")
                boundary = snapshot["after_id"]
                preflight = {"boundary_observed": True, "boundary": boundary}
            base = replace(base, reconcile_before_first_create=True)
            if base.kind == "thread_message_create":
                nonce_source = snapshot.get("operation_key") if snapshot else prepared.get("nonce_value")
                if isinstance(nonce_source, str):
                    legacy_nonce = stable_nonce(nonce_source)
                base = replace(base, legacy_nonce=legacy_nonce)
        return base, preflight

    def build_handoff_snapshot(self) -> HandoffSnapshot:
        backup_bytes, snapshot_db = _readonly_snapshot(self.state_path)
        try:
            episodes = {
                int(row["id"]): row
                for row in snapshot_db.execute("SELECT * FROM episodes ORDER BY id").fetchall()
            }
            items: list[HandoffItem] = []
            self._operations = {}
            rows = snapshot_db.execute("SELECT * FROM outbox ORDER BY id").fetchall()
            for row in rows:
                operation_name = str(row["operation"])
                status = str(row["status"])
                pending_create = status != "complete" and operation_name in {
                    "create_thread", "post_source_reply", "post_history_reply"
                }
                # Updates and deletes are idempotent desired-state writes. Board
                # retains these pending rows and submits them by their same key.
                if status != "complete" and not pending_create:
                    continue
                episode = episodes.get(int(row["episode_id"]))
                if episode is None:
                    raise HandoffError("Swing Board outbox episode is unavailable")
                if pending_create and operation_name != "create_thread" and not episode["thread_id"]:
                    # Replies cannot be handed off until the owner materializes
                    # the topic and applies its accepted thread receipt.
                    continue
                payload = self._operation_payload(
                    snapshot_db, operation_name, row["dedupe_key"], row["payload_json"], episode
                )
                intent, preflight = self._intent(
                    operation_name,
                    row["dedupe_key"],
                    payload,
                    pending_create=pending_create,
                    create_snapshot=payload.get("create_snapshot"),
                )
                receipt = self._known_receipt(operation_name, row, episode, intent)
                item = HandoffItem(intent, receipt=receipt, preflight=preflight)
                self._operations[intent.key] = intent
                items.append(item)

            table = snapshot_db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='channel_outbox'"
            ).fetchone()
            if table:
                for row in snapshot_db.execute("SELECT * FROM channel_outbox ORDER BY id").fetchall():
                    pending = row["status"] != "complete"
                    intent = OperationIntent(
                        key=operation_key(row["dedupe_key"]),
                        kind="channel_message_create",
                        ordering_key=f"channel:{row['channel_id']}",
                        target={"channel_id": row["channel_id"]},
                        payload={"content": row["content"], "allowed_mentions": {"parse": []}},
                        reconcile_before_first_create=pending,
                        legacy_nonce=stable_nonce(row["dedupe_key"]) if pending else None,
                    )
                    receipt = None
                    if not pending and row["completion_json"]:
                        receipt_data = json.loads(row["completion_json"])
                        message_id = receipt_data.get("message_id") if isinstance(receipt_data, dict) else None
                        if not isinstance(message_id, str):
                            raise HandoffError("Swing Board heartbeat receipt is invalid")
                        receipt = {"channel_id": row["channel_id"], "message_id": message_id}
                    item = HandoffItem(intent, receipt=receipt, preflight=None)
                    self._operations[intent.key] = intent
                    items.append(item)

            acknowledgments = self._acks()
            for index, item in enumerate(items):
                saved = acknowledgments.get(item.operation.key)
                if saved is None:
                    continue
                try:
                    accepted = OperationReceipt.from_json(saved, item.operation)
                except (TypeError, ValueError):
                    raise HandoffError("Swing Board handoff acknowledgment does not match its operation") from None
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
        except HandoffError:
            raise
        except (KeyError, TypeError, ValueError, sqlite3.Error, DeliveryClientError):
            raise HandoffError("cannot build Swing Board handoff snapshot") from None
        finally:
            snapshot_db.close()

    @staticmethod
    def _known_receipt(
        operation_name: str, row: sqlite3.Row, episode: sqlite3.Row, intent: OperationIntent
    ) -> dict[str, str] | None:
        if row["status"] != "complete":
            return None
        if operation_name == "create_thread":
            thread_id = episode["thread_id"]
            starter_id = episode["starter_message_id"]
            if not thread_id or not starter_id:
                raise HandoffError("completed Swing Board topic has no stored Discord IDs")
            return {"thread_id": str(thread_id), "message_id": str(starter_id)}
        try:
            completion = json.loads(row["completion_json"] or "{}")
        except json.JSONDecodeError:
            raise HandoffError("Swing Board completion receipt is invalid") from None
        if not isinstance(completion, dict):
            raise HandoffError("Swing Board completion receipt is invalid")
        if operation_name in {"post_source_reply", "post_history_reply"}:
            message_id = completion.get("message_id")
            if not isinstance(message_id, str) or not message_id.isdigit():
                raise HandoffError("completed Swing Board reply has no stored Discord ID")
            return {"message_id": message_id}
        if operation_name == "delete_message":
            message_id = intent.target["message_id"]
            return {"message_id": message_id}
        if operation_name == "edit_starter":
            return {"thread_id": intent.target["thread_id"], "message_id": intent.target["message_id"]}
        if operation_name == "patch_thread":
            return {"thread_id": intent.target["thread_id"]}
        raise HandoffError("unsupported completed Swing Board operation")

    def acknowledge(self, receipt: OperationReceipt) -> None:
        operation = self._operations.get(receipt.key)
        if operation is None or operation.digest != receipt.digest:
            raise HandoffError("Swing Board handoff acknowledgment key does not match its operation")
        acknowledgments = self._acks()
        previous = acknowledgments.get(receipt.key)
        if previous is not None:
            try:
                accepted = OperationReceipt.from_json(previous, operation)
            except (TypeError, ValueError):
                raise HandoffError("Swing Board handoff acknowledgment is invalid") from None
            if accepted.digest != receipt.digest:
                raise HandoffError("Swing Board handoff operation digest changed")
            return
        acknowledgments[receipt.key] = _receipt_document(receipt)
        self._persist_acks(acknowledgments)


def _delivery_client_from_environment(*, include_admin: bool) -> DeliveryClient:
    base_url = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_URL", "http://127.0.0.1:9140")
    token_path = Path(os.environ.get(
        "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE",
        str(Path.home() / ".hermes/secrets/bursawatch-discord-delivery-client-token"),
    )).expanduser()
    admin_path = None
    if include_admin:
        configured = os.environ.get("BURSAWATCH_DISCORD_DELIVERY_ADMIN_TOKEN_FILE")
        if not configured:
            raise DeliveryClientError("admin_credentials_required")
        admin_path = Path(configured).expanduser()
    return DeliveryClient(base_url, token_path, admin_token_file=admin_path)


def _state_path() -> Path:
    return Path(os.environ.get(
        "IDX_SWING_PLAN_BOARD_STATE_PATH",
        str(Path.home() / ".hermes/state/idx-swing-board.sqlite3"),
    )).expanduser()


def _media_root() -> Path:
    return Path(os.environ.get(
        "IDX_SWING_PLAN_BOARD_MEDIA_ROOT",
        str(Path.home() / ".hermes/state/idx-swing-board-media"),
    )).expanduser()


def apply_swing_board_handoff(
    plan_path: Path,
    adapter: SwingBoardHandoffAdapter,
    client: DeliveryClient,
    *,
    apply: bool,
    environment: Mapping[str, str] | None = None,
):
    """Require both handoff gates before the shared service can be mutated."""
    require_apply_authorization(apply=apply, environment=environment)
    return apply_handoff(plan_path, adapter, client)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", type=Path, metavar="PATH", help="write a private, payload-free read-only plan")
    mode.add_argument("--apply", type=Path, metavar="PATH", help="apply a previously reviewed plan")
    args = parser.parse_args(argv)
    try:
        if args.plan is not None:
            client = _delivery_client_from_environment(include_admin=False)
            adapter = SwingBoardHandoffAdapter(
                _state_path(), args.plan, media_root=_media_root(), delivery_client=client
            )
            plan = plan_handoff(adapter, plan_path=args.plan)
            print(json.dumps(plan.as_dict(), sort_keys=True, separators=(",", ":")))
            return 0
        require_apply_authorization(apply=True)
        client = _delivery_client_from_environment(include_admin=True)
        adapter = SwingBoardHandoffAdapter(
            _state_path(), args.apply, media_root=_media_root(), delivery_client=client
        )
        result = apply_swing_board_handoff(args.apply, adapter, client, apply=True)
        print(json.dumps({
            "acknowledged_count": result.acknowledged_count,
            "skipped_count": result.skipped_count,
            "backup_created": result.backup_path.is_file(),
        }, sort_keys=True, separators=(",", ":")))
        return 0
    except (HandoffError, DeliveryClientError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
