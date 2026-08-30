from __future__ import annotations

import fcntl
import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
import discord
import render
import rsshub
import state
from agent_protocol import agent_item, build_wake_payload, is_promotional, requires_relevance, validate_submission


WIB = ZoneInfo("Asia/Jakarta")
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
WATCHER_HEARTBEAT_NAME = "x-post"
OWNER_MENTION = "<@443342168434933760>"


@dataclass
class RunStats:
    fetched: int = 0
    filtered: int = 0
    queued: int = 0
    delivered: int = 0
    degraded: bool = False
    needs_attention: bool = False
    reasons: list[str] = field(default_factory=list)

    def note_empty_profile(self, handle: str) -> None:
        self.degraded = True
        self.reasons.append(f"{handle}: empty source feed")

    def note_source_error(self, reason: str) -> None:
        self.degraded = True
        self.reasons.append(reason)
        if "HTTP 401" in reason or "HTTP 403" in reason:
            self.needs_attention = True

    def tokens(self) -> str:
        return f"{self.fetched} fetched · {self.filtered} filtered · {self.queued} queued · {self.delivered} delivered · {len(self.reasons)} errors"


def state_path() -> Path:
    return Path(os.environ.get("X_POST_WATCH_STATE_PATH", str(Path(__file__).resolve().parent.parent / "state" / "state.json")))


def config_path() -> Path:
    return Path(os.environ.get("X_POST_WATCH_CONFIG_PATH", str(Path(__file__).resolve().parent.parent / "config" / "watches.json")))


def format_heartbeat(now: datetime, stats: RunStats) -> str:
    suffix = f" · {stats.reasons[0]}" if stats.reasons else ""
    attention = f" {OWNER_MENTION}" if stats.needs_attention else ""
    return f"🫀 {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · {stats.tokens()}" + (" ⚠️" if stats.degraded else "") + suffix + attention


def format_fatal(now: datetime, reason: str) -> str:
    return f"❌ {WATCHER_HEARTBEAT_NAME} · {now.astimezone(WIB):%H:%M} WIB · failed: {' '.join(reason.split())[:180]}"


def _next_deliverable_index(value: dict, profiles: dict, now: datetime) -> int | None:
    for index, event in enumerate(value["outbox"]):
        profile = profiles.get(event["profile_id"])
        if profile is None:
            continue
        if state.is_ready(event, now) and (not profile.uses_llm or event.get("agent_phase") == "ready"):
            return index
    return None


def _target_channel(profile, event: dict) -> str:
    if not profile.enable_llm_routing:
        return profile.discord_channels[0].channel_id
    return profile.channel_for(event["route"]).channel_id


def _deliver(value: dict, profiles: dict, event_index: int, dry_run: bool, storage: Path, stats: RunStats) -> bool:
    event = value["outbox"][event_index]
    profile = profiles[event["profile_id"]]
    post = state.deserialize_post(event["post"])
    thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]]))
    channel_id = _target_channel(profile, event)
    messages = render.render_post(profile, post, event.get("summary") if profile.enable_llm_summary else None, event.get("title"), thread_posts)
    try:
        if event["text_index"] < len(messages):
            index = event["text_index"]
            discord.post_text(messages[index], channel_id, dry_run, discord.nonce(f"{profile.id}:{post.post_id}", f"text:{index}"))
            event["text_index"] += 1
            state.save_state(storage, value)
            return True
        all_media = []
        seen_media: set[str] = set()
        for thread_post in thread_posts:
            for media in thread_post.media:
                if media.url not in seen_media:
                    seen_media.add(media.url)
                    all_media.append(media)
        for thread_post in thread_posts:
            for media in thread_post.quoted_media:
                if media.url not in seen_media:
                    seen_media.add(media.url)
                    all_media.append(media)
        if profile.forward_media and event["media_index"] < len(all_media):
            index = event["media_index"]
            discord.post_media(all_media[index].url, channel_id, dry_run, discord.nonce(f"{profile.id}:{post.post_id}", f"media:{index}"), storage.parent / "media")
            event["media_index"] += 1
            state.save_state(storage, value)
            return True
    except Exception as exc:
        event["last_error"] = " ".join(str(exc).split())[:180]
        stats.degraded = True
        stats.reasons.append(event["last_error"])
        state.save_state(storage, value)
        return False
    value["outbox"].pop(event_index)
    state.save_state(storage, value)
    stats.delivered += 1
    return True


