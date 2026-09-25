"""Sanitized admin inspection and exact-digest retry CLI."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def _request(method: str, path: str, data: dict | None = None) -> dict:
    base = os.environ.get("DISCORD_DELIVERY_ADMIN_URL", "http://127.0.0.1:9140")
    token = os.environ.get("DISCORD_DELIVERY_ADMIN_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_DELIVERY_ADMIN_TOKEN is required")
    request = urllib.request.Request(
        base.rstrip("/") + path, method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def _show(row: dict) -> None:
    destination = row.get("target", {})
    print("\t".join((row["key"], ",".join(f"{key}={value}" for key, value in destination.items()),
                     row["digest"], row["status"], row["created_at"], row.get("error_category") or "")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    status = subcommands.add_parser("status")
    status.add_argument("--limit", type=int, default=50)
    status.add_argument("--offset", type=int, default=0)
    retry = subcommands.add_parser("retry")
    retry.add_argument("key")
    retry.add_argument("--expected-digest", required=True)
    retry.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        page = _request("GET", f"/v1/admin/operations?limit={args.limit}&offset={args.offset}")
        for row in page["operations"]:
            _show(row)
        return 0
    offset = 0
    selected = None
    while offset <= 100000:
        page = _request("GET", f"/v1/admin/operations?limit=100&offset={offset}")
        selected = next((row for row in page["operations"] if row["key"] == args.key), None)
        if selected or len(page["operations"]) < 100:
            break
        offset += 100
    if selected is None:
        raise RuntimeError("operation key not found")
    _show(selected)
    if selected["status"] != "blocked" or selected["digest"] != args.expected_digest:
        raise RuntimeError("blocked status and expected digest must match")
    if not args.apply:
        print("Preview only. Pass --apply to release this blocked operation.")
        return 0
    path = "/v1/admin/operations/" + urllib.parse.quote(args.key, safe="") + "/retry"
    updated = _request("POST", path, {"expected_digest": args.expected_digest})
    _show(updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
