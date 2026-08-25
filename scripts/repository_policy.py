#!/usr/bin/env python3
from __future__ import annotations

from pathlib import PurePosixPath
import subprocess


FORBIDDEN_PARTS = {
    ".git",
    ".playwright-mcp",
    ".pytest_cache",
    ".superpowers",
    ".venv",
    ".worktrees",
    "__pycache__",
    "build",
    "dist",
    "state",
    "tmp",
    "venv",
}
FORBIDDEN_NAMES = {".DS_Store", "state.json", "state.db"}
FORBIDDEN_SUFFIXES = (
    ".bak",
    ".backup",
    ".db-shm",
    ".db-wal",
    ".key",
    ".log",
    ".orig",
    ".p12",
    ".pem",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".tmp",
)
FORBIDDEN_PREFIXES = (
    "hermes-agent-starter/",
    "mm-weekly-log-normalizer/local-backfill/",
    "mm-weekly-log-normalizer/preview/",
)
FORBIDDEN_EXACT = {
    ".env",
    "cobalt/compose/cookies.json",
}


def violations_for(paths: list[str]) -> list[str]:
    violations: list[str] = []
    for raw in paths:
        path = PurePosixPath(raw)
        parts = set(path.parts)
        name = path.name
        forbidden = (
            raw in FORBIDDEN_EXACT
            or raw.startswith(FORBIDDEN_PREFIXES)
            or bool(parts & FORBIDDEN_PARTS)
            or name in FORBIDDEN_NAMES
            or name.startswith("state.db-")
            or name.endswith(FORBIDDEN_SUFFIXES)
            or (name.startswith(".env.") and name != ".env.example")
        )
        if forbidden:
            violations.append(raw)
    return sorted(violations)


def tracked_paths() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"])
    return [item.decode() for item in output.split(b"\0") if item]


def main() -> int:
    violations = violations_for(tracked_paths())
    if violations:
        print("repository policy rejected tracked artifacts:")
        for path in violations:
            print(f"  {path}")
        return 1
    print("repository policy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
