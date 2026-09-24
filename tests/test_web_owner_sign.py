"""Exercise the owner-sign workflow against an isolated local Git remote."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "web_owner_sign.py"
SPEC = importlib.util.spec_from_file_location("web_owner_sign", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
web_owner_sign = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web_owner_sign)


def git(directory: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(directory), *args], text=True, stderr=subprocess.PIPE
    ).strip()


def publish(directory: Path, message: str) -> str:
    git(directory, "add", "-A")
    git(directory, "commit", "-m", message)
    git(directory, "push", "origin", "HEAD:main")
    return git(directory, "rev-parse", "HEAD")


def test_signs_each_changed_package_once_after_successful_web_ci(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-b", "main", str(checkout)], check=True)
    git(checkout, "config", "user.name", "absolutepraya")
    git(checkout, "config", "user.email", "94060711+absolutepraya@users.noreply.github.com")
    git(checkout, "remote", "add", "origin", str(remote))
    for package in web_owner_sign.PACKAGES:
        path = checkout / package
        path.mkdir()
        (path / "page.txt").write_text(f"{package} initial\n")
    initial_sha = publish(checkout, "feat: initial web source")
    monkeypatch.chdir(checkout)

    assert web_owner_sign.sign(initial_sha) == 0
    first_sign_sha = git(checkout, "rev-parse", "HEAD")
    assert first_sign_sha != initial_sha
    assert git(checkout, "log", "-1", "--format=%ae") == (
        "94060711+absolutepraya@users.noreply.github.com"
    )
    for package in web_owner_sign.PACKAGES:
        marker = checkout / package / web_owner_sign.MARKER
        assert web_owner_sign.signed_fingerprint(marker) == (
            web_owner_sign.tree_fingerprint(first_sign_sha, package)
        )
        assert len(marker.read_text().splitlines()) == 2

    # The sign commit itself triggers Web CI again; it must not create a loop.
    assert web_owner_sign.sign(first_sign_sha) == 0
    assert git(checkout, "rev-parse", "HEAD") == first_sign_sha

    (checkout / "web-config" / "page.txt").write_text("config changed\n")
    config_sha = publish(checkout, "feat: update config")
    assert web_owner_sign.sign(config_sha) == 0
    config_sign_sha = git(checkout, "rev-parse", "HEAD")
    assert len((checkout / "web-config" / web_owner_sign.MARKER).read_text().splitlines()) == 3
    assert len((checkout / "web-landing" / web_owner_sign.MARKER).read_text().splitlines()) == 2

    # An older successful run cannot sign newer, unvalidated landing code.
    (checkout / "web-landing" / "page.txt").write_text("landing changed\n")
    landing_sha = publish(checkout, "feat: update landing")
    assert web_owner_sign.sign(config_sign_sha) == 0
    assert git(checkout, "rev-parse", "HEAD") == landing_sha
    assert web_owner_sign.sign(landing_sha) == 0
    assert len((checkout / "web-landing" / web_owner_sign.MARKER).read_text().splitlines()) == 3

    # A completed run for config must not sign a newer landing change before
    # landing's own Web CI passes. The later run signs both stale packages.
    (checkout / "web-config" / "page.txt").write_text("config changed again\n")
    config_pending_sha = publish(checkout, "feat: another config update")
    (checkout / "web-landing" / "page.txt").write_text("landing changed again\n")
    landing_pending_sha = publish(checkout, "feat: another landing update")
    assert web_owner_sign.sign(config_pending_sha) == 0
    assert git(checkout, "rev-parse", "HEAD") == landing_pending_sha
    assert web_owner_sign.sign(landing_pending_sha) == 0
    assert len((checkout / "web-config" / web_owner_sign.MARKER).read_text().splitlines()) == 4
    assert len((checkout / "web-landing" / web_owner_sign.MARKER).read_text().splitlines()) == 4
