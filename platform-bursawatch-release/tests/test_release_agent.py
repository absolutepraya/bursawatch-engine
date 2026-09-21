from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "bin"))
import release_agent


def manifest() -> release_agent.ReleaseManifest:
    return release_agent.ReleaseManifest.load(ROOT / "release-manifest.json")


def test_manifest_maps_every_current_tracked_path_exactly_once():
    tracked = subprocess.check_output(["git", "ls-files"], cwd=REPOSITORY_ROOT, text=True).splitlines()
    result = manifest()

    unmatched = []
    ambiguous = []
    for path in tracked:
        matches = [
            unit.identifier
            for unit in result.units
            if any(release_agent.fnmatch.fnmatchcase(path, pattern) for pattern in unit.paths)
        ]
        if not matches:
            unmatched.append(path)
        elif len(matches) > 1:
            ambiguous.append((path, matches))

    assert unmatched == []
    assert ambiguous == []


def test_manifest_orders_dependencies_before_the_x_runtime_unit():
    units = manifest().matching_units(["cron-x-account-watch/bin/scan.py"])

    assert [unit.identifier for unit in units] == [
        "lib-bursawatch-control",
        "lib-swing-format",
        "cron-dc-swing-board",
        "cron-x-account-watch",
    ]


def test_manifest_rejects_an_unmapped_changed_path():
    with pytest.raises(release_agent.ReleaseError, match="exactly once"):
        manifest().matching_units(["new-unmapped-runtime/file.py"])


def test_manifest_marks_host_bound_release_assets_manual():
    units = manifest().matching_units(["platform-bursawatch-release/deployment/systemd/bursawatch-release-agent.service"])

    assert [(unit.identifier, unit.handler) for unit in units] == [
        ("manual-release-agent-bootstrap", "manual"),
    ]


def test_whatsapp_runtime_manifest_includes_archive_operator_wrapper():
    units = manifest().matching_units(["cron-wa-channel-watch/bin/bursawatch-wa-channel-archive.sh"])

    whatsapp = next(unit for unit in units if unit.identifier == "cron-wa-channel-watch")
    assert ("bursawatch-wa-channel-archive.sh", "bursawatch-wa-channel-archive.sh") in whatsapp.wrappers


def test_manifest_maps_market_news_watchdog_wrapper_to_its_vps_name():
    unit = next(unit for unit in manifest().units if unit.identifier == "cron-tg-market-news")

    assert ("watchdog-wrapper.sh", "bursawatch-tg-market-news-watchdog.sh") in unit.wrappers


def test_release_no_post_mode_keeps_wrappers_from_reloading_control_plane_credentials():
    wrappers = [
        REPOSITORY_ROOT / "cron-tg-market-news/bin/bursawatch-tg-market-news.sh",
        REPOSITORY_ROOT / "cron-tg-phintraco-swing/bin/bursawatch-tg-phintraco-swing.sh",
        REPOSITORY_ROOT / "cron-tg-kelas-investasi-gtw/bin/bursawatch-tg-kelas-investasi-gtw.sh",
        REPOSITORY_ROOT / "cron-dc-swing-board/bin/bursawatch-dc-swing-board.sh",
        REPOSITORY_ROOT / "cron-x-account-watch/bin/bursawatch-x-account-watch.sh",
        REPOSITORY_ROOT / "cron-ig-account-watch/bin/bursawatch-ig-account-watch.sh",
        REPOSITORY_ROOT / "cron-wa-channel-watch/bin/bursawatch-wa-channel-watch.sh",
    ]

    for wrapper in wrappers:
        source = wrapper.read_text(encoding="utf-8")
        assert "BURSAWATCH_RELEASE_NO_POST" in source


def test_changed_migrations_require_a_header_and_manual_migrations_block_automatic_release(
    tmp_path: Path,
):
    migrations = tmp_path / "service-bursawatch-control/migrations"
    migrations.mkdir(parents=True)
    (migrations / "legacy-release-eligibility.json").write_text(
        json.dumps({"version": 1, "migrations": {"001_legacy.sql": "automatic"}}),
        encoding="utf-8",
    )
    (migrations / "008_manual.sql").write_text(
        "-- bursawatch-release: manual\nselect 1;\n", encoding="utf-8"
    )

    manual = release_agent._changed_manual_migrations(
        tmp_path, ["service-bursawatch-control/migrations/008_manual.sql"]
    )

    assert manual == ["008_manual.sql"]
    (migrations / "009_missing.sql").write_text("select 1;\n", encoding="utf-8")
    with pytest.raises(release_agent.ReleaseError, match="eligibility is missing"):
        release_agent._changed_manual_migrations(
            tmp_path, ["service-bursawatch-control/migrations/009_missing.sql"]
        )