def run(now: datetime | None = None, dry_run: bool | None = None) -> dict[str, object]:
    now = now or datetime.now(WIB)
    dry_run = bool(dry_run) or os.environ.get("X_POST_WATCH_NO_POST") == "1"
    storage = state_path()
    storage.parent.mkdir(parents=True, exist_ok=True)
    with (storage.parent / "run.lock").open("w") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return build_wake_payload(None)
        stats = RunStats()
        try:
            watches = config.load_watch_config(config_path())
            value = state.load_state(storage)
            stats.filtered = state.take_filtered_since_last_heartbeat(value)
            profiles = {profile.id: profile for profile in watches.profiles}
            for profile in watches.profiles:
                if not profile.enabled: continue
                try:
                    record = value["profiles"].get(profile.id) or {}
                    posts = rsshub.fetch_profile_items(profile, after_id=record.get("cursor"))
                    stats.fetched += len(posts)
                    if not posts:
                        stats.note_empty_profile(profile.handle)
                    queued, reason = state.observe_posts(
                        value, profile, posts,
                        lambda post: rsshub.is_forwardable(profile, post),
                        lambda post: rsshub.is_self_thread_post(profile, post), now,
                    )
                    stats.queued += queued
                    if reason:
                        stats.degraded = True; stats.reasons.append(f"{profile.id}: {reason}")
                    state.save_state(storage, value)
                except rsshub.SourceFetchError as exc:
                    stats.note_source_error(f"{profile.id}: {exc}")
            while (event_index := _next_deliverable_index(value, profiles, now)) is not None:
                if not _deliver(value, profiles, event_index, dry_run, storage, stats): break
            discord.post_text(format_heartbeat(now, stats), HEARTBEAT_CHANNEL_ID, dry_run, discord.nonce("heartbeat", now.astimezone(WIB).strftime("%Y%m%d%H")))
            event = state.claim_oldest_agent(value, profiles, now)
            state.save_state(storage, value)
            post = state.deserialize_post(event["post"]) if event else None
            thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]])) if event else None
            return build_wake_payload(agent_item(profiles[event["profile_id"]], post, thread_posts) if event and post else None)
        except Exception as exc:
            try: discord.post_text(format_fatal(now, str(exc)), HEARTBEAT_CHANNEL_ID, dry_run, discord.nonce("fatal", now.astimezone(WIB).strftime("%Y%m%d%H")))
            except Exception: pass
            raise


def submit_analysis_payload(payload: object, dry_run: bool | None = None) -> dict[str, object]:
    if type(payload) is not dict or not isinstance(payload.get("event_key"), str):
        raise ValueError("analysis submission requires an event_key")
    storage = state_path()
    storage.parent.mkdir(parents=True, exist_ok=True)
    dry_run = bool(dry_run) or os.environ.get("X_POST_WATCH_NO_POST") == "1"
    with (storage.parent / "run.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        value = state.load_state(storage)
        watches = config.load_watch_config(config_path())
        profiles = {profile.id: profile for profile in watches.profiles}
        profile_id = payload["event_key"].partition(":")[0]
        profile = profiles.get(profile_id)
        if profile is None or not profile.uses_llm:
            raise ValueError("analysis profile is not enabled")
        analysis = validate_submission(profile, payload)
        event = state.awaiting_analysis_event(value, analysis["event_key"])
        thread_posts = tuple(state.deserialize_post(item) for item in event.get("thread_posts", [event["post"]]))
        promotional = is_promotional(state.deserialize_post(event["post"]), thread_posts)
        if analysis.get("is_relevant") is False or promotional:
            if not promotional and requires_relevance(state.deserialize_post(event["post"]), thread_posts):
                raise ValueError("direct market disclosure must be relevant")
            state.discard_analysis(value, analysis["event_key"])
            state.save_state(storage, value)
            return {"submitted": True, "ignored": True, "delivered": 0}
        state.submit_analysis(value, analysis["event_key"], {key: item for key, item in analysis.items() if key not in {"event_key", "is_relevant"}})
        state.save_state(storage, value)
        stats = RunStats()
        now = datetime.now(WIB)
        while (event_index := _next_deliverable_index(value, profiles, now)) is not None:
            if not _deliver(value, profiles, event_index, dry_run, storage, stats):
                break
    return {"submitted": True, "delivered": stats.delivered}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    submit = subparsers.add_parser("submit-analysis")
    submit.add_argument("--json", required=True, dest="payload")
    arguments = parser.parse_args()
    try:
        if arguments.command == "submit-analysis":
            result = submit_analysis_payload(json.loads(arguments.payload))
        else:
            result = run()
    except Exception as exc:
        print(json.dumps({"wakeAgent": False, "error": " ".join(str(exc).split())[:180]}, ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False))
