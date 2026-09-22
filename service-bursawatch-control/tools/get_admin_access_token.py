#!/usr/bin/env python3
"""Obtain a Supabase Auth user token and store it in the local control-plane env.

This helper deliberately prompts for credentials instead of accepting them as
command-line arguments, and never prints the returned access token.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def load_env(path: Path) -> tuple[list[str], dict[str, str]]:
    lines = path.read_text().splitlines()
    values: dict[str, str] = {}
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip("\"'")
    return lines, values


def token_claims(token: str) -> dict[str, object]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Supabase did not return a JWT access token")
    encoded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(encoded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Supabase returned an unreadable access token") from exc
    if not isinstance(claims, dict):
        raise ValueError("Supabase returned an invalid access token payload")
    return claims


def store_token(env_path: Path, lines: list[str], token: str) -> None:
    replacement = f"CONTROL_PLANE_ADMIN_ACCESS_TOKEN={token}"
    for index, line in enumerate(lines):
        if line.startswith("CONTROL_PLANE_ADMIN_ACCESS_TOKEN="):
            lines[index] = replacement
            break
    else:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(replacement)
    temporary = env_path.with_name(f".{env_path.name}.tmp")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.chmod(0o600)
    temporary.replace(env_path)
    env_path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env",
        type=Path,
        default=Path.cwd() / "service-bursawatch-control" / ".env",
        help="ignored control-plane env file to update",
    )
    args = parser.parse_args()
    env_path = args.env.expanduser().resolve()
    if not env_path.is_file():
        parser.error(f"env file not found: {env_path}")

    lines, values = load_env(env_path)
    supabase_url = values.get("CONTROL_PLANE_SUPABASE_URL", "").rstrip("/")
    if not supabase_url:
        parser.error("CONTROL_PLANE_SUPABASE_URL is missing from the env file")

    email = input("Supabase Auth email: ").strip()
    password = getpass.getpass("Supabase Auth password: ")
    publishable_key = getpass.getpass("Supabase publishable/anon key: ").strip()
    if not email or not password or not publishable_key:
        parser.error("email, password, and publishable/anon key are required")

    request = urllib.request.Request(
        f"{supabase_url}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"apikey": publishable_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        print(f"Supabase login failed with HTTP {error.code}")
        return 1
    except urllib.error.URLError as error:
        print(f"Supabase login request failed: {error.reason}")
        return 1

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        print("Supabase response did not contain an access token")
        return 1
    try:
        claims = token_claims(token)
    except ValueError as error:
        print(error)
        return 1
    if claims.get("role") != "authenticated" or not claims.get("sub"):
        print("Supabase returned a non-user token; use the Auth access_token, not a publishable or service_role key")
        return 1
    if isinstance(claims.get("exp"), (int, float)) and claims["exp"] <= time.time():
        print("Supabase returned an expired access token")
        return 1

    store_token(env_path, lines, token)
    print(f"Admin access token stored in {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
