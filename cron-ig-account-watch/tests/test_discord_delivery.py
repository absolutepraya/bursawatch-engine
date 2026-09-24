from __future__ import annotations

from pathlib import Path

import pytest

import discord
from bursawatch_discord_delivery.models import OperationReceipt


class _DeliveryOwner:
    def __init__(self):
        self.operations = {}
        self.submissions = []

    def status(self, operation_key):
        return self.operations.get(operation_key)

    def submit(self, operation):
        self.submissions.append(operation)
        receipt = OperationReceipt(
            id=f"operation-{len(self.submissions)}",
            key=operation.key,
            digest=operation.digest,
            status="delivered",
            receipt={"channel_id": operation.target["channel_id"], "message_id": "8001"},
        )
        self.operations[operation.key] = receipt
        return receipt


def test_retried_media_returns_existing_owner_id_and_preserves_exact_ordered_bytes(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    event_dir = media_root / "event-a"
    event_dir.mkdir(parents=True)
    image = event_dir / "image-0.jpg"
    image.write_bytes(b"carousel-image-zero")
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(media_root))
    owner = _DeliveryOwner()
    key_nonce = discord.nonce("profile:publication", "media:0")

    first = discord.post_media(
        image,
        "123456789012345678",
        False,
        key_nonce,
        event_key="profile:publication",
        operation_leg="media:0",
        client=owner,
    )
    retried = discord.post_media(
        image,
        "123456789012345678",
        False,
        key_nonce,
        event_key="profile:publication",
        operation_leg="media:0",
        client=owner,
    )

    assert first == retried == "8001"
    assert len(owner.submissions) == 1
    operation = owner.submissions[0]
    assert operation.kind == "channel_message_create"
    assert operation.attachments[0].filename == "image-0.jpg"
    assert operation.attachments[0].data == b"carousel-image-zero"


def test_media_symlink_rejected_before_any_service_upload(tmp_path, monkeypatch):
    media_root = tmp_path / "media"
    event_dir = media_root / "event-a"
    event_dir.mkdir(parents=True)
    target = event_dir / "real.jpg"
    target.write_bytes(b"original-image")
    alias = event_dir / "alias.jpg"
    alias.symlink_to(target)
    monkeypatch.setenv("INSTAGRAM_POST_WATCH_MEDIA_ROOT", str(media_root))
    owner = _DeliveryOwner()

    with pytest.raises(ValueError, match="media path is invalid"):
        discord.post_media(
            alias,
            "123456789012345678",
            False,
            discord.nonce("profile:publication", "media:0"),
            event_key="profile:publication",
            operation_leg="media:0",
            client=owner,
        )

    assert owner.submissions == []
