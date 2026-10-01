from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cron-stockbit-snips" / "bin"))
sys.path.insert(0, str(ROOT / "cron-rss-source-ingest" / "bin"))

from config import FEEDS, LoadedStockbitConfig, load_watch_config_data
from compatible_catalog_transition import TransitionBlocked, apply_plan, build_plan, main

LANES = tuple(feed.lane.value for feed in FEEDS)
STAMP = "2026-09-30T10:00:00+00:00"
PRIVATE_ARTICLE = "private article text must not appear in the transition plan"
RSS_GUARD = "BURSAWATCH_RSS_CATALOG_TRANSITION_ALLOW_APPLY"


def _loaded_config(revision: int = 7, enabled: tuple[str, ...] = LANES) -> LoadedStockbitConfig:
    return LoadedStockbitConfig(
        load_watch_config_data({
            "version": 1,
            "feeds": [{"id": lane, "enabled": lane in enabled} for lane in LANES],
            "destinations": {
                "id_stocks_news_channel_id": "1525102508714889257",
                "macro_news_channel_id": "1531655369884045382",
            },
            "additional_prompt_instruction": "",
        }),
        revision,
    )


def _catalog(revision: int) -> dict:
    return {
        "revision": revision,
        "subscriptions": [
            {
                "platform": "rss",
                "endpoint_id": f"rss:stockbit:{feed.lane.value}",
                "publisher_id": "stockbit",
                "address": feed.url,
                "provider_id": feed.lane.value,
                "capability_id": "stockbit_snips",
                "verification_status": "verified",
                "enabled": True,
                "settings": {"mode": "fixed-rss"},
                "provenance": {"owner": "stockbit-snips"},
                "dispatch": {"pipeline_id": "stockbit_snips", "version": 1},
            }
            for feed in FEEDS
        ],
    }


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _seed_state(root: Path, *, origin: int = 4, marker: int = 4, config_revision: int = 7) -> None:
    root.mkdir(parents=True)
    _write(root / "catalog-revision.json", {"revision": marker})
    _write(root / "watch-config-revision.json", {"revision": config_revision})
    for feed in FEEDS:
        lane = feed.lane.value
        endpoint_id = f"rss:stockbit:{lane}"
        endpoint = {
            "platform": "rss",
            "endpoint_id": endpoint_id,
            "publisher_id": "stockbit",
            "address": feed.url,
            "provider_id": lane,
        }
        anchor = hashlib.sha256(f"legacy-{lane}".encode()).hexdigest()
        _write(root / endpoint_id.replace(":", "-") / "cursor.json", {
            "initialized": True,
            "anchor": anchor,
            "position": None,
            "boundary_published_at": STAMP,
            "legacy_seed": {
                "legacy_state_sha256": "a" * 64,
                "endpoint": endpoint,
                "catalog_revision": origin,
                "proposed_anchor": anchor,
                "cursor_shape": "generic",
                "boundary_timestamp": STAMP,
            },
        })
        _write(root / endpoint_id.replace(":", "-") / "http-validators.json", {
            "version": 1,
            "etag": None,
            "last_modified": None,
        })


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


@pytest.fixture
def transition_case(tmp_path: Path):
    prior = _catalog(4)
    target = _catalog(5)
    state_root = tmp_path / "state"
    _seed_state(state_root)
    loaded_config = _loaded_config()
    return prior, target, state_root, loaded_config


