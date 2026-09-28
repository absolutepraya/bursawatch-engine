from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parent
sys.path.insert(0, str(REPOSITORY_ROOT / "lib-bursawatch-discord-delivery" / "bin"))
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
        "delivery_owner_url": "http://127.0.0.1:9140",
        "delivery_client_token_file": tmp_path / "delivery-client-token",
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


def test_sync_file_installs_executable_wrappers_with_world_execute_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source.sh"
    target = tmp_path / "runtime" / "wrapper.sh"
    source.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    monkeypatch.setattr(release_agent, "_ensure_safe_directory", lambda path: None)

    release_agent._sync_file(source, target, executable=True)

    assert target.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"
    assert target.stat().st_mode & 0o777 == 0o755


def test_manifest_orders_dependencies_before_the_x_runtime_unit():
    units = manifest().matching_units(["cron-x-account-watch/bin/scan.py"])

    assert [unit.identifier for unit in units] == [
        "lib-bursawatch-control",
        "lib-bursawatch-discord-delivery",
        "lib-swing-format",
        "cron-dc-swing-board",
        "cron-x-account-watch",
    ]


def test_telegram_source_ingest_resolves_runtime_dependencies_before_pilot():
    units = manifest().matching_units(["cron-tg-source-ingest/bin/runner.py"])
    identifiers = [unit.identifier for unit in units]

    assert identifiers == [
        "lib-bursawatch-control",
        "lib-bursawatch-discord-delivery",
        "lib-bursawatch-pipeline-runtime",
        "lib-bursawatch-source-ingest-pilot",
        "lib-bursawatch-source-media",
        "lib-telegram-resilience",
        "cron-tg-market-news",
        "lib-swing-format",
        "cron-dc-swing-board",
        "cron-tg-phintraco-swing",
        "cron-tg-kelas-investasi-gtw",
        "cron-tg-source-ingest-pilot",
    ]
    assert all(unit.handler == "runtime" for unit in units)
    runtime = units[-1]
    assert runtime.runtime == "bursawatch-tg-source-ingest"
    assert runtime.verification == "telegram-source-ingest-no-post"


def test_x_source_ingest_resolves_as_an_installable_runtime():
    units = manifest().matching_units(["cron-x-source-ingest/bin/runner.py"])
    by_id = {unit.identifier: unit for unit in units}
    runtime = by_id["cron-x-source-ingest-pilot"]

    assert runtime.handler == "runtime"
    assert runtime.runtime == "bursawatch-x-source-ingest"
    assert runtime.verification == "x-source-ingest-no-post"
    assert ("bursawatch-x-source-ingest.sh", "bursawatch-x-source-ingest.sh") in runtime.wrappers
    assert {
        "lib-bursawatch-control",
        "lib-bursawatch-discord-delivery",
        "lib-bursawatch-pipeline-runtime",
        "lib-bursawatch-source-ingest-pilot",
        "lib-bursawatch-source-media",
        "cron-x-account-watch",
    } <= set(by_id)


def test_instagram_source_ingest_remains_metadata_only():
    result = manifest()
    units = result.matching_units(["cron-ig-source-ingest/bin/runner.py"])
    assert [unit.identifier for unit in units] == ["cron-ig-source-ingest-pilot"]
    assert [unit.handler for unit in units] == ["metadata"]


def test_whatsapp_source_ingest_resolves_as_an_installable_runtime():
    units = manifest().matching_units(["cron-wa-source-ingest/bin/runner.py"])
    by_id = {unit.identifier: unit for unit in units}
    runtime = by_id["cron-wa-source-ingest-pilot"]

    assert runtime.handler == "runtime"
    assert runtime.runtime == "bursawatch-wa-source-ingest"
    assert runtime.verification == "whatsapp-source-ingest-no-post"
    assert ("bursawatch-wa-source-ingest.sh", "bursawatch-wa-source-ingest.sh") in runtime.wrappers
    assert {
        "lib-bursawatch-control",
        "lib-bursawatch-discord-delivery",
        "lib-bursawatch-pipeline-runtime",
        "lib-bursawatch-source-ingest-pilot",
        "lib-bursawatch-source-media",
        "cron-wa-channel-watch",
    } <= set(by_id)


