"""Private source client construction for unscheduled platform entry points."""
from __future__ import annotations

import os
from pathlib import Path

from source_event_client import SourceEventClient


def client(prefix: str) -> SourceEventClient:
    url = os.environ[f"{prefix}_CONTROL_PLANE_URL"]
    token_file = Path(os.environ[f"{prefix}_CONTROL_PLANE_TOKEN_FILE"])
    if token_file.stat().st_mode & 0o077:
        raise RuntimeError("source inbox token file permissions are too broad")
    return SourceEventClient(url, token_file.read_text().strip())


def state_root(prefix: str, identity: str) -> Path:
    return Path(os.environ.get(f"{prefix}_STATE_ROOT", str(Path.home() / ".hermes" / "state" / identity)))
