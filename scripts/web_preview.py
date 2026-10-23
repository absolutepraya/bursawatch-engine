#!/usr/bin/env python3
"""Manage only paired Bursawatch PR Workers and their hostname Access gates."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

ACCOUNT = "40ffe81c2b657eebc19edd8558b5f5ba"
SUBDOMAIN = "absolutepraya"
PACKAGES = {"web-config": "bursawatch-dash", "web-landing": "bursawatch-landing"}
ROOT = Path(__file__).resolve().parent.parent


def targets(number: str) -> dict[str, dict[str, str]]:
    if not re.fullmatch(r"[1-9][0-9]{0,8}", str(number)):
        raise ValueError("Expected a positive pull request number")
    return {
        package: {"name": f"{prefix}-pr-{number}",
                  "host": f"{prefix}-pr-{number}.{SUBDOMAIN}.workers.dev"}
        for package, prefix in PACKAGES.items()
    }


def prepare(number: str, root: Path = ROOT) -> None:
    pair = targets(number)
    for package, target in pair.items():
        source = json.loads((root / package / "wrangler.jsonc").read_text())
        # Copy only build/runtime settings. Never inherit production routes,
        # bindings, vars, secrets, environments, or an alternate preview URL.
        config = {key: source[key] for key in (
            "main", "compatibility_date", "compatibility_flags", "assets"
        )}
        config.update(account_id=ACCOUNT, name=target["name"], routes=[],
                      workers_dev=True, preview_urls=False,
                      vars={"BURSAWATCH_PREVIEW_MODE": "1"})
        if package == "web-landing":
            config["vars"]["BURSAWATCH_CONFIG_URL"] = "https://" + pair["web-config"]["host"]
        (root / package / ".wrangler-preview.json").write_text(json.dumps(config, indent=2) + "\n")


class Cloudflare:
    def __init__(self) -> None:
        self.token = os.environ["CLOUDFLARE_API_TOKEN"]

    def request(self, method: str, path: str, body=None, *, missing_ok=False):
        request = urllib.request.Request(
            f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/{path}",
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            # Avoid dumping provider bodies or request headers into CI logs.
            raise RuntimeError(f"Cloudflare {method} failed with HTTP {error.code}") from None
        if not result.get("success"):
            raise RuntimeError(f"Cloudflare {method} did not succeed")
        return result

    def apps(self):
        page = 1
        while True:
            response = self.request("GET", f"access/apps?per_page=100&page={page}")
            yield from response["result"]
            if page >= response.get("result_info", {}).get("total_pages", 1):
                return
            page += 1


def app_name(target: dict[str, str]) -> str:
    return "Bursawatch preview: " + target["name"]


def matching_app(apps, target):
    matches = [app for app in apps if app.get("domain") == target["host"]]
    if len(matches) > 1 or any(app.get("name") != app_name(target) for app in matches):
        raise RuntimeError("Preview hostname already has an unexpected Access owner")
    return matches[0] if matches else None


def check_policy(app, target, email):
    policies = app.get("policies", [])
    if (app.get("type") != "self_hosted" or app.get("domain") != target["host"]
            or len(policies) != 1 or policies[0].get("decision") != "allow"
            or policies[0].get("include") != [{"email": {"email": email}}]
            or policies[0].get("exclude") or policies[0].get("require")):
        raise RuntimeError("Preview Access policy differs from the approved email allowlist")


def protect(number: str, api, email: str) -> None:
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Set BURSAWATCH_PREVIEW_EMAIL to the approved reviewer email")
    apps = list(api.apps())
    for target in targets(number).values():
        app = matching_app(apps, target)
        if app is None:
            app = api.request("POST", "access/apps", {
                "name": app_name(target), "type": "self_hosted", "domain": target["host"],
                "session_duration": "24h", "http_only_cookie_attribute": True,
                "policies": [{"name": "Approved preview reviewer", "decision": "allow",
                              "include": [{"email": {"email": email}}]}],
            })["result"]
        # Read back the policy, including on repeat runs. Do not silently widen it.
        app = api.request("GET", f"access/apps/{app['id']}")["result"]
        check_policy(app, target, email)
        print(f"Access policy verified for {target['host']}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify(number: str, opener=None, *, attempts=13, retry_delay=5) -> None:
    opener = opener or urllib.request.build_opener(NoRedirect)
    for package, target in targets(number).items():
        paths = ["/", "/favicon.ico"]
        if package == "web-config":
            paths += ["/app", "/workspace", "/api/control/watchers"]
        for path in paths:
            for attempt in range(attempts):
                try:
                    request = urllib.request.Request(
                        "https://" + target["host"] + path,
                        headers={"User-Agent": "Bursawatch-Preview-CI/1.0"},
                    )
                    response = opener.open(request, timeout=30)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    code = response.code
                    location = urllib.parse.urlparse(response.headers.get("Location", ""))
                    gated = (code == 302 and location.scheme == "https"
                             and location.hostname
                             and location.hostname.endswith(".cloudflareaccess.com")
                             and location.path.startswith("/cdn-cgi/access/login/"))
                if gated:
                    break
                # New workers.dev routes can return 404 during propagation.
                # Never retry app content, app redirects, or an unrelated login.
                if code != 404 or attempt == attempts - 1:
                    raise RuntimeError(f"Anonymous access was not gated (HTTP {code}): {target['host']}{path}")
                print(f"Waiting for preview route propagation: {target['host']}", flush=True)
                time.sleep(retry_delay)
        print(f"Anonymous HTML, assets and API blocked: https://{target['host']}")


def cleanup(number: str, api, *, keep_access=False) -> None:
    # Remove both Workers before removing either gate. A failed deletion must
    # leave Access intact. Fixed names and account prevent production deletion.
    pair = targets(number)
    for target in pair.values():
        api.request("DELETE", f"workers/services/{target['name']}", missing_ok=True)
        print(f"Preview Worker removed or absent: {target['name']}")
    if not keep_access:
        apps = list(api.apps())
        for target in pair.values():
            app = matching_app(apps, target)
            if app:
                api.request("DELETE", f"access/apps/{app['id']}", missing_ok=True)
                print(f"Preview Access gate removed: {target['host']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "protect", "verify", "cleanup", "disable"])
    parser.add_argument("number")
    args = parser.parse_args()
    targets(args.number)  # Validate before constructing a client or making calls.
    if args.command == "prepare":
        prepare(args.number)
    elif args.command == "verify":
        verify(args.number)
    elif args.command == "protect":
        protect(args.number, Cloudflare(), os.environ.get("BURSAWATCH_PREVIEW_EMAIL", ""))
    else:
        cleanup(args.number, Cloudflare(), keep_access=args.command == "disable")


if __name__ == "__main__":
    main()