def test_build_plan_previews_one_unchanged_four_lane_projection_without_state_writes(transition_case):
    prior, target, state_root, loaded_config = transition_case
    before = _files(state_root)

    plan = build_plan(prior, target, state_root, loaded_config)

    assert plan["status"] == "preview"
    assert plan["from_revision"] == 4
    assert plan["to_revision"] == 5
    assert plan["seed_origin_revision"] == 4
    assert plan["watch_config_revision"] == 7
    assert re.fullmatch(r"[0-9a-f]{64}", plan["prior_catalog_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", plan["target_catalog_sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", plan["projection_sha256"])
    assert plan["revision_only"] is True
    encoded = json.dumps(plan, sort_keys=True)
    assert all(feed.url not in encoded for feed in FEEDS)
    assert PRIVATE_ARTICLE not in encoded
    assert "source_text" not in encoded
    assert _files(state_root) == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.__setitem__("endpoint_id", "rss:stockbit:unknown"),
        lambda row: row.__setitem__("capability_id", "unknown_capability"),
        lambda row: row["settings"].__setitem__("mode", "changed"),
        lambda row: row["provenance"].__setitem__("owner", "other-owner"),
        lambda row: row.__setitem__("verification_status", "pending"),
        lambda row: row["dispatch"].__setitem__("pipeline_id", "other-pipeline"),
    ],
    ids=["identity", "capability", "settings", "provenance", "verification", "dispatch"],
)
def test_build_plan_rejects_changed_enabled_projection_rows(transition_case, mutate):
    prior, target, state_root, loaded_config = transition_case
    changed = copy.deepcopy(target)
    mutate(changed["subscriptions"][0])

    with pytest.raises(TransitionBlocked):
        build_plan(prior, changed, state_root, loaded_config)


@pytest.mark.parametrize(
    "changed_version", [True, 1.0], ids=["integer-to-boolean", "integer-to-float"]
)
def test_build_plan_rejects_json_numeric_type_changes_in_projection(
    transition_case, changed_version
):
    prior, target, state_root, loaded_config = transition_case
    changed = copy.deepcopy(target)
    changed["subscriptions"][0]["dispatch"]["version"] = changed_version
    before = _files(state_root)

    with pytest.raises(TransitionBlocked):
        build_plan(prior, changed, state_root, loaded_config)

    assert _files(state_root) == before


@pytest.mark.parametrize("case", ["missing", "extra"])
def test_build_plan_rejects_missing_or_extra_enabled_stockbit_lane(transition_case, case):
    prior, target, state_root, loaded_config = transition_case
    changed_prior = copy.deepcopy(prior)
    changed_target = copy.deepcopy(target)
    if case == "missing":
        changed_prior["subscriptions"].pop()
        changed_target["subscriptions"].pop()
    else:
        extra = {**changed_prior["subscriptions"][0], "endpoint_id": "rss:stockbit:extra", "provider_id": "extra"}
        changed_prior["subscriptions"].append(extra)
        changed_target["subscriptions"].append(copy.deepcopy(extra))

    with pytest.raises(TransitionBlocked):
        build_plan(changed_prior, changed_target, state_root, loaded_config)


def test_build_plan_rejects_duplicate_enabled_identity(transition_case):
    prior, target, state_root, loaded_config = transition_case
    prior["subscriptions"].append(copy.deepcopy(prior["subscriptions"][0]))
    target["subscriptions"].append(copy.deepcopy(target["subscriptions"][0]))

    with pytest.raises(TransitionBlocked):
        build_plan(prior, target, state_root, loaded_config)


@pytest.mark.parametrize(
    ("prior", "target"),
    [
        (_catalog(4), _catalog(6)),
        ({"revision": True, "subscriptions": []}, _catalog(5)),
        ({"revision": 4, "subscriptions": None}, _catalog(5)),
        ({"revision": 4, "subscriptions": []}, {"revision": 5, "subscriptions": []}),
    ],
    ids=["nonconsecutive", "boolean-revision", "malformed-prior", "malformed-projection"],
)
def test_build_plan_rejects_invalid_snapshots(transition_case, prior, target):
    _unused_prior, _unused_target, state_root, loaded_config = transition_case

    with pytest.raises(TransitionBlocked):
        build_plan(prior, target, state_root, loaded_config)


def test_build_plan_requires_current_watcher_config_revision(transition_case):
    prior, target, state_root, _loaded = transition_case

    with pytest.raises(TransitionBlocked):
        build_plan(prior, target, state_root, _loaded_config(revision=8))


def test_build_plan_requires_all_four_configured_lanes(transition_case):
    prior, target, state_root, _loaded = transition_case

    with pytest.raises(TransitionBlocked):
        build_plan(prior, target, state_root, _loaded_config(enabled=LANES[:-1]))


def test_build_plan_rejects_symlinked_state_root(transition_case, tmp_path):
    prior, target, state_root, loaded_config = transition_case
    alias = tmp_path / "state-link"
    alias.symlink_to(state_root, target_is_directory=True)

    with pytest.raises(TransitionBlocked):
        build_plan(prior, target, alias, loaded_config)


