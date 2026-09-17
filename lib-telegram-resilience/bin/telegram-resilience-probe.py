#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram_resilience import PolyCopResilience, is_transport_error


WIB = ZoneInfo("Asia/Jakarta")


def _endpoint(client: Any) -> str | None:
    session = getattr(client, "session", None)
    address = getattr(session, "server_address", None)
    port = getattr(session, "port", None)
    if not address:
        return None
    return f"{address}:{port}" if port else str(address)


async def run_probe(
    client: Any, resilience: PolyCopResilience, now: datetime
) -> dict[str, object]:
    decision = resilience.acquire_probe("telegram-resilience-probe", now)
    if decision.kind != "probe":
        return {
            "connected": False,
            "authorized": decision.kind != "auth_required",
            "status": decision.kind,
        }
    try:
        await client.connect()
        if not await client.is_user_authorized():
            resilience.record_auth_required(
                decision.lease_id, "telegram-resilience-probe", now
            )
            return {"connected": True, "authorized": False}
        me = await client.get_me()
        resilience.record_authenticated_success(
            decision.lease_id,
            "telegram-resilience-probe",
            now,
            getattr(getattr(client, "session", None), "dc_id", None),
            _endpoint(client),
        )
        return {
            "connected": True,
            "authorized": True,
            "dc_id": getattr(getattr(client, "session", None), "dc_id", None),
        }
    except BaseException as error:
        if is_transport_error(error):
            resilience.record_transport_failure(
                decision.lease_id, "telegram-resilience-probe", error, now
            )
            return {"connected": False, "authorized": False, "status": "transport_open"}
        raise
    finally:
        await client.disconnect()


def _client_from_environment() -> Any:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    session = os.environ.get("POLYCOP_SESSION_STRING")
    if not api_id or not api_hash or not session:
        raise RuntimeError(
            "TELEGRAM_API_ID, TELEGRAM_API_HASH, and POLYCOP_SESSION_STRING are required"
        )
    return TelegramClient(StringSession(session), int(api_id), api_hash)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--log-path", type=Path, required=True)
    parser.add_argument("--no-notify", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        result = asyncio.run(
            run_probe(
                _client_from_environment(),
                PolyCopResilience.for_paths(arguments.state_path, arguments.log_path),
                datetime.now(WIB),
            )
        )
    except Exception as error:
        print(json.dumps({"connected": False, "authorized": False, "error": type(error).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("authorized") else 2


if __name__ == "__main__":
    raise SystemExit(main())