def test_rss_source_ingest_resolves_as_an_installable_runtime():
    units = manifest().matching_units(["cron-rss-source-ingest/bin/runner.py"])
    by_id = {unit.identifier: unit for unit in units}
    runtime = by_id["cron-rss-source-ingest-pilot"]

    assert runtime.handler == "runtime"
    assert runtime.runtime == "bursawatch-rss-source-ingest"
    assert runtime.verification == "rss-source-ingest-no-post"
    assert ("bursawatch-rss-source-ingest.sh", "bursawatch-rss-source-ingest.sh") in runtime.wrappers
    assert {
        "lib-bursawatch-control",
        "lib-bursawatch-discord-delivery",
        "lib-bursawatch-pipeline-runtime",
        "lib-bursawatch-source-ingest-pilot",
        "cron-stockbit-snips",
    } <= set(by_id)


def test_telegram_source_ingest_no_post_is_synthetic_and_has_no_secret_environment(tmp_path: Path):
    specification = release_agent._no_post_specification("telegram-source-ingest-no-post", tmp_path)

    assert specification.command == (str(Path.home() / ".hermes/scripts/bursawatch-tg-source-ingest.sh"),)
    assert specification.environment["BURSAWATCH_RELEASE_NO_POST"] == "1"
    assert specification.environment["BURSAWATCH_RELEASE_NO_POST_TEMP"] == str(specification.temporary_path)
    assert specification.environment["HOME"] == str(Path.home())
    assert set(specification.environment) == {
        "PATH", "HOME", "TZ", "LANG", "BURSAWATCH_RELEASE_NO_POST",
        "BURSAWATCH_RELEASE_NO_POST_TEMP",
    }
    assert "POLYCOP_SESSION_STRING" not in specification.environment
    assert "TELEGRAM_API_HASH" not in specification.environment
    assert "BURSAWATCH_TG_SOURCE_CONTROL_PLANE_TOKEN_FILE" not in specification.environment


def test_telegram_source_ingest_verification_rejects_non_synthetic_success():
    with pytest.raises(release_agent.DeploymentError, match="synthetic verification"):
        release_agent._verify_telegram_source_ingest_no_post('{"outcome":"ok"}')

    release_agent._verify_telegram_source_ingest_no_post(
        '{"outcome":"synthetic-ok","network":false,"secrets":false,"writes":false,"events":1,"content_hash":"' + "a" * 64 + '"}'
    )


def test_x_source_ingest_no_post_is_synthetic_and_has_no_secret_environment(tmp_path: Path):
    specification = release_agent._no_post_specification("x-source-ingest-no-post", tmp_path)

    assert specification.command == (str(Path.home() / ".hermes/scripts/bursawatch-x-source-ingest.sh"),)
    assert specification.environment["BURSAWATCH_RELEASE_NO_POST"] == "1"
    assert specification.environment["BURSAWATCH_RELEASE_NO_POST_TEMP"] == str(specification.temporary_path)
    assert specification.environment["HOME"] == str(Path.home())
    assert set(specification.environment) == {
        "PATH", "HOME", "TZ", "LANG", "BURSAWATCH_RELEASE_NO_POST",
        "BURSAWATCH_RELEASE_NO_POST_TEMP",
    }


def test_x_source_ingest_verification_rejects_non_synthetic_success():
    with pytest.raises(release_agent.DeploymentError, match="X source-ingest synthetic verification"):
        release_agent._verify_x_source_ingest_no_post('{"outcome":"ok"}')

    release_agent._verify_x_source_ingest_no_post(
        '{"outcome":"synthetic-ok","network":false,"secrets":false,"writes":false,"events":1,"content_hash":"' + "b" * 64 + '"}'
    )


def test_rss_source_ingest_no_post_is_synthetic_and_has_no_secret_environment(tmp_path: Path):
    specification = release_agent._no_post_specification("rss-source-ingest-no-post", tmp_path)

    assert specification.command == (str(Path.home() / ".hermes/scripts/bursawatch-rss-source-ingest.sh"),)
    assert specification.environment == {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "TZ": "Asia/Jakarta",
        "LANG": "C.UTF-8",
        "BURSAWATCH_RELEASE_NO_POST": "1",
        "BURSAWATCH_RELEASE_NO_POST_TEMP": str(specification.temporary_path),
    }
    assert specification.temporary_path.is_relative_to(tmp_path)


