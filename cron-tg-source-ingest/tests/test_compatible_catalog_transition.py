from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-tg-source-ingest" / "bin"))
from compatible_catalog_transition import TransitionBlocked, apply_plan, build_plan, main


def _telegram_rows():
    rows = []
    profiles = [
        ("telegram:phintraprofits", "phintraco", "phintraprofits", "1444713822", ["trading_plans"]),
        ("telegram:phintasprofits", "phintraco", "phintasprofits", None, ["company_news", "macro_news", "stock_status"]),
        ("telegram:kelasinvestasiid", "kelas-investasi", "kelasinvestasiid", "2142109618", ["swing_support"]),
        ("telegram:tuntunsekuritas", "tuntun", "tuntunsekuritas", None, ["company_news", "macro_news"]),
    ]
    for endpoint, publisher, address, provider, capabilities in profiles:
        for capability in capabilities:
            rows.append({
                "endpoint_id": endpoint,
                "publisher_id": publisher,
                "platform": "telegram",
                "address": address,
                "provider_id": provider,
                "credential_ref": "credential:telegram",
                "capability_id": capability,
                "pipeline": capability,
                "dispatch_group": capability,
                "enabled": True,
                "verification_status": "verified",
                "settings": {"language": "id"},
                "source": "endpoint_override",
            })
    return rows


def _catalogs():
    rows = _telegram_rows()
    prior = {"revision": 3, "updated_at": "2026-09-27T00:00:00Z", "selected_securities": ["BBRI", "BMRI"], "subscriptions": rows}
    target = {"revision": 4, "updated_at": "2026-09-28T00:00:00Z", "selected_securities": ["BBRI", "BMRI"], "subscriptions": copy.deepcopy(rows) + [{
        "endpoint_id": "x:writingtorch",
        "publisher_id": "writingtorch",
        "platform": "x",
        "address": "writingtorch",
        "provider_id": None,
        "credential_ref": None,
        "capability_id": "company_news",
        "pipeline": "company_news",
        "dispatch_group": "news",
        "enabled": True,
        "verification_status": "verified",
        "settings": {},
        "source": "endpoint_override",
    }]}
    return prior, target


def _state(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    os.chmod(root, 0o700)
    (root / "catalog-revision.json").write_text('{"revision":3}\n')
    for endpoint in ("phintraprofits", "phintasprofits", "kelasinvestasiid", "tuntunsekuritas"):
        directory = root / f"telegram-{endpoint}"
        directory.mkdir()
        (directory / "cursor.json").write_text('{"cursor":35467}\n')
    (root / "telegram-phintraprofits" / "handoff-0001.json").write_text('{"event":"durable"}\n')
    return root


def test_compatible_transition_preserves_all_cursors_and_state(tmp_path, monkeypatch):
    prior, target = _catalogs()
    root = _state(tmp_path)
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    plan = build_plan(prior, target, root)
    monkeypatch.setenv("BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY", "1")

    result = apply_plan(plan, prior, target, root)

    after = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert result["status"] == "applied"
    assert result["preserved_cursor_count"] == 4
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 4}
    for path, content in before.items():
        if path != "catalog-revision.json":
            assert after[path] == content
    journal = json.loads((root / "catalog-transitions" / "compatible-3-to-4.json").read_text())
    assert journal["status"] == "complete"


@pytest.mark.parametrize("change", ["capability", "settings", "identity", "enabled"])
def test_transition_blocks_any_enabled_telegram_row_change(tmp_path, change):
    prior, target = _catalogs()
    changed = target["subscriptions"][0]
    if change == "capability":
        changed["capability_id"] = "macro_news"
    elif change == "settings":
        changed["settings"] = {"language": "en"}
    elif change == "identity":
        changed["provider_id"] = "999"
    else:
        changed["enabled"] = False

    with pytest.raises(TransitionBlocked, match="enabled Telegram"):
        build_plan(prior, target, _state(tmp_path))


def test_transition_blocks_changed_securities_or_revision_gap(tmp_path):
    prior, target = _catalogs()
    root = _state(tmp_path)
    target["selected_securities"] = ["BBRI"]
    with pytest.raises(TransitionBlocked, match="selected securities changed"):
        build_plan(prior, target, root)
    target["selected_securities"] = prior["selected_securities"]
    target["revision"] = 5
    with pytest.raises(TransitionBlocked, match="consecutive"):
        build_plan(prior, target, root)


def test_transition_blocks_missing_or_changed_cursor_after_preview(tmp_path, monkeypatch):
    prior, target = _catalogs()
    root = _state(tmp_path)
    plan = build_plan(prior, target, root)
    (root / "telegram-phintraprofits" / "cursor.json").write_text('{"cursor":35468}\n')
    monkeypatch.setenv("BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY", "1")
    with pytest.raises(TransitionBlocked, match="changed after preview"):
        apply_plan(plan, prior, target, root)

    (root / "telegram-phintraprofits" / "cursor.json").unlink()
    with pytest.raises(TransitionBlocked, match="cursor is missing"):
        build_plan(prior, target, root)


def test_transition_resumes_after_marker_write_before_journal_completion(tmp_path, monkeypatch):
    prior, target = _catalogs()
    root = _state(tmp_path)
    plan = build_plan(prior, target, root)
    journal_path = root / "catalog-transitions" / "compatible-3-to-4.json"
    journal_path.parent.mkdir(mode=0o700)
    journal_path.write_text(json.dumps({"version": 1, "status": "applying", "plan": plan}))
    os.chmod(journal_path, 0o600)
    (root / "catalog-revision.json").write_text('{"revision":4}\n')
    monkeypatch.setenv("BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY", "1")

    result = apply_plan(plan, prior, target, root)

    assert result["status"] == "applied"
    assert json.loads(journal_path.read_text())["status"] == "complete"


def test_transition_cli_requires_private_plan_and_explicit_apply(tmp_path, monkeypatch, capsys):
    prior, target = _catalogs()
    root = _state(tmp_path)
    prior_path = tmp_path / "prior.json"
    target_path = tmp_path / "target.json"
    prior_path.write_text(json.dumps(prior))
    target_path.write_text(json.dumps(target))
    plan_path = tmp_path / "private" / "plan.json"
    args = ["--prior-catalog", str(prior_path), "--target-catalog", str(target_path), "--state-root", str(root), "--plan-file", str(plan_path)]

    assert main(["preview", *args]) == 0
    assert plan_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(capsys.readouterr().out)["status"] == "preview"
    assert main(["apply", *args]) == 2
    assert json.loads((root / "catalog-revision.json").read_text())["revision"] == 3
    capsys.readouterr()

    monkeypatch.setenv("BURSAWATCH_ALLOW_COMPATIBLE_CATALOG_TRANSITION_APPLY", "1")
    assert main(["apply", *args]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "applied"