@pytest.mark.parametrize("plan_kind", ["inside", "symlink_into_state"])
def test_preview_rejects_plan_path_inside_or_symlinked_into_state(transition_case, tmp_path, monkeypatch, capsys, plan_kind):
    import compatible_catalog_transition as transition

    prior, target, state_root, loaded_config = transition_case
    prior_path = tmp_path / "prior.json"
    target_path = tmp_path / "target.json"
    _write(prior_path, prior)
    _write(target_path, target)
    monkeypatch.setattr(transition, "load_watch_config_for_run", lambda: loaded_config)
    if plan_kind == "inside":
        plan_path = state_root / "plan.json"
    else:
        destination = state_root / "linked-plan.json"
        destination.write_text("{}", encoding="utf-8")
        plan_path = tmp_path / "plan-link.json"
        plan_path.symlink_to(destination)

    result = main([
        "preview",
        "--prior-catalog", str(prior_path),
        "--target-catalog", str(target_path),
        "--state-root", str(state_root),
        "--plan-file", str(plan_path),
    ])

    assert result == 2
    assert "https://" not in capsys.readouterr().err


def test_cli_preview_and_apply_use_a_private_redacted_plan(transition_case, tmp_path, monkeypatch, capsys):
    import compatible_catalog_transition as transition

    prior, target, state_root, loaded_config = transition_case
    prior_path = tmp_path / "prior.json"
    target_path = tmp_path / "target.json"
    private_dir = tmp_path / "private"
    private_dir.mkdir(mode=0o700)
    plan_path = private_dir / "rss-plan.json"
    _write(prior_path, prior)
    _write(target_path, target)
    monkeypatch.setattr(transition, "load_watch_config_for_run", lambda: loaded_config)

    preview_status = main([
        "preview",
        "--prior-catalog", str(prior_path),
        "--target-catalog", str(target_path),
        "--state-root", str(state_root),
        "--plan-file", str(plan_path),
    ])

    preview_output = capsys.readouterr()
    assert preview_status == 0
    assert preview_output.err == ""
    preview_result = json.loads(preview_output.out)
    assert set(preview_result) == {
        "status", "from_revision", "to_revision", "seed_origin_revision",
        "watch_config_revision", "state_file_count", "plan_sha256",
    }
    assert preview_result["status"] == "preview"
    assert plan_path.stat().st_mode & 0o777 == 0o600
    plan_text = plan_path.read_text(encoding="utf-8")
    assert all(feed.url not in plan_text for feed in FEEDS)
    assert PRIVATE_ARTICLE not in plan_text

    monkeypatch.setenv(RSS_GUARD, "1")
    apply_status = main([
        "apply",
        "--prior-catalog", str(prior_path),
        "--target-catalog", str(target_path),
        "--state-root", str(state_root),
        "--plan-file", str(plan_path),
    ])

    apply_output = capsys.readouterr()
    assert apply_status == 0
    assert apply_output.err == ""
    apply_result = json.loads(apply_output.out)
    assert set(apply_result) == {
        "status", "from_revision", "to_revision", "state_file_count", "plan_sha256",
    }
    assert apply_result["status"] == "applied"


