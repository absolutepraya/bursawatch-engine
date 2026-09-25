from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHARED_BIN = ROOT / "lib-bursawatch-discord-delivery" / "bin"
sys.path.insert(0, str(SHARED_BIN))

import delivery_handoff
import scan
from bursawatch_discord_delivery.handoff import APPLY_ENVIRONMENT_VARIABLE, HandoffError


def _state_with_pending_chart(tmp_state: Path, tmp_path: Path) -> tuple[dict, Path]:
    state = scan.empty_state()
    source = (Path(__file__).parent / "fixtures" / "trading_buy.txt").read_text()
    call = scan.parse_swing_call(33655, source, has_photo=True)
    event = scan.enqueue_call(state, call, scan.current_time())
    chart = tmp_path / "33655.jpg"
    chart.write_bytes(b"source chart bytes")
    event.update(
        phase=scan.PHASE_PENDING_BOARD,
        chart_status="captured",
        media_path=str(chart),
        text_discord_id="987654321012345678",
    )
    scan.save_state(state)
    return state, chart


def test_handoff_plan_keeps_completed_text_and_reconciles_prior_chart_without_replay(
    tmp_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scan, "state_path", lambda: tmp_state)
    state, chart = _state_with_pending_chart(tmp_state, tmp_path)
    before = tmp_state.read_bytes()
    adapter = delivery_handoff.PhintracoHandoffAdapter(tmp_state, tmp_path / "plan.json")

    snapshot = adapter.build_handoff_snapshot()

    assert tmp_state.read_bytes() == before
    assert len(snapshot.items) == 2
    text, image = snapshot.items
    assert text.operation.key == "bursawatch-tg-phintraco-swing:33655:text"
    assert text.receipt == {
        "channel_id": scan.ALERT_CHANNEL_ID,
        "message_id": "987654321012345678",
    }
    assert image.operation.key == "bursawatch-tg-phintraco-swing:33655:chart"
    assert image.operation.attachments[0].data == chart.read_bytes()
    assert image.receipt is None
    assert image.operation.reconcile_before_first_create is True
    assert image.operation.legacy_nonce == scan.discord_nonce("33655", "chart")
    assert image.preflight is None


def test_handoff_apply_requires_the_explicit_cutover_gate(
    tmp_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scan, "state_path", lambda: tmp_state)
    _state_with_pending_chart(tmp_state, tmp_path)
    plan_path = tmp_path / "plan.json"
    adapter = delivery_handoff.PhintracoHandoffAdapter(tmp_state, plan_path)
    delivery_handoff.plan_handoff(adapter, plan_path=plan_path)

    with pytest.raises(HandoffError, match="explicit environment gate"):
        delivery_handoff.apply_phintraco_handoff(
            plan_path,
            adapter,
            object(),
            apply=True,
            environment={APPLY_ENVIRONMENT_VARIABLE: "0"},
        )


def test_handoff_acknowledgments_are_kept_out_of_watcher_state(
    tmp_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scan, "state_path", lambda: tmp_state)
    _state_with_pending_chart(tmp_state, tmp_path)
    adapter = delivery_handoff.PhintracoHandoffAdapter(tmp_state, tmp_path / "plan.json")

    source = json.loads(tmp_state.read_text())
    assert source["outbox"]["33655"]["text_discord_id"] == "987654321012345678"
    assert "delivery_handoff" not in source["outbox"]["33655"]


def test_synthetic_rollback_retry_reuses_phintraco_operation_keys(
    tmp_state: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    support = str(Path(__file__).resolve().parents[2] / "service-bursawatch-control" / "tests")
    if support not in sys.path:
        sys.path.insert(0, support)
    from legacy_handoff_rehearsal import SyntheticDeliveryOwner, rehearse_legacy_handoff

    monkeypatch.setattr(scan, "state_path", lambda: tmp_state)
    _state_with_pending_chart(tmp_state, tmp_path)
    original = tmp_state.read_bytes()
    owner = SyntheticDeliveryOwner()
    adapter = delivery_handoff.PhintracoHandoffAdapter(tmp_state, tmp_path / "plan.json")

    identities = rehearse_legacy_handoff(
        adapter, owner, restore_source=lambda: tmp_state.write_bytes(original)
    )

    assert [key for key, _digest in identities] == [
        "bursawatch-tg-phintraco-swing:33655:text",
        "bursawatch-tg-phintraco-swing:33655:chart",
    ]
    assert len(owner.new_pending_acceptances) == 1
