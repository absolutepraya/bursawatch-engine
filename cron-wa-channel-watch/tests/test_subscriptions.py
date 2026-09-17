from __future__ import annotations

from pathlib import Path

import pytest

import subscriptions


CONFIG = Path(__file__).resolve().parents[1] / "config" / "watches.json"


def test_dry_run_checks_bridge_without_following() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(method: str, url: str, payload: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, payload))
        return {"status": "connected", "channelSink": True}

    result = subscriptions.run(CONFIG, "http://127.0.0.1:3055", request=fake_request)

    assert result["action"] == "dry_run"
    assert result["channels"] == [
        {
            "profile_id": "bri-danareksa-sekuritas",
            "display_name": "BRI Danareksa Sekuritas",
            "channel_jid": "120363419226413141@newsletter",
            "status": "would_subscribe",
        }
    ]
    assert calls == [("GET", "http://127.0.0.1:3055/health", None)]


def test_apply_follows_each_enabled_channel() -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def fake_request(method: str, url: str, payload: dict[str, object] | None) -> dict[str, object]:
        calls.append((method, url, payload))
        if method == "GET":
            return {"status": "connected", "channelSink": True}
        assert payload is not None
        return {"channel_jid": payload["jid"], "duration": "86400"}

    result = subscriptions.run(CONFIG, "http://127.0.0.1:3055", apply=True, request=fake_request)

    assert result["action"] == "apply"
    assert result["ok"] is True
    assert result["channels"] == [
        {
            "profile_id": "bri-danareksa-sekuritas",
            "display_name": "BRI Danareksa Sekuritas",
            "channel_jid": "120363419226413141@newsletter",
            "status": "subscribed",
            "duration": "86400",
        }
    ]
    assert calls == [
        ("GET", "http://127.0.0.1:3055/health", None),
        (
            "POST",
            "http://127.0.0.1:3055/newsletter/follow",
            {"jid": "120363419226413141@newsletter"},
        ),
    ]


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:3055",
        "http://example.com:3055",
        "http://127.0.0.1:3055/path",
        "http://127.0.0.1:3055?token=secret",
    ],
)
def test_bridge_url_is_local_http_only(value: str) -> None:
    with pytest.raises(ValueError, match="bridge URL"):
        subscriptions._bridge_url(value)
