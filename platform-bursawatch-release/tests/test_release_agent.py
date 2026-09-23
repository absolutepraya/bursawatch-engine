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


def make_settings(tmp_path: Path, **overrides: object) -> release_agent.Settings:
    values: dict[str, object] = {
        "repository": "owner/repository",
        "token": "read-token",
        "state_root": tmp_path / "state",
        "branch": "main",
        "runtime_home": tmp_path / "runtime",
        "control_plane_runtime": tmp_path / "control-plane",
        "control_plane_env": tmp_path / "control-plane.env",
        "heartbeat_env": tmp_path / "heartbeat.env",
        "heartbeat_channel_id": "123",
        "github_api_url": "https://api.github.com",
        "timeout_seconds": 1,
    }
    values.update(overrides)
    return release_agent.Settings(**values)


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


@pytest.mark.parametrize(
    ("path", "expected_unit"),
    [
        ("DEPLOYMENT.md", "repository-metadata"),
        (".github/workflows/web.yml", "repository-metadata"),
        ("web-config/src/app/page.tsx", "web-applications"),
        ("web-landing/src/app/page.tsx", "web-applications"),
    ],
)
def test_web_migration_paths_require_no_vps_deployment(path: str, expected_unit: str):
    units = manifest().matching_units([path])

    assert [(unit.identifier, unit.handler) for unit in units] == [(expected_unit, "metadata")]


def test_manifest_marks_host_bound_release_assets_manual():
    for path in (
        "platform-bursawatch-release/deployment/systemd/bursawatch-release-agent.service",
        "platform-bursawatch-release/release-manifest.json",
    ):
        units = manifest().matching_units([path])

        assert [(unit.identifier, unit.handler) for unit in units] == [
            ("manual-release-agent-bootstrap", "manual"),
        ]


def test_whatsapp_runtime_manifest_includes_archive_operator_wrapper():
    units = manifest().matching_units(["cron-wa-channel-watch/bin/bursawatch-wa-channel-archive.sh"])

    whatsapp = next(unit for unit in units if unit.identifier == "cron-wa-channel-watch")
    assert ("bursawatch-wa-channel-archive.sh", "bursawatch-wa-channel-archive.sh") in whatsapp.wrappers
    assert ("bursawatch-wa-channel-backfill.sh", "bursawatch-wa-channel-backfill.sh") in whatsapp.wrappers


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


