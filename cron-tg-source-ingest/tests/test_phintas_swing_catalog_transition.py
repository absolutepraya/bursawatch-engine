from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT / "lib-bursawatch-control" / "bin"))
sys.path.insert(0, str(ROOT / "lib-bursawatch-source-ingest" / "bin"))
sys.path.insert(0, str(ROOT / "cron-tg-source-ingest" / "bin"))

from adapter import LegacySeedBlocked, plan_phintas_swing_catalog_transition
from phintas_swing_catalog_transition import _load_object, _write_new_private_json


def _row(endpoint_id: str, address: str, provider_id: str | None, capability: str,
         pipeline: str, enabled: bool, source: str) -> dict:
    return {
        "platform": "telegram",
        "endpoint_id": endpoint_id,
        "publisher_id": "phintraco",
        "address": address,
        "provider_id": provider_id,
        "capability_id": capability,
        "pipeline": pipeline,
        "dispatch_group": None,
        "enabled": enabled,
        "verification_status": "verified",
        "settings": {},
        "source": source,
    }


def _catalogs() -> tuple[dict, dict]:
    rows = [
        _row("telegram:phintraprofits", "phintraprofits", "1444713822", "trading_plans", "swing_plan", True, "endpoint_override"),
        _row("telegram:phintasprofits", "phintasprofits", None, "company_news", "company_news", True, "endpoint_override"),
        _row("telegram:phintasprofits", "phintasprofits", None, "macro_news", "macro_news", True, "endpoint_override"),
        _row("telegram:phintasprofits", "phintasprofits", None, "stock_status", "stock_status", True, "endpoint_override"),
        _row("telegram:phintasprofits", "phintasprofits", None, "trading_plans", "swing_plan", False, "unset"),
    ]
    prior = {"revision": 7, "selected_securities": [], "subscriptions": rows}
    target = deepcopy(prior)
    target["revision"] = 8
    for row in target["subscriptions"]:
        if row["endpoint_id"] == "telegram:phintraprofits":
            row["enabled"] = False
        elif row["endpoint_id"] == "telegram:phintasprofits" and row["capability_id"] == "trading_plans":
            row["enabled"] = True
            row["source"] = "endpoint_override"
    return prior, target


def _state_root(tmp_path: Path, *, cursor: int = 35556) -> tuple[Path, bytes, bytes]:
    root = tmp_path / "telegram-source-state"
    root.mkdir(mode=0o700)
    target_dir = root / "telegram-phintasprofits"
    target_dir.mkdir(mode=0o700)
    target_path = target_dir / "cursor.json"
    target_path.write_text(json.dumps({"cursor": cursor, "bootstrap_cursor": 35483}, separators=(",", ":")))
    target_path.chmod(0o600)
    old_dir = root / "telegram-phintraprofits"
    old_dir.mkdir(mode=0o700)
    old_path = old_dir / "cursor.json"
    old_path.write_text('{"cursor":35556}\n')
    old_path.chmod(0o600)
    revision = root / "catalog-revision.json"
    revision.write_text('{"revision":7}\n')
    revision.chmod(0o600)
    other = root / "agent-dispatch.json"
    other.write_text('{"version":1,"last_owner":"market_news"}\n')
    other.chmod(0o600)
    return root, target_path.read_bytes(), old_path.read_bytes()


def test_phintas_transition_moves_only_swing_capability_and_preserves_both_cursors(tmp_path, monkeypatch):
    prior, target = _catalogs()
    root, target_cursor, legacy_cursor = _state_root(tmp_path)

    preview = plan_phintas_swing_catalog_transition(prior, target, root)

    assert preview["revision_only"] is True
    assert preview["seeds"] == []
    assert preview["metadata"]["preserved_cursor"]["message_id"] == 35556
    monkeypatch.setenv("BURSAWATCH_ALLOW_PHINTAS_SWING_CATALOG_TRANSITION_APPLY", "1")
    applied = plan_phintas_swing_catalog_transition(prior, target, root, apply=True, expected_plan=preview)

    assert applied["status"] == "applied"
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 8}
    assert (root / "telegram-phintasprofits" / "cursor.json").read_bytes() == target_cursor
    assert (root / "telegram-phintraprofits" / "cursor.json").read_bytes() == legacy_cursor
    assert json.loads((root / "catalog-transitions/7-to-8.json").read_text())["status"] == "complete"


def test_phintas_transition_rejects_unrelated_catalog_changes(tmp_path):
    prior, target = _catalogs()
    target["subscriptions"][1]["settings"] = {"unexpected": True}
    root, _, _ = _state_root(tmp_path)

    with pytest.raises(LegacySeedBlocked, match="only the legacy and canonical"):
        plan_phintas_swing_catalog_transition(prior, target, root)


def test_phintas_transition_requires_existing_cursor_and_does_not_seed_it(tmp_path):
    prior, target = _catalogs()
    root, _, _ = _state_root(tmp_path)
    (root / "telegram-phintasprofits" / "cursor.json").unlink()

    with pytest.raises(LegacySeedBlocked, match="initialized Phintas cursor is required"):
        plan_phintas_swing_catalog_transition(prior, target, root)


def test_phintas_transition_apply_requires_guard_and_unchanged_state(tmp_path):
    prior, target = _catalogs()
    root, _, _ = _state_root(tmp_path)
    preview = plan_phintas_swing_catalog_transition(prior, target, root)

    with pytest.raises(LegacySeedBlocked, match="BURSAWATCH_ALLOW_PHINTAS_SWING_CATALOG_TRANSITION_APPLY=1"):
        plan_phintas_swing_catalog_transition(prior, target, root, apply=True, expected_plan=preview)
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 7}


def test_phintas_transition_rejects_cursor_change_after_preview(tmp_path, monkeypatch):
    prior, target = _catalogs()
    root, _, _ = _state_root(tmp_path)
    preview = plan_phintas_swing_catalog_transition(prior, target, root)
    cursor = root / "telegram-phintasprofits" / "cursor.json"
    cursor.write_text('{"cursor":35557}\n')
    cursor.chmod(0o600)
    monkeypatch.setenv("BURSAWATCH_ALLOW_PHINTAS_SWING_CATALOG_TRANSITION_APPLY", "1")

    with pytest.raises(LegacySeedBlocked, match="unchanged catalog transition preview"):
        plan_phintas_swing_catalog_transition(prior, target, root, apply=True, expected_plan=preview)


def test_transition_cli_writes_an_exclusive_private_preview(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    plan_path = private / "transition.json"
    _write_new_private_json(plan_path, {"revision": 8})

    assert plan_path.stat().st_mode & 0o777 == 0o600
    assert _load_object(plan_path, "catalog transition plan", private=True) == {"revision": 8}
    with pytest.raises(ValueError, match="already exists"):
        _write_new_private_json(plan_path, {"revision": 9})


def test_transition_cli_rejects_symlinked_plan_directory(tmp_path):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)

    with pytest.raises(ValueError, match="cannot traverse a symlink"):
        _write_new_private_json(alias / "transition.json", {"revision": 8})
    assert not (private / "transition.json").exists()
