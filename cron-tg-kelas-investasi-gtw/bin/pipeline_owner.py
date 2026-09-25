"""Inbox work and bounded agent handoff for the existing Kelas domain owner.

The Telegram adapter owns source acceptance. This module owns only the Kelas
bundle, agent, All, and Board state already defined by this package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import config
from agent_protocol import agent_item, build_wake_payload, validate_submission
from discord import deliver_oldest_ready_event
from models import SourceMedia, SourceMessage
from parsing import parse_gtw_header
from state import (
    claim_oldest_agent, load_state, new_state, observe_messages, ready_events,
    restore_expired_claim, run_lock, save_state,
)
from telegram_source import _atomic_write


class OwnerPending(RuntimeError):
    """Owner state or a required Source Media read is unavailable."""


def _state_path() -> Path:
    return Path(os.environ.get(
        "KELAS_INVESTASI_GTW_STATE_PATH",
        str(Path.home() / ".hermes" / "state" / "kelas-investasi-gtw-watch.json"),
    ))


def _guard_no_post(path: Path, no_post: bool) -> None:
    protected = (Path.home() / ".hermes" / "state").resolve()
    if no_post and (path.expanduser().resolve().is_relative_to(protected)
                    or _media_root(path).expanduser().resolve().is_relative_to(protected)):
        raise ValueError("no-post Kelas work requires isolated state")


def _media_root(path: Path) -> Path:
    configured = os.environ.get("KELAS_INVESTASI_GTW_STATE_MEDIA_ROOT")
    return Path(configured) if configured else path.parent / "media"


def _loaded_config() -> config.LoadedWatchConfig:
    loaded = config.load_watch_config_for_run()
    if loaded.revision is None:
        raise ValueError("Kelas pipeline requires an effective live watch config")
    if (loaded.config.telegram_channel_id, loaded.config.telegram_username) != (2142109618, "kelasinvestasiid"):
        raise ValueError("Kelas pipeline source does not match canonical endpoint")
    return loaded


def _source_media_client():
    base_url = os.environ.get("BURSAWATCH_SOURCE_MEDIA_URL")
    token_file = os.environ.get("BURSAWATCH_SOURCE_MEDIA_READ_TOKEN_FILE")
    if not base_url or not token_file:
        raise OwnerPending("Source Media Owner read credentials are unavailable")
    local = Path(__file__).resolve().parents[2] / "lib-bursawatch-source-media" / "bin"
    if not local.exists():
        local = Path.home() / ".agents" / "skills" / "lib-bursawatch-source-media" / "bin"
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))
    from bursawatch_source_media import SourceMediaClient
    return SourceMediaClient(base_url, Path(token_file))


def _work_message(work: dict[str, Any]) -> tuple[SourceMessage, dict[str, Any] | None, int, int]:
    envelope = work["envelope"]
    if (work["pipeline_id"], work["capability_id"], work["version"], envelope["endpoint_id"], envelope["publisher_id"]) != (
        "swing_support", "swing_support", 1, "telegram:kelasinvestasiid", "kelas-investasi"
    ):
        raise ValueError("unsupported Kelas source work")
    identity = json.dumps(["telegram", envelope["endpoint_id"], envelope["provider_event_id"]], separators=(",", ":"))
    if envelope.get("platform") != "telegram" or work["event_key"] != hashlib.sha256(identity.encode()).hexdigest():
        raise ValueError("Kelas source event identity is invalid")
    expected = hashlib.sha256(f'{work["event_key"]}:1:swing_support'.encode()).hexdigest()
    if work["effect_key"] != expected or work["work_key"] != expected:
        raise ValueError("Kelas work identity is invalid")
    body = envelope["payload"]
    message_id = int(envelope["provider_event_id"])
    published_at = datetime.fromisoformat(envelope["published_at"])
    if message_id <= 0 or published_at.tzinfo is None or type(body.get("text")) is not str:
        raise ValueError("Kelas source message is invalid")
    predecessor = body.get("previous_provider_event_id")
    if type(predecessor) is not int or not 0 <= predecessor < message_id:
        raise ValueError("Kelas source predecessor is invalid")
    bootstrap = body.get("bootstrap_provider_event_id")
    if type(bootstrap) is not int or not 0 <= bootstrap <= predecessor:
        raise ValueError("Kelas source bootstrap identity is invalid")
    reply = body.get("reply_to_message_id")
    if reply is not None and (type(reply) is not int or reply <= 0):
        raise ValueError("Kelas reply identity is invalid")
    ids = body.get("media_ref_ids", [])
    refs = envelope.get("media_refs", [])
    if type(ids) is not list or type(refs) is not list or any(type(ref) is not str for ref in ids):
        raise ValueError("Kelas media mapping is invalid")
    if envelope.get("media_required") and not refs:
        raise ValueError("Kelas source media is not durable")
    selected = [ref for ref in refs if type(ref) is dict and ref.get("ref") in ids and ref.get("kind") == "image"]
    if ids and (len(ids) != 1 or len(selected) != 1 or selected[0].get("content_type") != "image/jpeg" or selected[0].get("durable") is not True):
        raise ValueError("Kelas header photo reference is invalid")
    media = (SourceMedia(message_id, 0),) if selected else ()
    return SourceMessage(message_id, published_at, body["text"], reply, media), selected[0] if selected else None, predecessor, bootstrap


def _cache_header_photo(path: Path, message_id: int, reference: dict[str, Any], media_store: Any) -> Path:
    destination = _media_root(path) / f"kelas-investasi-{message_id}-0.jpg"
    expected_digest = reference.get("sha256")
    expected_size = reference.get("size_bytes")
    if destination.is_file() and destination.stat().st_size == expected_size and hashlib.sha256(destination.read_bytes()).hexdigest() == expected_digest:
        return destination.resolve()
    downloaded = (media_store or _source_media_client()).download(reference["ref"])
    data = getattr(downloaded, "data", None)
    if (type(data) is not bytes or not 1 <= len(data) <= 8 * 1024 * 1024
            or len(data) != expected_size or hashlib.sha256(data).hexdigest() != expected_digest
            or not data.startswith(b"\xff\xd8\xff")):
        raise OwnerPending("Source Media Owner returned a photo that failed integrity checks")
    _atomic_write(destination, data)
    return destination.resolve()


def _load_pipeline_state(path: Path) -> dict[str, object]:
    if path.exists():
        return load_state(path)
    return new_state()


def submit(work: dict[str, Any], *, no_post: bool = False, media_store: Any = None) -> str:
    loaded = _loaded_config()
    path = _state_path()
    _guard_no_post(path, no_post)
    message, reference, predecessor, bootstrap = _work_message(work)
    with config.activate_watch_config(loaded.config), run_lock(path.with_name(path.name + ".lock")):
        state = _load_pipeline_state(path)
        if state["cursor"] is None:
            # The adapter's original future-only high-water mark is stable
            # across all later events. A later work item cannot initialize
            # this owner by claiming its own predecessor as the baseline.
            if predecessor != bootstrap:
                raise OwnerPending("Kelas first source work arrived out of order")
            state["cursor"] = bootstrap
        if message.message_id <= int(state["cursor"] or 0):
            return "accepted"
        if state["cursor"] != predecessor:
            raise OwnerPending("Kelas source work arrived out of order")
        photo_path = None
        if reference is not None and parse_gtw_header(message.text) is not None and message.reply_to_message_id is None:
            photo_path = _cache_header_photo(path, message.message_id, reference, media_store)
        observe_messages(state, [message], datetime.now(timezone.utc))
        if photo_path is not None and state["pending"] and state["pending"][0]["header_message_id"] == message.message_id:
            state["pending"][0]["media"][0]["path"] = str(photo_path)
        save_state(path, state)
    return "accepted"


def _drain(state: dict[str, object], path: Path, now: datetime, no_post: bool, channel_id: str) -> int:
    delivered = 0
    while deliver_oldest_ready_event(state, now, no_post, state_path=path, channel_id=channel_id):
        delivered += 1
    return delivered


def claim_agent(*, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    loaded = _loaded_config()
    path = _state_path()
    _guard_no_post(path, no_post)
    current = now or datetime.now(timezone.utc)
    with config.activate_watch_config(loaded.config), run_lock(path.with_name(path.name + ".lock")):
        state = _load_pipeline_state(path)
        ready_events(state, current)
        save_state(path, state)
        _drain(state, path, current, no_post, loaded.config.alert_discord_channel_id)
        event = claim_oldest_agent(state, current)
        if event is None:
            return {"wakeAgent": False}
        save_state(path, state)
        return build_wake_payload(agent_item(
            event,
            source_username=loaded.config.telegram_username,
            additional_prompt_instruction=loaded.config.additional_prompt_instruction,
        ))


def agent_status(*, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    """Expose one read-only candidate so a platform runner can arbitrate wakes."""
    loaded = _loaded_config()
    path = _state_path()
    _guard_no_post(path, no_post)
    current = now or datetime.now(timezone.utc)
    with config.activate_watch_config(loaded.config), run_lock(path.with_name(path.name + ".lock")):
        state = _load_pipeline_state(path)
        for event in state["outbox"]:
            phase = event["agent_phase"]
            lease = event["agent_lease_until"]
            if phase == "ready" or (phase == "claimed" and isinstance(lease, str) and datetime.fromisoformat(lease) <= current):
                return {"ready": True, "pipeline_id": "swing_support", "event_key": event["event_key"],
                        "published_at": event["source_published_at"]}
        pending = state["pending"]
        if pending:
            candidate = pending[0]
            if current - datetime.fromisoformat(candidate["last_message_at"]) > timedelta(minutes=20):
                return {"ready": True, "pipeline_id": "swing_support",
                        "event_key": f'{candidate["header_message_id"]}:{candidate["ticker"]}',
                        "published_at": candidate["source_published_at"]}
        return {"ready": False, "pipeline_id": "swing_support"}


def submit_analysis(payload: object, *, now: datetime | None = None, no_post: bool = False) -> dict[str, object]:
    loaded = _loaded_config()
    path = _state_path()
    _guard_no_post(path, no_post)
    current = now or datetime.now(timezone.utc)
    raw = json.loads(payload) if isinstance(payload, str) else payload
    if type(raw) is not dict:
        raise ValueError("Kelas agent submission is invalid")
    with config.activate_watch_config(loaded.config), run_lock(path.with_name(path.name + ".lock")):
        state = _load_pipeline_state(path)
        event = next((item for item in state["outbox"] if item.get("event_key") == raw.get("event_key") and item.get("agent_phase") == "claimed"), None)
        if event is None:
            raise ValueError("submission does not match a claimed event")
        if restore_expired_claim(event, current):
            save_state(path, state)
            raise ValueError("submission agent lease has expired")
        accepted = validate_submission(event, raw)
        event["title"] = accepted["title"]
        event["summary"] = accepted["summary"]
        event["agent_phase"] = "delivering"
        event["agent_lease_until"] = None
        save_state(path, state)
        delivered = _drain(state, path, current, no_post, loaded.config.alert_discord_channel_id)
        return {"accepted": True, "event_key": accepted["event_key"], "delivered": delivered}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--agent-status", action="store_true")
    group.add_argument("--claim-agent", action="store_true")
    group.add_argument("--submit-analysis")
    args = parser.parse_args(argv)
    no_post = os.environ.get("BURSAWATCH_TG_SOURCE_NO_POST") == "1"
    if args.agent_status:
        result = agent_status(no_post=no_post)
    elif args.claim_agent:
        result = claim_agent(no_post=no_post)
    elif args.submit_analysis is not None:
        result = submit_analysis(args.submit_analysis, no_post=no_post)
    else:
        result = {"outcome": submit(json.load(sys.stdin), no_post=no_post)}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
