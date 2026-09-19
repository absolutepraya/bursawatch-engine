from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from config import load_for_run


DEFAULT_CONFIG = Path("~/.agents/skills/bursawatch-wa-channel-watch/config/watches.json").expanduser()
DEFAULT_BRIDGE = "http://127.0.0.1:3055"
RequestFn = Callable[[str, str, dict[str, object] | None], dict[str, object]]


def _bridge_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("bridge URL must be an HTTP loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("bridge URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("bridge URL must not contain a path")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("bridge URL has an invalid port") from exc
    return value.rstrip("/")


def _request_json(method: str, url: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"bridge returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError("bridge request failed") from exc
    except TimeoutError as exc:
        raise RuntimeError("bridge request timed out") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("bridge returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("bridge returned an invalid JSON object")
    return result


def _targets(config_path: Path) -> list[dict[str, str]]:
    config = load_for_run(config_path).config
    return [
        {
            "profile_id": profile.id,
            "display_name": profile.display_name,
            "channel_jid": profile.channel_jid,
        }
        for profile in config.profiles
        if profile.enabled
    ]


def run(
    config_path: Path,
    bridge_url: str,
    apply: bool = False,
    request: RequestFn = _request_json,
) -> dict[str, object]:
    bridge = _bridge_url(bridge_url)
    targets = _targets(config_path)
    health = request("GET", f"{bridge}/health", None)
    if health.get("status") != "connected":
        raise RuntimeError("WhatsApp bridge is not connected")
    if health.get("channelSink") is not True:
        raise RuntimeError("WhatsApp Channel sink is unavailable")

    if not apply:
        return {
            "action": "dry_run",
            "bridge": {
                "status": health.get("status"),
                "channel_sink": health.get("channelSink"),
            },
            "channels": [
                {**target, "status": "would_subscribe"}
                for target in targets
            ],
        }

    channels: list[dict[str, object]] = []
    errors = False
    for target in targets:
        try:
            result = request(
                "POST",
                f"{bridge}/newsletter/follow",
                {"jid": target["channel_jid"]},
            )
            if result.get("channel_jid") != target["channel_jid"]:
                raise RuntimeError("bridge returned the wrong Channel")
            channels.append({
                **target,
                "status": "subscribed",
                "duration": result.get("duration"),
            })
        except (RuntimeError, ValueError) as exc:
            errors = True
            channels.append({**target, "status": "failed", "error": str(exc)})

    return {
        "action": "apply",
        "bridge": {
            "status": health.get("status"),
            "channel_sink": health.get("channelSink"),
        },
        "channels": channels,
        "ok": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ensure enabled WhatsApp Channel profiles are followed by the existing bridge account."
    )
    parser.add_argument("command", nargs="?", choices={"ensure"}, default="ensure")
    parser.add_argument("--apply", action="store_true", help="perform the follow and live-update subscription")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--bridge-url", default=os.environ.get("WHATSAPP_CHANNEL_BRIDGE_URL", DEFAULT_BRIDGE))
    parser.add_argument("--json", action="store_true", help="emit the machine-readable result")
    args = parser.parse_args()

    try:
        result = run(args.config.expanduser(), args.bridge_url, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0 if result.get("ok", True) else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"action": "error", "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
