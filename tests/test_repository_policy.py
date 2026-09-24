import fnmatch
import json
import re
import subprocess
from pathlib import Path

from scripts.repository_policy import violations_for


ROOT = Path(__file__).resolve().parents[1]
DISCORD_GATEWAY = "service-bursawatch-discord-delivery/bin/discord_delivery/discord_gateway.py"
DISCORD_API_PATTERNS = (
    re.compile(r"discord(?:app)?\.com/api/v\d+", re.IGNORECASE),
    re.compile(r"Authorization.{0,100}\bBot\b", re.IGNORECASE),
    re.compile(r"(?:f)?[\"'](/channels/)", re.IGNORECASE),
)


def _manifest() -> dict[str, object]:
    return json.loads((ROOT / "platform-bursawatch-release/release-manifest.json").read_text())


def _changed_paths() -> set[str]:
    tracked_paths = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    changed_tracked = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return set(tracked_paths) | set(changed_tracked) | set(untracked)


def _matching_units(path: str, manifest: dict[str, object]) -> list[dict[str, object]]:
    units = manifest["units"]
    assert isinstance(units, list)
    return [
        unit
        for unit in units
        if isinstance(unit, dict)
        and any(fnmatch.fnmatchcase(path, pattern) for pattern in unit.get("paths", []))
    ]


def test_accepts_reviewed_source_and_examples() -> None:
    assert violations_for([
        ".env.example",
        "cron-tg-market-news/bin/scan.py",
        "service-cobalt/compose/docker-compose.yml",
    ]) == []


def test_rejects_runtime_credentials_caches_and_independent_repo() -> None:
    paths = [
        ".env",
        ".worktrees/topic/file.py",
        "service-cobalt/compose/cookies.json",
        "hermes-agent-starter/README.md",
        "cron-tg-market-news/state.json",
        "watcher/__pycache__/scan.pyc",
        "watcher/state/run.lock",
    ]
    assert violations_for(paths) == sorted(paths)


def test_discord_rest_access_is_owned_only_by_delivery_gateway() -> None:
    hits: list[str] = []
    for package_pattern in ("cron-*", "platform-*", "lib-*", "service-*"):
        for package in ROOT.glob(package_pattern):
            if not package.is_dir():
                continue
            for source in package.rglob("*"):
                if not source.is_file() or "tests" in source.parts:
                    continue
                if source.suffix not in {".py", ".sh", ".js", ".mjs", ".ts"}:
                    continue
                text = source.read_text(errors="replace")
                if any(pattern.search(text) for pattern in DISCORD_API_PATTERNS):
                    hits.append(source.relative_to(ROOT).as_posix())

    assert sorted(hits) == [DISCORD_GATEWAY]


def test_changed_paths_map_to_exactly_one_release_unit() -> None:
    manifest = _manifest()
    mapping = {path: _matching_units(path, manifest) for path in sorted(_changed_paths())}
    unmapped = {path: units for path, units in mapping.items() if not units}
    ambiguous = {path: units for path, units in mapping.items() if len(units) > 1}

    assert not unmapped, f"changed paths missing from release manifest: {sorted(unmapped)}"
    assert not ambiguous, f"changed paths map to multiple release units: {sorted(ambiguous)}"


def test_delivery_service_and_host_bootstrap_remain_manual() -> None:
    manifest = _manifest()
    for path in (
        "service-bursawatch-discord-delivery/bin/discord_delivery/api.py",
        "service-bursawatch-discord-delivery/deployment/systemd/bursawatch-discord-delivery.service",
        "platform-bursawatch-release/deployment/bootstrap-release-agent.sh",
    ):
        units = _matching_units(path, manifest)
        assert len(units) == 1
        assert units[0]["handler"] == "manual"


def test_discord_clients_depend_on_shared_runtime_library() -> None:
    manifest = _manifest()
    units = manifest["units"]
    assert isinstance(units, list)
    runtime_units = {
        unit.get("runtime"): unit
        for unit in units
        if isinstance(unit, dict) and unit.get("handler") == "runtime"
    }
    migrated_runtimes = (
        "bursawatch-tg-market-news",
        "bursawatch-tg-phintraco-swing",
        "bursawatch-tg-kelas-investasi-gtw",
        "bursawatch-dc-swing-board",
        "bursawatch-x-account-watch",
        "bursawatch-ig-account-watch",
        "bursawatch-wa-channel-watch",
        "bursawatch-stockbit-snips",
    )

    for runtime in migrated_runtimes:
        assert runtime in runtime_units
        assert "lib-bursawatch-discord-delivery" in runtime_units[runtime].get("depends_on", [])
