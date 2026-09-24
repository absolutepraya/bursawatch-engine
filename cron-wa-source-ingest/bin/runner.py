"""Unscheduled WhatsApp bridge queue reader. No bridge state is mutated."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for package in ("lib-bursawatch-control", "lib-bursawatch-source-ingest", "lib-bursawatch-source-media"):
    candidate = ROOT / package / "bin"
    if not candidate.exists():
        candidate = Path.home() / ".agents" / "skills" / package / "bin"
    sys.path.insert(0, str(candidate))
owner = ROOT / "cron-wa-channel-watch" / "bin"
if not owner.exists():
    owner = Path.home() / ".agents" / "skills" / "bursawatch-wa-channel-watch" / "bin"
sys.path.insert(0, str(owner))
from source_runner import client, state_root
from adapter import run_once
from config import load_for_run


def _media_client():
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_UPLOAD_TOKEN_FILE")
    url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    if not token_file or not url:
        return None
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(url, Path(token_file))


def main() -> int:
    if os.environ.get("BURSAWATCH_WA_SOURCE_NO_POST") == "1":
        raise RuntimeError("use injected queue and inbox fakes for no-post validation")
    loaded = load_for_run(Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_CONFIG_PATH", str(owner.parent / "config" / "watches.json"))))
    if loaded.revision is None:
        raise RuntimeError("WhatsApp source adapter requires a live watcher configuration revision")
    inbox = client("BURSAWATCH_WA_SOURCE")
    queue_dir = Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_QUEUE_DIR", str(Path.home() / ".hermes" / "state" / "whatsapp-channel-watch" / "queue")))
    archive_root = Path(os.environ.get("WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT", str(Path.home() / ".hermes" / "state" / "whatsapp-channel-watch" / "archive")))
    results = run_once(inbox.get_effective(), loaded.config.profiles, queue_dir, state_root("BURSAWATCH_WA_SOURCE", "bursawatch-wa-source-ingest"), inbox, datetime.now(timezone.utc), archive_root=archive_root, media_store=_media_client())
    print(json.dumps(results, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
