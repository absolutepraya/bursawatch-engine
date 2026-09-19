from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_api_systemd_unit_keeps_the_service_on_loopback_with_a_scoped_environment():
    unit = (ROOT / "deployment/systemd/bursawatch-control-plane.service").read_text(encoding="utf-8")

    assert "EnvironmentFile=/home/praya/.hermes/.env" in unit
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
