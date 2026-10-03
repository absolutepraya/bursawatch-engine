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

def _claim_from_state(value, key, root):
    import news_source_work
    record = value["candidates"].get(key)
    origin = news_source_work.provenance(value, key)
    if not record or record.get("phase") != "awaiting_agent" or origin is None:
        return None
    return SummaryContextClaim(key, record["agent_lease_until"], origin["event_key"], origin["version"], origin["content_hash"], record["candidate"]["source_text"], image_refs(origin.get("summary_media_refs", []), association="source publication; only this candidate's supplied story"), root)


def _load_claim(key, now, no_post):
    import pipeline_owner
    import state
    pipeline_owner._check_no_post(no_post)
    with state.run_lock():
        return claim_from_state(state.load_state(migrate=False), key, state._state_path().parent / "summary-context")

def prepare_summary_context(request: Mapping[str, object], *, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    return prepare_claim_context(request, resolve_claim=lambda key: _load_claim(key, current, no_post), client_factory=_client, now=current)


def claim_from_state(value, key, root):
    try:
        return _claim_from_state(value, key, root)
    except Exception:
        return None
