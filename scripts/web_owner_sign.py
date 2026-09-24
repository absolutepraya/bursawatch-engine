#!/usr/bin/env python3
"""Record an owner-authored web change after the matching Web CI run passes.

The workflow authenticates and configures Git before invoking this script. This
script only writes a marker for package content that the successful run tested.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PACKAGES = ("web-config", "web-landing")
MARKER = "absolutepraya-sign.md"
SIGNATURE = re.compile(r"^[0-9]{8}-[0-9]{6} ([0-9a-f]{64})$")


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def tree_fingerprint(revision: str, package: str) -> str:
    """Hash tracked package paths and blob IDs, excluding its release marker."""
    entries = git("ls-tree", "-r", "-z", revision, "--", package).stdout
    marker_path = f"{package}/{MARKER}".encode()
    digest = hashlib.sha256()
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        _, path = entry.split(b"\t", 1)
        if path != marker_path:
            digest.update(entry)
            digest.update(b"\0")
    return digest.hexdigest()


def signed_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        match = SIGNATURE.fullmatch(line)
        if match:
            return match.group(1)
    return None


def sign(validated_sha: str, *, attempts: int = 3) -> int:
    if not re.fullmatch(r"[0-9a-f]{40}", validated_sha):
        raise ValueError("validated SHA must be a full GitHub commit hash")

    for attempt in range(1, attempts + 1):
        git("fetch", "--quiet", "origin", "main")
        current_sha = git("rev-parse", "FETCH_HEAD").stdout.decode().strip()
        if git("merge-base", "--is-ancestor", validated_sha, current_sha, check=False).returncode:
            print("Validated commit is no longer on main; skipping this run.")
            return 0

        eligible = []
        newer_web_content = False
        for package in PACKAGES:
            tested = tree_fingerprint(validated_sha, package)
            current = tree_fingerprint(current_sha, package)
            if tested != current:
                print(f"{package}: newer code awaits its own Web CI run.")
                newer_web_content = True
            eligible.append((package, current))
        if newer_web_content:
            print("Skipping the entire sign until both web packages pass Web CI together.")
            return 0

        git("switch", "--force-create", "web-owner-sign", current_sha)
        timestamp = datetime.now(timezone.utc).strftime("%m%d%Y-%H%M%S")
        changed = []
        for package, fingerprint in eligible:
            path = Path(package) / MARKER
            if signed_fingerprint(path) == fingerprint:
                continue
            previous = path.read_text(encoding="utf-8") if path.exists() else (
                "# Owner release signatures (UTC)\n\n"
            )
            path.write_text(
                previous.rstrip("\n") + f"\n{timestamp} {fingerprint}\n",
                encoding="utf-8",
            )
            changed.append(str(path))

        if not changed:
            print("All validated web content is already signed; no commit needed.")
            return 0

        git("add", "--", *changed)
        git("commit", "-m", "chore(web): record owner release signature")
        result = git("push", "origin", "HEAD:main", check=False)
        if result.returncode == 0:
            print(f"Signed {', '.join(changed)} on main.")
            return 0
        print(f"Main advanced or push was refused (attempt {attempt}/{attempts}).", file=sys.stderr)
        if attempt == attempts:
            print(result.stderr.decode(errors="replace"), file=sys.stderr)
            return result.returncode

    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validated-sha", required=True)
    arguments = parser.parse_args()
    return sign(arguments.validated_sha)


if __name__ == "__main__":
    raise SystemExit(main())