def test_rss_source_ingest_verification_requires_synthetic_isolation():
    with pytest.raises(release_agent.DeploymentError, match="RSS source-ingest synthetic verification"):
        release_agent._verify_synthetic_source_ingest_no_post('{"outcome":"ok"}', "RSS")

    release_agent._verify_synthetic_source_ingest_no_post(
        '{"outcome":"synthetic-ok","network":false,"secrets":false,"writes":false,"events":1,"content_hash":"' + "c" * 64 + '"}',
        "RSS",
    )


def test_whatsapp_source_ingest_no_post_is_synthetic_and_has_no_secret_environment(tmp_path: Path):
    specification = release_agent._no_post_specification("whatsapp-source-ingest-no-post", tmp_path)

    assert specification.command == (str(Path.home() / ".hermes/scripts/bursawatch-wa-source-ingest.sh"),)
    assert specification.environment == {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path.home()),
        "TZ": "Asia/Jakarta",
        "LANG": "C.UTF-8",
        "BURSAWATCH_RELEASE_NO_POST": "1",
        "BURSAWATCH_RELEASE_NO_POST_TEMP": str(specification.temporary_path),
    }
    with pytest.raises(release_agent.DeploymentError, match="WhatsApp source-ingest synthetic verification"):
        release_agent._verify_synthetic_source_ingest_no_post('{"outcome":"ok"}', "WhatsApp")

    release_agent._verify_synthetic_source_ingest_no_post(
        '{"outcome":"synthetic-ok","network":false,"secrets":false,"writes":false,"events":1,"content_hash":"' + "d" * 64 + '"}',
        "WhatsApp",
    )


