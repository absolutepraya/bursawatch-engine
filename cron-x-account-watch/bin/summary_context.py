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
    from dataclasses import replace
    import render
    from source_media import reference_id
    record = next((row for row in value["outbox"] if f'{row.get("profile_id")}:{row.get("post_id")}' == key and row.get("agent_phase") == "awaiting_agent"), None)
    if record is None:
        return None
    origin = value.get("source_events", {}).get(record.get("source_event_key"))
    if origin is None:
        return None
    metadata = record.get("source_media_refs", {})
    refs = image_refs(list(metadata.values()) if isinstance(metadata, dict) else metadata, association="source thread")
    associations = {}
    for post in record.get("thread_posts", [record["post"]]):
        for field, role in (("media", "authored"), ("quoted_media", "quoted")):
            for media in post.get(field, []):
                ref = reference_id(media.get("url", ""))
                if ref:
                    associations[ref] = f'{role} image for source post {post["post_id"]}'
    refs = tuple(replace(ref, association=associations.get(ref.ref, ref.association)) for ref in refs)
    text = "\n\n".join(render.markdown(post.get("content_html", "")) for post in record.get("thread_posts", [record["post"]]))
    return SummaryContextClaim(key, record["agent_lease_until"], record["source_event_key"], origin["version"], origin["content_hash"], text, refs, root)


def _load_claim(key, now, no_post):
    import scan
    import state
    import pipeline_owner
    storage = state.state_path()
    pipeline_owner._check_no_post(storage, no_post)
    if no_post and not os.environ.get("X_POST_WATCH_STATE_PATH"):
        raise ValueError("isolated state required")
    import fcntl
    with (storage.parent / "run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return claim_from_state(state.load_state(storage), key, storage.parent / "summary-context")

def prepare_summary_context(request: Mapping[str, object], *, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    current = now or datetime.now(timezone.utc)
    return prepare_claim_context(request, resolve_claim=lambda key: _load_claim(key, current, no_post), client_factory=_client, now=current)


def claim_from_state(value, key, root):
    try:
        return _claim_from_state(value, key, root)
    except Exception:
        return None
