from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib-bursawatch-source-ingest" / "bin"))
import unchanged_projection_transition as transition

TOOL = ROOT / "lib-bursawatch-source-ingest/bin/unchanged_projection_transition.py"


def _rows(platform, endpoints):
    return [{"platform": platform, "endpoint_id": e, "capability_id": c, "enabled": True, "settings": {}}
            for e in endpoints for c in ("company_news", "macro_news")]


def _catalog(revision, rss=("rss:a", "rss:b"), x=("x:one",)):
    return {"revision": revision, "selected_securities": [], "subscriptions": _rows("rss", rss) + _rows("x", x)}


def _root(tmp_path, revision=8):
    root = tmp_path / "state"
    (root / "rss-a").mkdir(parents=True, mode=0o700)
    root.chmod(0o700)
    (root / "catalog-revision.json").write_text(json.dumps({"revision": revision}))
    (root / "catalog-revision.json").chmod(0o600)
    cursor = root / "rss-a" / "cursor.json"
    cursor.write_bytes(b'{"anchor":"abc","position":null}')
    cursor.chmod(0o600)
    return root, cursor


def test_other_platform_change_advances_the_marker_and_keeps_cursor_bytes(tmp_path, monkeypatch):
    root, cursor = _root(tmp_path)
    before = cursor.read_bytes()
    prior, target = _catalog(8), _catalog(9, x=("x:one", "x:two"))
    plan = transition.build_plan("rss", prior, target, root)
    assert plan["projection_sha256"] and (plan["from_revision"], plan["to_revision"]) == (8, 9)
    assert cursor.read_bytes() == before and json.loads((root / "catalog-revision.json").read_text()) == {"revision": 8}
    with pytest.raises(transition.TransitionBlocked):
        transition.apply_plan(plan, "rss", prior, target, root)  # guard variable absent
    monkeypatch.setenv(transition.APPLY_ENV, "1")
    assert transition.apply_plan(plan, "rss", prior, target, root)["status"] == "applied"
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 9}
    assert cursor.read_bytes() == before
    journal = json.loads((root / "catalog-transitions" / "8-to-9.json").read_text())
    assert journal["status"] == "complete" and journal["plan"]["metadata"]["transition_type"] == transition.TRANSITION_TYPE
    assert transition.apply_plan(plan, "rss", prior, target, root)["status"] == "applied"  # idempotent


@pytest.mark.parametrize("change", ["own_row_changed", "own_endpoint_added", "own_row_removed", "securities", "not_adjacent"])
def test_rejects_any_change_to_the_roots_own_projection(tmp_path, change):
    root, _ = _root(tmp_path)
    prior, target = _catalog(8), _catalog(9)
    if change == "own_row_changed":
        target["subscriptions"][0]["settings"] = {"x": 1}
    elif change == "own_endpoint_added":
        target = _catalog(9, rss=("rss:a", "rss:b", "rss:c"))
    elif change == "own_row_removed":
        target = _catalog(9, rss=("rss:a",))
    elif change == "securities":
        target["selected_securities"] = ["BBCA"]
    else:
        target["revision"] = 10
    with pytest.raises(transition.TransitionBlocked):
        transition.build_plan("rss", prior, target, root)
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 8}


def test_rejects_state_that_changed_between_preview_and_apply(tmp_path, monkeypatch):
    root, cursor = _root(tmp_path)
    prior, target = _catalog(8), _catalog(9)
    plan = transition.build_plan("rss", prior, target, root)
    cursor.write_bytes(cursor.read_bytes() + b" ")
    monkeypatch.setenv(transition.APPLY_ENV, "1")
    with pytest.raises(transition.TransitionBlocked):
        transition.apply_plan(plan, "rss", prior, target, root)
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 8}


def test_rejects_a_root_that_is_not_at_the_prior_revision_or_is_unsafe(tmp_path):
    root, _ = _root(tmp_path, revision=7)
    with pytest.raises(transition.TransitionBlocked):
        transition.build_plan("rss", _catalog(8), _catalog(9), root)
    root2, _ = _root(tmp_path / "two")
    root2.chmod(0o755)
    with pytest.raises(transition.TransitionBlocked):
        transition.build_plan("rss", _catalog(8), _catalog(9), root2)
    link = tmp_path / "link"
    link.symlink_to(root2, target_is_directory=True)
    with pytest.raises(transition.TransitionBlocked):
        transition.build_plan("rss", _catalog(8), _catalog(9), link)


def test_command_line_preview_then_apply(tmp_path):
    root, cursor = _root(tmp_path)
    before = cursor.read_bytes()
    prior_file, target_file, plan_file = tmp_path / "prior.json", tmp_path / "target.json", tmp_path / "plans" / "plan.json"
    prior_file.write_text(json.dumps(_catalog(8)))
    target_file.write_text(json.dumps(_catalog(9, x=("x:one", "x:two"))))
    base = [sys.executable, str(TOOL)]
    args = ["--platform", "rss", "--prior-catalog", str(prior_file), "--target-catalog", str(target_file), "--state-root", str(root), "--plan-file", str(plan_file)]
    preview = subprocess.run(base + ["preview", *args], capture_output=True, text=True)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["status"] == "preview" and oct(plan_file.stat().st_mode & 0o777) == "0o600"
    blocked = subprocess.run(base + ["apply", *args], capture_output=True, text=True)
    assert blocked.returncode == 2 and json.loads((root / "catalog-revision.json").read_text()) == {"revision": 8}
    env = {"PATH": "/usr/bin:/bin", transition.APPLY_ENV: "1"}
    applied = subprocess.run(base + ["apply", *args], capture_output=True, text=True, env=env)
    assert applied.returncode == 0, applied.stderr
    assert json.loads((root / "catalog-revision.json").read_text()) == {"revision": 9} and cursor.read_bytes() == before
    inside = subprocess.run(base + ["preview", *args[:-1], str(root / "plan.json")], capture_output=True, text=True)
    assert inside.returncode == 2


def test_rejects_a_generation_root(tmp_path):
    root, _ = _root(tmp_path)
    (root / "catalog-revision.json").write_text(json.dumps({"revision": 8, "generation": {"mode": "future_only", "version": 1, "projection_sha256": "0" * 64}}))
    with pytest.raises(transition.TransitionBlocked):
        transition.build_plan("rss", _catalog(8), _catalog(9), root)