def test_rss_source_ingest_release_dispatch_rejects_non_synthetic_output(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(release_agent, "_run_command", lambda *_args, **_kwargs: '{"outcome":"ok"}')
    deployer = release_agent.ReleaseDeployer(
        settings=make_settings(tmp_path), release_sha="a" * 40, checkout=tmp_path / "checkout"
    )

    with pytest.raises(release_agent.DeploymentError, match="RSS source-ingest synthetic verification"):
        deployer._run_verification("rss-source-ingest-no-post")


def test_telegram_wrapper_runs_synthetic_check_without_reading_environment_files(tmp_path: Path):
    home = tmp_path / "home"
    skills = home / ".agents/skills"
    skills.mkdir(parents=True)
    for package, runtime in (
        ("cron-tg-source-ingest", "bursawatch-tg-source-ingest"),
        ("lib-bursawatch-control", "lib-bursawatch-control"),
        ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"),
        ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
        ("lib-bursawatch-source-media", "lib-bursawatch-source-media"),
        ("lib-bursawatch-discord-delivery", "lib-bursawatch-discord-delivery"),
        ("lib-telegram-resilience", "lib-telegram-resilience"),
    ):
        (skills / runtime).symlink_to(REPOSITORY_ROOT / package, target_is_directory=True)
    python = home / ".local/share/uv/tools/yahoo-finance-mcp/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    env_path = home / ".hermes/.env"
    env_path.mkdir(parents=True)  # Opening it as a file would fail if no-post reads it.
    temporary = tmp_path / "release-agent-temporary"
    temporary.mkdir()
    wrapper = REPOSITORY_ROOT / "cron-tg-source-ingest/bin/bursawatch-tg-source-ingest.sh"
    environment = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "BURSAWATCH_RELEASE_NO_POST": "1",
        "BURSAWATCH_RELEASE_NO_POST_TEMP": str(temporary),
        "POLYCOP_SESSION_STRING": "must-not-be-passed",
        "TELEGRAM_API_HASH": "must-not-be-passed",
    }

    result = subprocess.run([str(wrapper)], env=environment, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "must-not-be-passed" not in result.stdout + result.stderr
    release_agent._verify_telegram_source_ingest_no_post(result.stdout)
    assert [path.name for path in temporary.iterdir()] == ["telegram-source-ingest.log"]


def test_x_wrapper_runs_synthetic_check_without_reading_environment_files(tmp_path: Path):
    home = tmp_path / "home"
    skills = home / ".agents/skills"
    skills.mkdir(parents=True)
    for package, runtime in (
        ("cron-x-source-ingest", "bursawatch-x-source-ingest"),
        ("cron-x-account-watch", "bursawatch-x-account-watch"),
        ("lib-bursawatch-control", "lib-bursawatch-control"),
        ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"),
        ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
        ("lib-bursawatch-source-media", "lib-bursawatch-source-media"),
        ("lib-bursawatch-discord-delivery", "lib-bursawatch-discord-delivery"),
    ):
        destination = skills / runtime
        source = REPOSITORY_ROOT / package
        if package == "cron-x-source-ingest":
            shutil.copytree(source, destination)
        else:
            destination.symlink_to(source, target_is_directory=True)
    python = home / ".local/share/uv/tools/yahoo-finance-mcp/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    env_path = home / ".hermes/.env"
    env_path.mkdir(parents=True)
    temporary = tmp_path / "release-agent-temporary"
    temporary.mkdir()
    wrapper = REPOSITORY_ROOT / "cron-x-source-ingest/bin/bursawatch-x-source-ingest.sh"
    environment = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "BURSAWATCH_RELEASE_NO_POST": "1",
        "BURSAWATCH_RELEASE_NO_POST_TEMP": str(temporary),
        "X_POST_WATCH_CONTROL_PLANE_TOKEN": "must-not-be-passed",
        "BURSAWATCH_X_SOURCE_CONTROL_PLANE_TOKEN_FILE": "must-not-be-passed",
    }

    result = subprocess.run([str(wrapper)], env=environment, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "must-not-be-passed" not in result.stdout + result.stderr
    release_agent._verify_x_source_ingest_no_post(result.stdout)
    assert [path.name for path in temporary.iterdir()] == ["x-source-ingest.log"]


def test_rss_wrapper_runs_synthetic_check_without_reading_environment_files(tmp_path: Path):
    home = tmp_path / "home"
    skills = home / ".agents/skills"
    skills.mkdir(parents=True)
    for package, runtime in (
        ("cron-rss-source-ingest", "bursawatch-rss-source-ingest"),
        ("cron-stockbit-snips", "bursawatch-stockbit-snips"),
        ("lib-bursawatch-control", "lib-bursawatch-control"),
        ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"),
        ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
        ("lib-bursawatch-discord-delivery", "lib-bursawatch-discord-delivery"),
    ):
        (skills / runtime).symlink_to(REPOSITORY_ROOT / package, target_is_directory=True)
    python = home / ".local/share/uv/tools/yahoo-finance-mcp/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    (home / ".hermes/.env").mkdir(parents=True)
    temporary = tmp_path / "release-agent-temporary"
    temporary.mkdir()
    wrapper = REPOSITORY_ROOT / "cron-rss-source-ingest/bin/bursawatch-rss-source-ingest.sh"
    environment = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "BURSAWATCH_RELEASE_NO_POST": "1",
        "BURSAWATCH_RELEASE_NO_POST_TEMP": str(temporary),
        "BURSAWATCH_RSS_SOURCE_CONTROL_PLANE_TOKEN_FILE": "must-not-be-passed",
        "STOCKBIT_SNIPS_CONTROL_PLANE_TOKEN": "must-not-be-passed",
        "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE": "must-not-be-passed",
    }

    result = subprocess.run([str(wrapper)], env=environment, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "must-not-be-passed" not in result.stdout + result.stderr
    release_agent._verify_synthetic_source_ingest_no_post(result.stdout, "RSS")
    assert [path.name for path in temporary.iterdir()] == ["rss-source-ingest.log"]


def test_whatsapp_wrapper_runs_synthetic_check_without_reading_environment_files(tmp_path: Path):
    home = tmp_path / "home"
    skills = home / ".agents/skills"
    skills.mkdir(parents=True)
    for package, runtime in (
        ("cron-wa-source-ingest", "bursawatch-wa-source-ingest"),
        ("cron-wa-channel-watch", "bursawatch-wa-channel-watch"),
        ("lib-bursawatch-control", "lib-bursawatch-control"),
        ("lib-bursawatch-pipeline-runtime", "lib-bursawatch-pipeline-runtime"),
        ("lib-bursawatch-source-ingest", "lib-bursawatch-source-ingest-pilot"),
        ("lib-bursawatch-source-media", "lib-bursawatch-source-media"),
        ("lib-bursawatch-discord-delivery", "lib-bursawatch-discord-delivery"),
    ):
        destination = skills / runtime
        source = REPOSITORY_ROOT / package
        if package == "cron-wa-source-ingest":
            shutil.copytree(source, destination)
        else:
            destination.symlink_to(source, target_is_directory=True)
    python = home / ".local/share/uv/tools/yahoo-finance-mcp/bin/python"
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    (home / ".hermes/.env").mkdir(parents=True)
    temporary = tmp_path / "release-agent-temporary"
    temporary.mkdir()
    wrapper = REPOSITORY_ROOT / "cron-wa-source-ingest/bin/bursawatch-wa-source-ingest.sh"
    environment = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "BURSAWATCH_RELEASE_NO_POST": "1",
        "BURSAWATCH_RELEASE_NO_POST_TEMP": str(temporary),
        "BURSAWATCH_WA_SOURCE_CONTROL_PLANE_TOKEN_FILE": "must-not-be-passed",
        "WHATSAPP_CHANNEL_WATCH_CONTROL_PLANE_TOKEN": "must-not-be-passed",
        "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE": "must-not-be-passed",
    }

    result = subprocess.run([str(wrapper)], env=environment, text=True, capture_output=True, check=False)

    assert result.returncode == 0, result.stderr
    assert "must-not-be-passed" not in result.stdout + result.stderr
    release_agent._verify_synthetic_source_ingest_no_post(result.stdout, "WhatsApp")
    assert [path.name for path in temporary.iterdir()] == ["whatsapp-source-ingest.log"]