def test_explicit_manual_release_applies_reviewed_manual_migrations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    sha = "b" * 40
    checkout = tmp_path / "checkout"
    manifest_path = checkout / "platform-bursawatch-release"
    migration_path = checkout / "service-bursawatch-control/migrations"
    manifest_path.mkdir(parents=True)
    migration_path.mkdir(parents=True)
    (manifest_path / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": [
                    {
                        "id": "control-plane-metadata",
                        "handler": "metadata",
                        "paths": ["service-bursawatch-control/migrations/**"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (migration_path / "legacy-release-eligibility.json").write_text(
        json.dumps({"version": 1, "migrations": {}}), encoding="utf-8"
    )
    (migration_path / "009_manual.sql").write_text(
        "-- bursawatch-release: manual\nselect 1;\n", encoding="utf-8"
    )

    class FakeGitHub:
        def __init__(self, settings: release_agent.Settings) -> None:
            del settings

        def current_main_sha(self) -> str:
            return sha

        def has_successful_ci(self, candidate: str) -> bool:
            return candidate == sha

    class FakeMirror:
        def __init__(self, settings: release_agent.Settings) -> None:
            del settings

        def materialize(self, candidate: str) -> Path:
            assert candidate == sha
            return checkout

        def changed_paths(self, worktree: Path, base_sha: str | None, candidate: str) -> list[str]:
            assert worktree == checkout
            assert base_sha is None
            assert candidate == sha
            return ["service-bursawatch-control/migrations/009_manual.sql"]

    monkeypatch.setattr(release_agent, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(release_agent, "GitMirror", FakeMirror)
    monkeypatch.setattr(release_agent, "_send_heartbeat", lambda settings, message: None)
    settings = make_settings(tmp_path, token="token")

    assert release_agent.release_once(settings) == "manual-required"
    assert release_agent.release_once(settings, allow_manual=True) == "released"
    state = json.loads((settings.state_root / "state.json").read_text(encoding="utf-8"))
    assert state["last_success_sha"] == sha
    assert state["blocked"] is None
    record = json.loads((settings.state_root / "records" / f"{sha}.json").read_text(encoding="utf-8"))
    assert record["status"] == "released"
    assert record["manual_migrations"] == ["009_manual.sql"]


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
        "stockbit-snips-no-post",
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
        if control_plane_values:
            assert "" in control_plane_values
        if verification == "stockbit-snips-no-post":
            assert specification.environment["STOCKBIT_SNIPS_NO_POST"] == "1"
            assert specification.environment["STOCKBIT_SNIPS_STATE_PATH"] == str(
                specification.temporary_path / "state.json"
            )
            assert specification.command == (
                str(Path.home() / ".hermes/scripts/bursawatch-stockbit-snips.sh"),
            )
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


def test_run_command_preserves_sanitized_failure_diagnostics():
    with pytest.raises(release_agent.CommandFailure) as raised:
        release_agent._run_command(
            (
                sys.executable,
                "-c",
                "import sys; print('token=secret-value'); print('password: secret-value', file=sys.stderr); sys.exit(2)",
            )
        )

    failure = raised.value
    assert failure.returncode == 2
    assert failure.signal_number is None
    assert failure.stdout == "token=<redacted>\n"
    assert failure.stderr == "password: <redacted>\n"


def test_run_command_records_signal_detail():
    with pytest.raises(release_agent.CommandFailure) as raised:
        release_agent._run_command(
            (
                sys.executable,
                "-c",
                "import os, signal; os.kill(os.getpid(), signal.SIGINT)",
            )
        )

    failure = raised.value
    assert failure.returncode == -2
    assert failure.signal_number == 2
    assert failure.signal_name == "SIGINT"


def test_no_post_failure_keeps_verification_metadata(monkeypatch, tmp_path: Path):
    def fail(command, **_kwargs):
        raise release_agent.CommandFailure(
            command,
            -2,
            stdout="drain started\n",
            stderr="token=secret-value\n",
        )

    monkeypatch.setattr(release_agent, "_run_command", fail)
    deployer = release_agent.ReleaseDeployer(
        settings=make_settings(tmp_path),
        release_sha="a" * 40,
        checkout=tmp_path / "checkout",
    )

    with pytest.raises(release_agent.CommandFailure) as raised:
        deployer._run_verification("swing-board-no-post")

    failure = raised.value
    assert failure.details["verification"] == "swing-board-no-post"
    assert failure.details["temporary_path"]
    assert failure.stderr == "token=<redacted>\n"
    assert not Path(failure.details["temporary_path"]).exists()


def test_blocked_record_keeps_sanitized_command_diagnostics(tmp_path: Path):
    store = release_agent.ReleaseStore(tmp_path / "state")
    state = store.read_state()
    failure = release_agent.CommandFailure(
        ("/home/praya/.hermes/scripts/bursawatch-dc-swing-board.sh", "drain"),
        -2,
        stdout="{\"pending\":0}\n",
        stderr="authorization=secret-value\n",
    )
    sha = "d" * 40

    release_agent._block_release(store, state, sha, str(failure), **failure.details)

    record = json.loads((tmp_path / "state" / "records" / f"{sha}.json").read_text(encoding="utf-8"))
    assert record["status"] == "blocked"
    assert record["returncode"] == -2
    assert record["signal_name"] == "SIGINT"
    assert record["stderr"] == "authorization=<redacted>\n"


def test_release_status_posts_with_the_scoped_status_token(monkeypatch, tmp_path: Path):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, *, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(release_agent, "urlopen", fake_urlopen)
    client = release_agent.GitHubClient(make_settings(tmp_path, status_token="status-token"))
    sha = "b" * 40

    assert client.publish_release_status(
        sha,
        state="failure",
        description="blocked by verification",
        target_url="https://github.example/release/b",
    ) is True

    request, timeout = requests[0]
    assert request.full_url == "https://api.github.com/repos/owner/repository/statuses/" + sha
    assert request.get_method() == "POST"
    assert request.headers["Authorization"] == "Bearer status-token"
    assert timeout == 1
    assert json.loads(request.data) == {
        "state": "failure",
        "target_url": "https://github.example/release/b",
        "description": "blocked by verification",
        "context": "bursawatch/release",
    }


def test_waiting_for_ci_publishes_a_pending_release_status(monkeypatch, tmp_path: Path):
    sha = "c" * 40
    statuses = []

    class FakeGitHub:
        def __init__(self, _settings):
            pass

        def current_main_sha(self):
            return sha

        def has_successful_ci(self, candidate):
            assert candidate == sha
            return False

        def publish_release_status(self, candidate, **details):
            statuses.append((candidate, details))

    monkeypatch.setattr(release_agent, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(release_agent, "_send_heartbeat", lambda settings, message: None)

    assert release_agent.release_once(make_settings(tmp_path, status_token="status-token")) == "waiting-for-ci"
    assert statuses == [
        (
            sha,
            {
                "state": "pending",
                "description": "waiting-for-ci",
                "target_url": None,
            },
        )
    ]


def test_existing_blocked_sha_publishes_its_status_once(monkeypatch, tmp_path: Path):
    sha = "e" * 40
    statuses = []

    class FakeGitHub:
        def __init__(self, _settings):
            pass

        def current_main_sha(self):
            return sha

        def publish_release_status(self, candidate, **details):
            statuses.append((candidate, details))
            return True

    settings = make_settings(tmp_path, status_token="status-token")
    store = release_agent.ReleaseStore(settings.state_root)
    state = store.read_state()
    state["blocked"] = {"sha": sha, "reason": "verification failed"}
    store.write_state(state)
    monkeypatch.setattr(release_agent, "GitHubClient", FakeGitHub)

    assert release_agent.release_once(settings) == "blocked"
    assert release_agent.release_once(settings) == "blocked"
    assert statuses == [
        (
            sha,
            {
                "state": "failure",
                "description": "verification failed",
                "target_url": None,
            },
        )
    ]
    assert release_agent.ReleaseStore(settings.state_root).read_state()["github_status"] == {
        "sha": sha,
        "state": "failure",
        "description": "verification failed",
    }


def test_main_returns_nonzero_for_a_blocked_release(monkeypatch, capsys):
    monkeypatch.setenv("BURSAWATCH_RELEASE_GITHUB_TOKEN", "read-token")
    monkeypatch.setattr(
        release_agent,
        "release_once",
        lambda settings, *, allow_manual=False: "blocked",
    )

    assert release_agent.main(["--once"]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "blocked"}


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