@pytest.mark.parametrize(
    "verification",
    [
        "market-news-no-post",
        "phintraco-no-post",
        "kelas-no-post",
        "swing-board-no-post",
        "x-no-post",
        "instagram-no-post",
        "whatsapp-no-post",
    ],
)
def test_no_post_verifications_use_an_isolated_path_and_disable_control_plane_writes(
    tmp_path: Path, verification: str
):
    specification = release_agent._no_post_specification(verification, tmp_path)
    try:
        assert specification.temporary_path.is_relative_to(tmp_path)
        assert specification.environment["BURSAWATCH_RELEASE_NO_POST_TEMP"] == str(specification.temporary_path)
        assert specification.command[0].startswith(str(Path.home() / ".hermes/scripts"))
        control_plane_values = [
            value
            for key, value in specification.environment.items()
            if key.endswith("_CONTROL_PLANE_URL")
        ]
        assert "" in control_plane_values
    finally:
        shutil.rmtree(specification.temporary_path, ignore_errors=True)


def test_release_store_writes_a_sanitized_atomic_state_and_record(tmp_path: Path):
    store = release_agent.ReleaseStore(tmp_path)
    state = store.read_state()
    state["last_success_sha"] = "a" * 40
    store.write_state(state)
    store.record("a" * 40, "blocked", reason="verification failed")
    store.record("a" * 40, "released", units=["cron-x-account-watch"])

    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["last_success_sha"] == "a" * 40
    record = json.loads((tmp_path / "records" / f"{'a' * 40}.json").read_text(encoding="utf-8"))
    assert record["status"] == "released"
    assert [event["status"] for event in record["history"]] == ["blocked", "released"]
    assert (tmp_path / "state.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "records" / f"{'a' * 40}.json").stat().st_mode & 0o777 == 0o600


def test_control_plane_health_waits_for_post_restart_readiness(monkeypatch):
    results: list[object] = [
        release_agent.DeploymentError("control-plane health request failed"),
        {"status": "starting"},
        {"status": "ok"},
    ]
    calls = []

    def read_health(url: str, *, timeout: float) -> object:
        calls.append((url, timeout))
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(release_agent, "_read_json_url", read_health)
    monkeypatch.setattr(release_agent.time, "sleep", lambda _: None)

    release_agent._wait_for_control_plane_health(timeout=3)

    assert len(calls) == 3
    assert all(url == "http://127.0.0.1:9120/healthz" for url, _ in calls)


def test_systemd_unit_keeps_static_agent_code_and_scoped_restart_boundary():
    service = (ROOT / "deployment/systemd/bursawatch-release-agent.service").read_text(encoding="utf-8")
    timer = (ROOT / "deployment/systemd/bursawatch-release-agent.timer").read_text(encoding="utf-8")
    sudoers = (ROOT / "deployment/sudoers.d/bursawatch-release-agent").read_text(encoding="utf-8")

    assert "ExecStart=/home/praya/.local/lib/bursawatch-release/bursawatch-release-agent.sh --once" in service
    assert "EnvironmentFile=/home/praya/.hermes/bursawatch-release-agent.env" in service
    assert "NoNewPrivileges=true" not in service
    assert "OnUnitActiveSec=1m" in timer
    assert "/usr/bin/systemctl restart bursawatch-control-plane.service" in sudoers
    assert "NOPASSWD" in sudoers


def test_bootstrap_script_requires_apply_and_has_valid_shell_syntax():
    script = ROOT / "deployment/bootstrap-release-agent.sh"
    source = script.read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(script)], check=True)
    assert '"${1:-}" != "--apply"' in source
    assert "bursawatch-release-agent.env" in source
    assert 'state_root="$HOME/.local/share/bursawatch-release"' in source
    assert 'install -d -m 0700 "$agent_dir" "$state_root"' in source
    assert "systemctl enable --now bursawatch-release-agent.timer" in source