def test_delivery_library_precedes_every_migrated_discord_runtime():
    sources = (
        "cron-tg-market-news/bin/scan.py",
        "cron-tg-phintraco-swing/bin/scan.py",
        "cron-tg-kelas-investasi-gtw/bin/scan.py",
        "cron-dc-swing-board/bin/board.py",
        "cron-x-account-watch/bin/scan.py",
        "cron-ig-account-watch/bin/scan.py",
        "cron-wa-channel-watch/bin/scan.py",
        "cron-wa-source-ingest/bin/runner.py",
        "cron-stockbit-snips/bin/scan.py",
        "cron-rss-source-ingest/bin/runner.py",
    )
    for source in sources:
        package = source.split("/", 1)[0]
        units = manifest().matching_units([source])
        identifiers = [unit.identifier for unit in units]
        runtime_id = {
            "cron-rss-source-ingest": "cron-rss-source-ingest-pilot",
            "cron-wa-source-ingest": "cron-wa-source-ingest-pilot",
        }.get(package, package)
        assert runtime_id in identifiers
        assert identifiers.index("lib-bursawatch-discord-delivery") < identifiers.index(runtime_id)


def test_discord_delivery_service_remains_a_manual_unit():
    units = manifest().matching_units(["service-bursawatch-discord-delivery/bin/serve.py"])
    assert [(unit.identifier, unit.handler) for unit in units] == [
        ("manual-discord-delivery-owner", "manual"),
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


def test_phintraco_runtime_requirements_are_metadata_not_runtime_deployment():
    units = manifest().matching_units(["cron-tg-phintraco-swing/requirements.txt"])

    assert [(unit.identifier, unit.handler) for unit in units] == [
        ("cron-tg-phintraco-swing-metadata", "metadata"),
    ]


def test_whatsapp_runtime_manifest_includes_archive_operator_wrapper():
    units = manifest().matching_units(["cron-wa-channel-watch/bin/bursawatch-wa-channel-archive.sh"])

    whatsapp = next(unit for unit in units if unit.identifier == "cron-wa-channel-watch")
    assert ("bursawatch-wa-channel-archive.sh", "bursawatch-wa-channel-archive.sh") in whatsapp.wrappers
    assert ("bursawatch-wa-channel-backfill.sh", "bursawatch-wa-channel-backfill.sh") in whatsapp.wrappers


def test_manifest_maps_market_news_watchdog_wrapper_to_its_vps_name():
    unit = next(unit for unit in manifest().units if unit.identifier == "cron-tg-market-news")

    assert ("watchdog-wrapper.sh", "bursawatch-tg-market-news-watchdog.sh") in unit.wrappers


def test_release_heartbeats_use_delivery_owner_with_stable_keys_and_existing_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    settings = make_settings(tmp_path)
    token_file = tmp_path / "delivery-client-token"
    clients = []
    submissions = []

    class FakeDeliveryClient:
        def __init__(self, base_url, token_path, *, timeout_seconds):
            clients.append((base_url, token_path, timeout_seconds))

        def submit(self, operation):
            submissions.append(operation)

    monkeypatch.setattr(release_agent, "DeliveryClient", FakeDeliveryClient, raising=False)
    monkeypatch.setattr(
        release_agent,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("release heartbeat attempted a direct HTTP request"),
    )

    success = "🫀 bursawatch-release · 12:34 WIB · sha=abcdef01 units=2"
    failure = "❌ bursawatch-release · 12:35 WIB · blocked manual=manual-release-agent-bootstrap"
    for content in (success, failure, success):
        release_agent._send_heartbeat(settings, content)

    assert clients == [
        ("http://127.0.0.1:9140", token_file, settings.timeout_seconds),
        ("http://127.0.0.1:9140", token_file, settings.timeout_seconds),
        ("http://127.0.0.1:9140", token_file, settings.timeout_seconds),
    ]
    assert [operation.kind for operation in submissions] == [
        "channel_message_create",
        "channel_message_create",
        "channel_message_create",
    ]
    assert [operation.key for operation in submissions] == [
        submissions[0].key,
        submissions[1].key,
        submissions[0].key,
    ]
    assert submissions[0].key != submissions[1].key
    assert all(operation.ordering_key == "channel:123" for operation in submissions)
    assert all(operation.target == {"channel_id": "123"} for operation in submissions)
    assert [operation.payload for operation in submissions] == [
        {"content": success, "allowed_mentions": {"parse": []}},
        {"content": failure, "allowed_mentions": {"parse": []}},
        {"content": success, "allowed_mentions": {"parse": []}},
    ]


def test_release_heartbeat_delivery_failure_is_best_effort_and_does_not_change_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    settings = make_settings(tmp_path)
    sha = "b" * 40
    heartbeat_attempts = []

    class FakeGitHub:
        def __init__(self, configured_settings):
            assert configured_settings is settings

        def current_main_sha(self):
            return sha

        def has_successful_ci(self, candidate):
            return candidate == sha

    class FakeMirror:
        def __init__(self, configured_settings):
            assert configured_settings is settings

        def materialize(self, candidate):
            assert candidate == sha
            return REPOSITORY_ROOT

        def changed_paths(self, worktree, base_sha, candidate):
            assert worktree == REPOSITORY_ROOT
            assert base_sha is None
            assert candidate == sha
            return []

    class UnavailableDeliveryClient:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, operation):
            heartbeat_attempts.append(operation)
            raise OSError("delivery owner unavailable")

    monkeypatch.setattr(release_agent, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(release_agent, "GitMirror", FakeMirror)
    monkeypatch.setattr(release_agent, "DeliveryClient", UnavailableDeliveryClient, raising=False)

    assert release_agent.release_once(settings) == "released"

    state = json.loads((settings.state_root / "state.json").read_text(encoding="utf-8"))
    record = json.loads((settings.state_root / "records" / f"{sha}.json").read_text(encoding="utf-8"))
    assert state["last_success_sha"] == sha
    assert state["blocked"] is None
    assert record["status"] == "released"
    assert len(heartbeat_attempts) == 1


def test_successfully_released_sha_is_a_silent_noop(monkeypatch, tmp_path: Path):
    sha = "f" * 40
    settings = make_settings(tmp_path)
    store = release_agent.ReleaseStore(settings.state_root)
    state = store.read_state()
    state["last_success_sha"] = sha
    store.write_state(state)
    store.record(sha, "released", units=["cron-tg-source-ingest-pilot"])
    state_before = (settings.state_root / "state.json").read_bytes()
    record_before = (settings.state_root / "records" / f"{sha}.json").read_bytes()
    heartbeat_attempts = []

    class FakeGitHub:
        def __init__(self, _settings):
            pass

        def current_main_sha(self):
            return sha

        def has_successful_ci(self, _candidate):
            pytest.fail("already-released SHA should not recheck CI")

    class NoOpMirror:
        def __init__(self, _settings):
            pytest.fail("already-released SHA should not materialize a worktree")

    monkeypatch.setattr(release_agent, "GitHubClient", FakeGitHub)
    monkeypatch.setattr(release_agent, "GitMirror", NoOpMirror)
    monkeypatch.setattr(
        release_agent,
        "_send_heartbeat",
        lambda *args, **kwargs: heartbeat_attempts.append((args, kwargs)),
    )

    assert release_agent.release_once(settings) == "already-released"

    assert (settings.state_root / "state.json").read_bytes() == state_before
    assert (settings.state_root / "records" / f"{sha}.json").read_bytes() == record_before
    assert heartbeat_attempts == []


def test_release_agent_does_not_read_discord_credentials_or_call_discord_rest():
    source = (ROOT / "bin" / "release_agent.py").read_text(encoding="utf-8")

    assert "discord.com/api" not in source
    assert "DISCORD_BOT_TOKEN" not in source
    assert "def _discord_token" not in source


def test_release_no_post_mode_keeps_wrappers_from_reloading_control_plane_credentials():
    wrappers = [
        REPOSITORY_ROOT / "cron-tg-market-news/bin/bursawatch-tg-market-news.sh",
        REPOSITORY_ROOT / "cron-tg-phintraco-swing/bin/bursawatch-tg-phintraco-swing.sh",
        REPOSITORY_ROOT / "cron-tg-kelas-investasi-gtw/bin/bursawatch-tg-kelas-investasi-gtw.sh",
        REPOSITORY_ROOT / "cron-dc-swing-board/bin/bursawatch-dc-swing-board.sh",
        REPOSITORY_ROOT / "cron-x-account-watch/bin/bursawatch-x-account-watch.sh",
        REPOSITORY_ROOT / "cron-x-source-ingest/bin/bursawatch-x-source-ingest.sh",
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
        "x-source-ingest-no-post",
        "rss-source-ingest-no-post",
        "whatsapp-source-ingest-no-post",
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
            manifest_data = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
            stockbit_unit = next(unit for unit in manifest_data["units"] if unit["id"] == "cron-stockbit-snips")
            assert "lib-bursawatch-control" in stockbit_unit.get("depends_on", [])
            assert specification.environment["STOCKBIT_SNIPS_NO_POST"] == "1"
            assert specification.environment["STOCKBIT_SNIPS_STATE_PATH"] == str(
                specification.temporary_path / "state.json"
            )
            assert specification.command == (
                str(Path.home() / ".hermes/scripts/bursawatch-stockbit-snips.sh"),
            )
            assert "STOCKBIT_SNIPS_CONTROL_PLANE_URL" not in specification.environment
            assert "STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH" not in specification.environment
            assert not any("REPORTER" in key for key in specification.environment if key.startswith("STOCKBIT_SNIPS_"))
    finally:
        shutil.rmtree(specification.temporary_path, ignore_errors=True)


def test_stockbit_no_post_uses_fresh_state_and_clears_inherited_event_spool(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH", "/inherited/forbidden/spool")
    first = release_agent._no_post_specification("stockbit-snips-no-post", tmp_path)
    second = release_agent._no_post_specification("stockbit-snips-no-post", tmp_path)
    try:
        assert first.temporary_path != second.temporary_path
        assert first.environment["STOCKBIT_SNIPS_STATE_PATH"] != second.environment["STOCKBIT_SNIPS_STATE_PATH"]
        assert not Path(first.environment["STOCKBIT_SNIPS_STATE_PATH"]).exists()
        assert not Path(second.environment["STOCKBIT_SNIPS_STATE_PATH"]).exists()
        assert "STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH" not in first.environment
        assert "STOCKBIT_SNIPS_CONTROL_PLANE_SPOOL_PATH" not in second.environment
    finally:
        shutil.rmtree(first.temporary_path, ignore_errors=True)
        shutil.rmtree(second.temporary_path, ignore_errors=True)


def test_stockbit_no_post_rejects_degraded_exit_zero_without_exposing_diagnostics(monkeypatch, tmp_path: Path):
    def degraded(_command, **kwargs):
        assert kwargs["environment"]["STOCKBIT_SNIPS_NO_POST"] == "1"
        return (
            "Stockbit live configuration is unavailable or invalid\n"
            + json.dumps({
                "wakeAgent": False,
                "items": [],
                "stats": {"degraded": True, "errors": ["Stockbit live configuration is unavailable or invalid"]},
            })
            + "\n"
        )

    monkeypatch.setattr(release_agent, "_run_command", degraded)
    deployer = release_agent.ReleaseDeployer(
        settings=make_settings(tmp_path), release_sha="a" * 40, checkout=tmp_path / "checkout"
    )
    with pytest.raises(release_agent.DeploymentError) as raised:
        deployer._run_verification("stockbit-snips-no-post")
    assert "live config" in str(raised.value)
    assert "unavailable or invalid" not in str(raised.value)
    assert not list((tmp_path / "state/no-post/stockbit-snips-no-post").glob("run-*"))


def test_stockbit_no_post_accepts_successful_config_read_with_fresh_state(monkeypatch, tmp_path: Path):
    def successful(_command, **kwargs):
        state_path = Path(kwargs["environment"]["STOCKBIT_SNIPS_STATE_PATH"])
        state_path.write_text(json.dumps({
            "version": 2,
            "articles": {},
            "last_heartbeat": "2026-09-23T12:00:00+07:00",
        }), encoding="utf-8")
        return json.dumps({
            "wakeAgent": False,
            "items": [],
            "stats": {"degraded": False, "errors": []},
        }) + "\n"

    monkeypatch.setattr(release_agent, "_run_command", successful)
    deployer = release_agent.ReleaseDeployer(
        settings=make_settings(tmp_path), release_sha="a" * 40, checkout=tmp_path / "checkout"
    )
    deployer._run_verification("stockbit-snips-no-post")
    assert not list((tmp_path / "state/no-post/stockbit-snips-no-post").glob("run-*"))


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


def test_main_returns_success_for_an_already_released_sha(monkeypatch, capsys):
    monkeypatch.setenv("BURSAWATCH_RELEASE_GITHUB_TOKEN", "read-token")
    monkeypatch.setattr(
        release_agent,
        "release_once",
        lambda settings, *, allow_manual=False: "already-released",
    )

    assert release_agent.main(["--once"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "already-released"}


def test_systemd_unit_keeps_static_agent_code_and_scoped_restart_boundary():
    service = (ROOT / "deployment/systemd/bursawatch-release-agent.service").read_text(encoding="utf-8")
    timer = (ROOT / "deployment/systemd/bursawatch-release-agent.timer").read_text(encoding="utf-8")
    sudoers = (ROOT / "deployment/sudoers.d/bursawatch-release-agent").read_text(encoding="utf-8")

    assert "ExecStart=/home/praya/.local/lib/bursawatch-release/bursawatch-release-agent.sh --once" in service
    assert "EnvironmentFile=/home/praya/.hermes/bursawatch-release-agent.env" in service
    assert "Environment=PYTHONPATH=/home/praya/.agents/skills/lib-bursawatch-discord-delivery/bin" in service
    assert "DISCORD_BOT_TOKEN" not in service
    assert "NoNewPrivileges=true" not in service
    assert "OnUnitActiveSec=1m" in timer
    assert "/usr/bin/systemctl restart bursawatch-control-plane.service" in sudoers
    assert "NOPASSWD" in sudoers


def test_cli_wrapper_exposes_the_shared_discord_client_package():
    wrapper = (ROOT / "bin/bursawatch-release-agent.sh").read_text(encoding="utf-8")

    assert 'export PYTHONPATH="/home/praya/.agents/skills/lib-bursawatch-discord-delivery/bin${PYTHONPATH:+:$PYTHONPATH}"' in wrapper


def test_bootstrap_script_requires_apply_and_has_valid_shell_syntax():
    script = ROOT / "deployment/bootstrap-release-agent.sh"
    source = script.read_text(encoding="utf-8")

    subprocess.run(["bash", "-n", str(script)], check=True)
    assert '"${1:-}" != "--apply"' in source
    assert "bursawatch-release-agent.env" in source
    assert 'state_root="$HOME/.local/share/bursawatch-release"' in source
    assert 'delivery_client_bin="$HOME/.agents/skills/lib-bursawatch-discord-delivery/bin"' in source
    assert 'PYTHONPATH="$release_home/.agents/skills/lib-bursawatch-discord-delivery/bin"' in source
    assert 'delivery_client_token_file="$HOME/.hermes/secrets/bursawatch-discord-delivery-client-token"' in source
    assert '[[ "$(stat -c \'%a\' "$delivery_client_token_file")" == "600" ]]' in source
    assert 'install -d -m 0700 "$agent_dir" "$state_root"' in source
    assert "systemctl enable --now bursawatch-release-agent.timer" in source


def test_release_env_template_uses_only_the_delivery_client_token_for_heartbeat():
    source = (ROOT / "deployment/env.example").read_text(encoding="utf-8")

    assert "BURSAWATCH_DISCORD_DELIVERY_URL=http://127.0.0.1:9140" in source
    assert (
        "BURSAWATCH_DISCORD_DELIVERY_CLIENT_TOKEN_FILE="
        "/home/praya/.hermes/secrets/bursawatch-discord-delivery-client-token"
    ) in source
    assert "BURSAWATCH_RELEASE_HEARTBEAT_ENV" not in source
    assert "DISCORD_BOT_TOKEN" not in source
