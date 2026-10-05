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
from bursawatch_source_media import SourceMediaClient, SummaryContextClaim, cleanup_claim_context, context_instruction, image_refs, prepare_claim_context


def _client():
    return SourceMediaClient(os.environ["BURSAWATCH_SOURCE_MEDIA_URL"], Path(os.environ["BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE"]))

def _claim_from_state(value, key, root):
    from normalize import deserialize_queue_event
    from classification import is_technical_review
    record = next((row for row in value["outbox"] if row.get("event_key") == key and row.get("agent_phase") == "awaiting_agent"), None)
    if record is None or not record.get("source_event_key"):
        return None
    event = deserialize_queue_event(record["event"])
    if is_technical_review(event.text):
        return None
    return SummaryContextClaim(key, record["agent_lease_until"], record["source_event_key"], 1, record["source_content_hash"], event.text, image_refs(record.get("summary_media_refs", []), association="original source publication"), root)


def _load_claim(key, now, no_post):
    import pipeline_owner
    import state
    storage = pipeline_owner._state_path()
    if no_post:
        pipeline_owner._assert_no_post_isolated(True, (storage, pipeline_owner._archive_root()))
    import fcntl
    with (storage.parent / "pipeline-owner.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return claim_from_state(state.load(storage), key, storage.parent / "summary-context")

def prepare_summary_context(request: Mapping[str, object], *, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    return prepare_claim_context(request, resolve_claim=lambda key: _load_claim(key, current, no_post), client_factory=_client, now=current)


def claim_from_state(value, key, root):
    try:
        return _claim_from_state(value, key, root)
    except Exception:
        return None