def test_apply_advances_only_marker_and_journal(transition_case, monkeypatch):
    prior, target, state_root, loaded_config = transition_case
    _write(state_root / "stockbit-owner" / "state.json", {"article": PRIVATE_ARTICLE})
    (state_root / "source-inbox").mkdir()
    (state_root / "source-inbox" / "events.jsonl").write_text(PRIVATE_ARTICLE, encoding="utf-8")
    _write(state_root / "delivery" / "receipts.json", {"operation": "already-delivered", "text": PRIVATE_ARTICLE})
    expected = build_plan(prior, target, state_root, loaded_config)
    before = _files(state_root)
    monkeypatch.setenv(RSS_GUARD, "1")
    monkeypatch.delenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", raising=False)

    result = apply_plan(expected, prior, target, state_root, loaded_config)

    journal = state_root / "catalog-transitions" / "4-to-5.json"
    assert result == {
        "status": "applied",
        "from_revision": 4,
        "to_revision": 5,
        "state_file_count": len(expected["state_files"]),
        "plan_sha256": expected["plan_sha256"],
    }
    after = _files(state_root)
    assert set(after) - set(before) == {"catalog-transitions/4-to-5.json"}
    assert {key: value for key, value in after.items() if key in before and key != "catalog-revision.json"} == {
        key: value for key, value in before.items() if key != "catalog-revision.json"
    }
    assert json.loads((state_root / "catalog-revision.json").read_text()) == {"revision": 5}
    record = json.loads(journal.read_text())
    metadata = record["plan"]["metadata"]
    assert metadata["transition_type"] == "rss-compatible-catalog-transition"
    assert metadata["projection_sha256"] == expected["projection_sha256"]
    assert metadata["watch_config_revision"] == 7
    assert metadata["seed_origin_revision"] == 4
    assert RSS_GUARD not in json.dumps(record)
    assert PRIVATE_ARTICLE not in json.dumps(record)


def test_apply_accepts_and_preserves_complete_prior_journal(transition_case, tmp_path, monkeypatch):
    _prior, _target, _unused_root, loaded_config = transition_case
    state_root = tmp_path / "state-with-history"
    _seed_state(state_root, origin=3, marker=3)
    monkeypatch.setenv(RSS_GUARD, "1")

    first_prior = _catalog(3)
    first_target = _catalog(4)
    first_plan = build_plan(first_prior, first_target, state_root, loaded_config)
    apply_plan(first_plan, first_prior, first_target, state_root, loaded_config)
    historical_journal = state_root / "catalog-transitions" / "3-to-4.json"
    historical_bytes = historical_journal.read_bytes()

    prior = _catalog(4)
    target = _catalog(5)
    expected = build_plan(prior, target, state_root, loaded_config)
    assert expected["seed_origin_revision"] == 3
    apply_plan(expected, prior, target, state_root, loaded_config)

    assert historical_journal.read_bytes() == historical_bytes
    assert json.loads((state_root / "catalog-revision.json").read_text()) == {"revision": 5}


def test_apply_requires_rss_guard_and_leaves_state_unchanged(transition_case, monkeypatch):
    prior, target, state_root, loaded_config = transition_case
    expected = build_plan(prior, target, state_root, loaded_config)
    before = _files(state_root)
    monkeypatch.delenv(RSS_GUARD, raising=False)
    monkeypatch.setenv("BURSAWATCH_ALLOW_LEGACY_CURSOR_SEED_APPLY", "1")

    with pytest.raises(TransitionBlocked):
        apply_plan(expected, prior, target, state_root, loaded_config)

    assert _files(state_root) == before


@pytest.mark.parametrize("tamper", ["plan", "state", "catalog"])
def test_apply_rejects_changed_plan_state_or_catalog_without_writes(transition_case, monkeypatch, tamper):
    prior, target, state_root, loaded_config = transition_case
    expected = build_plan(prior, target, state_root, loaded_config)
    before = _files(state_root)
    if tamper == "plan":
        expected = copy.deepcopy(expected)
        expected["projection_sha256"] = "f" * 64
    elif tamper == "state":
        (state_root / "rss-stockbit-unboxing" / "http-validators.json").write_text('{"version":1,"etag":"changed","last_modified":null}', encoding="utf-8")
    else:
        target = copy.deepcopy(target)
        target["subscriptions"][0]["settings"]["mode"] = "changed"
    before_attempt = _files(state_root)
    monkeypatch.setenv(RSS_GUARD, "1")

    with pytest.raises(TransitionBlocked):
        apply_plan(expected, prior, target, state_root, loaded_config)

    assert _files(state_root) == before_attempt


