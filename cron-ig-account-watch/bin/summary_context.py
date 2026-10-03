from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
from typing import Mapping

_library = Path(__file__).resolve().parents[2] / "lib-bursawatch-source-media" / "bin"
if not _library.is_dir():
    _library = Path.home() / ".agents/skills/lib-bursawatch-source-media/bin"
if str(_library) not in sys.path:
    sys.path.insert(0, str(_library))
from bursawatch_source_media import SourceMediaClient, SummaryContextClaim, context_instruction, image_refs, prepare_claim_context


def _client():
    return SourceMediaClient(os.environ["BURSAWATCH_SOURCE_MEDIA_URL"], Path(os.environ["BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE"]))

def _claim_from_state(value, key, root, origin):
    import agent_protocol
    import state
    record = next((row for row in value["outbox"] if row.get("event_key") == key and row.get("agent_phase") == "awaiting_agent"), None)
    if record is None or origin is None:
        return None
    post = state.deserialize_post(record["post"])
    return SummaryContextClaim(key, record["agent_lease_until"], origin["source_event_key"], 1, origin["content_hash"], agent_protocol.caption_text(post), image_refs(origin.get("summary_media_refs", []), association="original source publication"), root)


def _load_claim(key, now, no_post):
    import scan
    import state
    import source_work_routes
    if no_post:
        scan._require_no_post_isolation()
    storage = scan.state_path()
    with scan._process_lock(storage, blocking=False) as acquired:
        if not acquired:
            return None
        return claim_from_state(state.load_state(storage), key, storage.parent / "summary-context", source_work_routes.read(storage, key))

def prepare_summary_context(request: Mapping[str, object], *, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    return prepare_claim_context(request, resolve_claim=lambda key: _load_claim(key, current, no_post), client_factory=_client, now=current)


def claim_from_state(value, key, root, origin):
    try:
        return _claim_from_state(value, key, root, origin)
    except Exception:
        return None
