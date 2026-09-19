from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_api_systemd_unit_keeps_the_service_on_loopback_with_a_scoped_environment():
    unit = (ROOT / "deployment/systemd/bursawatch-control-plane.service").read_text(encoding="utf-8")

    assert "EnvironmentFile=/home/praya/.hermes/bursawatch-control-plane.env" in unit
    assert "--host 127.0.0.1 --port 9120" in unit
    assert "User=praya" in unit
    assert "NoNewPrivileges=true" in unit
    assert "PrivateTmp=true" in unit
    assert "0.0.0.0" not in unit


def test_nginx_bootstrap_vhost_is_the_only_planned_public_route():
    vhost = (ROOT / "deployment/nginx/api.bursawatch.abhipraya.dev.conf").read_text(encoding="utf-8")

    assert "server_name api.bursawatch.abhipraya.dev;" in vhost
    assert "proxy_pass http://127.0.0.1:9120;" in vhost
    assert "listen 80;" in vhost
    assert "listen 443" not in vhost


def test_deployment_uses_the_self_contained_validator_bundle():
    deployment = (ROOT / "deployment/README.md").read_text(encoding="utf-8")

    assert "validator-sources/" in deployment
    assert "not point the API at a live watcher runtime directory" in deployment


def test_repeat_release_helper_is_syntax_checked_and_keeps_its_boundary():
    helper = ROOT / "deploy.sh"
    script = helper.read_text(encoding="utf-8")

    assert helper.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(helper)], check=True)
    for command in ("sync", "migrate", "restart", "release"):
        assert f"  {command})" in script
    assert "require_apply" in script
    assert "require_published_commit" in script
    assert "--delete" in script
    assert "--no-perms" in script
    assert "--omit-dir-times" in script
    assert '"$package_dir/$source_dir/"' in script
    assert '"$remote_host:$runtime_dir/$source_dir/"' in script
    assert "certbot" not in script
    assert "/etc/nginx" not in script
    assert "cloudflare" not in script
    assert "bursawatch-schedule-reconciler" not in script
    assert "~/.hermes/.env" not in script
