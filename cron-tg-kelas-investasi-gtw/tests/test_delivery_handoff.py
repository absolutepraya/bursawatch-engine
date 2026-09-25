from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHARED_BIN = ROOT / "lib-bursawatch-discord-delivery" / "bin"
sys.path.insert(0, str(SHARED_BIN))

import delivery_handoff
import discord
import state
from bursawatch_discord_delivery.handoff import APPLY_ENVIRONMENT_VARIABLE, HandoffError
from fixtures.messages import at, header


def _state_with_completed_text_and_pending_image(path: Path, media_root: Path) -> dict[str, object]:
    image_path = media_root / "source.jpg"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"\xff\xd8\xffsource image bytes")
    value = state.new_state()
    value["cursor"] = 100
    state.observe_messages(
        value,
        [header(101, "CTRA"), header(102, "BREN")],
        at("2026-08-11T09:00:00+07:00"),
    )
    event = state.ready_events(value, at("2026-08-11T09:00:00+07:00"))[0]
    event.update(
        title="CTRA: Akumulasi kuat",
        summary="*(Ringkasan)* Ringkasan tervalidasi.",
        media=[{"message_id": 101, "ordinal": 0, "path": str(image_path)}],
        text_message_ids=["876543210123456789"],
        text_index=1,
    )
    state.save_state(path, value)
    return value


def test_handoff_preserves_text_receipt_and_orders_image_after_source_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "watcher.json"
    media_root = tmp_path / "media"
    monkeypatch.setenv("KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT", str(media_root))
    source = _state_with_completed_text_and_pending_image(state_path, media_root)
    before = state_path.read_bytes()
    adapter = delivery_handoff.KelasInvestasiHandoffAdapter(
        state_path, tmp_path / "plan.json", media_root=media_root
    )

    snapshot = adapter.build_handoff_snapshot()

    assert state_path.read_bytes() == before
    assert len(snapshot.items) == 2
    text, image = snapshot.items
    assert text.operation.key == "bursawatch-tg-kelas-investasi-gtw:101:CTRA:text:0"
    assert text.receipt == {
        "channel_id": "1525102458253217803",
        "message_id": "876543210123456789",
    }
    assert image.operation.key == "bursawatch-tg-kelas-investasi-gtw:101:CTRA:media:0"
    assert image.operation.attachments[0].data == b"\xff\xd8\xffsource image bytes"
    assert image.receipt is None
    assert image.operation.reconcile_before_first_create is True
    assert image.operation.legacy_nonce == discord.nonce("101:CTRA", "media:0")
    assert image.preflight is None
    assert source["outbox"][0]["text_message_ids"] == ["876543210123456789"]


def test_handoff_apply_requires_paused_writer_apply_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "watcher.json"
    media_root = tmp_path / "media"
    monkeypatch.setenv("KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT", str(media_root))
    _state_with_completed_text_and_pending_image(state_path, media_root)
    plan_path = tmp_path / "plan.json"
    adapter = delivery_handoff.KelasInvestasiHandoffAdapter(
        state_path, plan_path, media_root=media_root
    )
    delivery_handoff.plan_handoff(adapter, plan_path=plan_path)

    with pytest.raises(HandoffError, match="explicit environment gate"):
        delivery_handoff.apply_kelas_investasi_handoff(
            plan_path,
            adapter,
            object(),
            apply=True,
            environment={APPLY_ENVIRONMENT_VARIABLE: "0"},
        )


def test_handoff_source_acknowledgments_do_not_change_outbox_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "watcher.json"
    media_root = tmp_path / "media"
    monkeypatch.setenv("KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT", str(media_root))
    _state_with_completed_text_and_pending_image(state_path, media_root)
    adapter = delivery_handoff.KelasInvestasiHandoffAdapter(
        state_path, tmp_path / "plan.json", media_root=media_root
    )

    adapter.build_handoff_snapshot()

    persisted = json.loads(state_path.read_text())
    assert set(persisted["outbox"][0]) == set(
        state.load_state(state_path)["outbox"][0]
    )
    assert "delivery_handoff" not in persisted["outbox"][0]


def test_synthetic_rollback_retry_reuses_kelas_operation_keys(tmp_path, monkeypatch):
    import sys

    support = str(Path(__file__).resolve().parents[2] / "service-bursawatch-control" / "tests")
    if support not in sys.path:
        sys.path.insert(0, support)
    from legacy_handoff_rehearsal import SyntheticDeliveryOwner, rehearse_legacy_handoff

    state_path = tmp_path / "watcher.json"
    media_root = tmp_path / "media"
    monkeypatch.setenv("KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT", str(media_root))
    _state_with_completed_text_and_pending_image(state_path, media_root)
    original = state_path.read_bytes()
    owner = SyntheticDeliveryOwner()
    adapter = delivery_handoff.KelasInvestasiHandoffAdapter(
        state_path, tmp_path / "kelas-handoff.json", media_root=media_root
    )

    identities = rehearse_legacy_handoff(
        adapter, owner, restore_source=lambda: state_path.write_bytes(original)
    )

    assert len(identities) == 2
    assert len(owner.new_pending_acceptances) == 1