def test_apply_resumes_interrupted_edge_from_same_plan(transition_case, monkeypatch):
    import legacy_cursor_seed

    prior, target, state_root, loaded_config = transition_case
    expected = build_plan(prior, target, state_root, loaded_config)
    preserved = {
        key: value
        for key, value in _files(state_root).items()
        if key != "catalog-revision.json"
    }
    transition_path = state_root / "catalog-transitions" / "4-to-5.json"
    real_write = legacy_cursor_seed._write_private_json

    def interrupt_completion(path: Path, value: dict) -> None:
        if path == transition_path and value.get("status") == "complete":
            raise OSError("synthetic final journal interruption")
        real_write(path, value)

    monkeypatch.setenv(RSS_GUARD, "1")
    monkeypatch.setattr(legacy_cursor_seed, "_write_private_json", interrupt_completion)
    with pytest.raises(OSError, match="synthetic final journal interruption"):
        apply_plan(expected, prior, target, state_root, loaded_config)

    assert json.loads((state_root / "catalog-revision.json").read_text()) == {"revision": 5}
    assert json.loads(transition_path.read_text())["status"] == "applying"
    assert {key: value for key, value in _files(state_root).items() if key not in {"catalog-revision.json", "catalog-transitions/4-to-5.json"}} == preserved

    monkeypatch.setattr(legacy_cursor_seed, "_write_private_json", real_write)
    result = apply_plan(expected, prior, target, state_root, loaded_config)

    assert result["status"] == "applied"
    assert json.loads(transition_path.read_text())["status"] == "complete"
    assert {key: value for key, value in _files(state_root).items() if key not in {"catalog-revision.json", "catalog-transitions/4-to-5.json"}} == preserved


@pytest.mark.parametrize("location", ["state_root", "transition_directory"])
def test_apply_resumes_after_crash_left_private_atomic_write_temporary(
    transition_case, monkeypatch, location
):
    prior, target, state_root, loaded_config = transition_case
    expected = build_plan(prior, target, state_root, loaded_config)
    temporary_directory = (
        state_root
        if location == "state_root"
        else state_root / "catalog-transitions"
    )
    temporary_directory.mkdir(mode=0o700, exist_ok=True)
    temporary = temporary_directory / ".catalog-transition-abcde123"
    temporary.write_bytes(b'{"version":1')
    temporary.chmod(0o600)
    monkeypatch.setenv(RSS_GUARD, "1")

    result = apply_plan(expected, prior, target, state_root, loaded_config)

    assert result["status"] == "applied"
    assert not temporary.exists()
    assert json.loads(
        (state_root / "catalog-transitions" / "4-to-5.json").read_text()
    )["status"] == "complete"


@pytest.mark.parametrize("name", ["unexpected.json", ".catalog-transition-short"])
def test_build_plan_rejects_unrecognized_transition_directory_entry(
    transition_case, name
):
    prior, target, state_root, loaded_config = transition_case
    transition_directory = state_root / "catalog-transitions"
    transition_directory.mkdir(mode=0o700)
    (transition_directory / name).write_text("unexpected", encoding="utf-8")

    with pytest.raises(TransitionBlocked):
        build_plan(prior, target, state_root, loaded_config)


@pytest.mark.parametrize("kind", ["wrong_mode", "symlink"])
def test_build_plan_rejects_unsafe_catalog_transition_temporary(
    transition_case, kind
):
    prior, target, state_root, loaded_config = transition_case
    transition_directory = state_root / "catalog-transitions"
    transition_directory.mkdir(mode=0o700)
    temporary = transition_directory / ".catalog-transition-abcde123"
    if kind == "symlink":
        target_file = state_root / "watch-config-revision.json"
        temporary.symlink_to(target_file)
    else:
        temporary.write_text("partial", encoding="utf-8")
        temporary.chmod(0o644)

    with pytest.raises(TransitionBlocked):
        build_plan(prior, target, state_root, loaded_config)


def test_build_plan_rejects_missing_or_foreign_prior_journal(transition_case):
    prior, target, state_root, loaded_config = transition_case
    _write(state_root / "catalog-revision.json", {"revision": 5})

    with pytest.raises(TransitionBlocked):
        build_plan(_catalog(5), _catalog(6), state_root, loaded_config)

    (state_root / "catalog-transitions").mkdir()
    _write(state_root / "catalog-transitions" / "4-to-5.json", {
        "version": 1,
        "status": "complete",
        "plan": {"metadata": {"transition_type": "foreign-transition"}},
        "seeded_endpoints": [],
    })
    with pytest.raises(TransitionBlocked):
        build_plan(_catalog(5), _catalog(6), state_root, loaded_config)
