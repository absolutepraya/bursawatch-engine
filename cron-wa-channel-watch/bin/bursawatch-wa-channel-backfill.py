#!/usr/bin/env python3
"""Plan and apply guarded edits for already-delivered BRI WhatsApp Swing posts.

This maintenance tool never replays the WhatsApp queue and never creates an
All Swing message. It only edits message IDs named by an operator manifest,
after the corresponding immutable archive record and image have been checked.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import archive
import discord
from models import ChannelEvent, ChannelMedia
import swing_board
import render


BRI_PROFILE_ID = "bri-danareksa-sekuritas"
BRI_SWING_CHANNEL_ID = "1525102458253217803"
BRI_EMOJI_IDS = {"1549256273109848124", "1551797903927025797"}
BRI_LEGACY_EMOJI = ":bridanareksa:"
MANIFEST_VERSION = 1
_ID_RE = re.compile(r"^[0-9]{15,22}$")
_TICKER_RE = re.compile(r"^[A-Z]{2,5}$")
_HEADING_RE = re.compile(
    r"^###\s+(?:(?:<:[^:>]+:(?:"
    + "|".join(BRI_EMOJI_IDS)
    + r")>)|:bridanareksa:)\s+(?P<title>.+)$",
    re.MULTILINE,
)
_SENTIMENT_RE = re.compile(r"^(?:\*\*)?(?:Sentiment|Status)(?:\*\*)?:\s*(Bullish|Bearish|Sideways|Overweight|Underweight|Buy|Sell|Hold|Neutral|On track)", re.MULTILINE | re.IGNORECASE)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_new(path: Path, payload: object) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json(payload), encoding="utf-8")
    path.chmod(0o600)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fetch_messages(channel_id: str, limit: int, *, client: object | None = None) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    before: str | None = None
    while len(messages) < limit:
        page = discord.list_messages(
            channel_id, limit=min(100, limit - len(messages)), before=before, client=client
        )
        if not page:
            break
        messages.extend(page)
        next_before = page[-1].get("id")
        if not isinstance(next_before, str) or next_before == before:
            break
        before = next_before
        if len(page) < 100:
            break
    return messages[:limit]


def _candidate(message: dict[str, object], channel_id: str) -> dict[str, object] | None:
    message_id = message.get("id")
    content = message.get("content")
    if not isinstance(message_id, str) or not _ID_RE.fullmatch(message_id) or not isinstance(content, str):
        return None
    if not (
        any(f":{emoji_id}>" in content for emoji_id in BRI_EMOJI_IDS)
        or BRI_LEGACY_EMOJI in content
    ):
        return None
    if "whatsapp.com/channel/" not in content:
        return None
    heading = _HEADING_RE.search(content)
    title = heading.group("title").strip() if heading else None
    sentiment_match = _SENTIMENT_RE.search(content)
    sentiment = sentiment_match.group(1).title() if sentiment_match else None
    ticker = title.split(":", 1)[0].strip() if title and ":" in title else None
    return {
        "discord_channel_id": channel_id,
        "discord_message_id": message_id,
        "current_sha256": _sha256(content),
        "current_content": content,
        "suggested_title": title,
        "suggested_ticker": ticker if isinstance(ticker, str) and _TICKER_RE.fullmatch(ticker) else None,
        "suggested_sentiment": sentiment if sentiment in {"Bullish", "Bearish", "Sideways"} else None,
    }


def discover(channel_id: str, limit: int, *, client: object | None = None) -> dict[str, object]:
    candidates = [candidate for message in _fetch_messages(channel_id, limit, client=client) if (candidate := _candidate(message, channel_id))]
    return {
        "manifest_version": MANIFEST_VERSION,
        "purpose": "bri-whatsapp-swing-backfill",
        "channel_id": channel_id,
        "generated_at": datetime.now().astimezone().isoformat(),
        "items": candidates,
    }


def _manifest_items(payload: object) -> list[dict[str, object]]:
    if type(payload) is not dict or payload.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError("backfill manifest version is invalid")
    items = payload.get("items")
    if type(items) is not list or not items:
        raise ValueError("backfill manifest must contain one or more items")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in items:
        if type(item) is not dict:
            raise ValueError("backfill item is invalid")
        message_id = item.get("discord_message_id")
        event_key = item.get("event_key")
        if not isinstance(message_id, str) or not _ID_RE.fullmatch(message_id) or message_id in seen:
            raise ValueError("backfill item has a duplicate or invalid Discord message ID")
        if not isinstance(event_key, str) or not event_key:
            raise ValueError(f"backfill item {message_id} is missing event_key")
        for key in ("title", "reasons", "sentiment", "ticker"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"backfill item {message_id} is missing {key}")
        if item["sentiment"] not in {"Bullish", "Bearish", "Sideways"}:
            raise ValueError(f"backfill item {message_id} has an invalid sentiment")
        if not _TICKER_RE.fullmatch(str(item["ticker"])):
            raise ValueError(f"backfill item {message_id} has an invalid ticker")
        if "current_sha256" in item and not isinstance(item["current_sha256"], str):
            raise ValueError(f"backfill item {message_id} has an invalid content guard")
        seen.add(message_id)
        result.append(item)
    return result


def _event_and_image(root: Path, event_key: str) -> tuple[ChannelEvent, Path]:
    records = archive.query(root, profile_id=BRI_PROFILE_ID, event_key=event_key, limit=2)
    if len(records) != 1:
        raise ValueError(f"archive event is missing or ambiguous: {event_key}")
    data = records[0].data
    media_items = data.get("media")
    if type(media_items) is not list:
        raise ValueError(f"archive media is invalid: {event_key}")
    captured = [item for item in media_items if type(item) is dict and item.get("kind") == "image" and item.get("capture_status") == "captured"]
    if len(captured) != 1:
        raise ValueError(f"archive event must contain exactly one captured image: {event_key}")
    relative = captured[0].get("archive_path")
    if not isinstance(relative, str):
        raise ValueError(f"archive image path is invalid: {event_key}")
    image = (root / relative).resolve(strict=True)
    if image.is_symlink() or not image.is_file():
        raise ValueError(f"archive image is unavailable: {event_key}")
    media = tuple(
        ChannelMedia(
            kind=str(item.get("kind")),
            index=int(item.get("index", index)),
            mime=item.get("mime") if isinstance(item.get("mime"), str) else None,
            path=str((root / item["archive_path"]).resolve()) if item.get("capture_status") == "captured" and isinstance(item.get("archive_path"), str) else None,
        )
        for index, item in enumerate(media_items)
        if type(item) is dict
    )
    event = ChannelEvent(
        channel_jid=str(data["channel_jid"]),
        message_id=str(data["message_id"]),
        published_at=datetime.fromisoformat(str(data["published_at"])),
        text=str(data["text"]),
        links=tuple(str(link) for link in data.get("links", [])),
        media=media,
        received_at=datetime.fromisoformat(str(data["received_at"])),
    )
    return event, image


def _prepared(root: Path, item: dict[str, object]) -> dict[str, object]:
    event, image = _event_and_image(root, str(item["event_key"]))
    if not swing_board.is_eligible(
        event,
        {"route": "id_stocks_swing", "ticker": item["ticker"], "title": item["title"], "sentiment": item["sentiment"]},
        image,
    ):
        raise ValueError(f"archive source is not an eligible single-ticker BRI technical review: {item['event_key']}")
    rendered = render.render_post(
        _profile_for_render(),
        event,
        title=str(item["title"]),
        summary=str(item["reasons"]),
        route="id_stocks_swing",
        sentiment=str(item["sentiment"]),
    )
    if len(rendered) != 1:
        raise ValueError(f"backfill message would exceed one Discord message: {item['discord_message_id']}")
    return {"item": item, "event": event, "image": image, "content": rendered[0]}


def _profile_for_render():
    from config import ChannelProfile, DiscordChannel, StatusEmojis

    return ChannelProfile(
        id=BRI_PROFILE_ID,
        enabled=True,
        mode="forward",
        channel_jid="placeholder@newsletter",
        channel_url=swing_board.BRI_CHANNEL_URL,
        display_name="BRI Danareksa Sekuritas",
        emoji="<:bridanareksa:1551797903927025797>",
        status_emojis=StatusEmojis(
            up="<:up:1531285100346740766>",
            down="<:down:1531285063986053200>",
            hold="<:hold:1531284248235868333>",
        ),
        discord_channels=(DiscordChannel("id_stocks_swing", BRI_SWING_CHANNEL_ID, "IDX swing"),),
        forward_media=True,
        enable_llm_title=True,
        enable_llm_summary=True,
        enable_llm_routing=True,
        enable_llm_relevance_filter=True,
        relevance_scope="financial_market",
        additional_prompt_instruction="",
        max_items_per_poll=20,
    )


def plan(root: Path, manifest_path: Path) -> dict[str, object]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    prepared = [_prepared(root, item) for item in _manifest_items(payload)]
    operations = [
        {
            "discord_channel_id": str(value["item"]["discord_channel_id"]),
            "discord_message_id": str(value["item"]["discord_message_id"]),
            "event_key": str(value["item"]["event_key"]),
            "archive_image": str(value["image"]),
            "board_action": "submit-or-reconcile-chart-context",
            "message_action": "edit-content-in-place",
            "proposed_content": value["content"],
        }
        for value in prepared
    ]
    return {"manifest_version": MANIFEST_VERSION, "mode": "plan", "count": len(operations), "operations": operations}


def apply(root: Path, manifest_path: Path, *, client: object | None = None) -> dict[str, object]:
    if os.environ.get("WHATSAPP_CHANNEL_WATCH_ALLOW_BACKEDIT") != "1":
        raise RuntimeError("set WHATSAPP_CHANNEL_WATCH_ALLOW_BACKEDIT=1 for the explicitly approved back-edit")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    prepared = [_prepared(root, item) for item in _manifest_items(payload)]
    results: list[dict[str, object]] = []
    for value in prepared:
        item = value["item"]
        channel_id = str(item["discord_channel_id"])
        message_id = str(item["discord_message_id"])
        current = discord.get_message(channel_id, message_id, client=client)
        content = current.get("content") if current else None
        if not isinstance(content, str):
            raise RuntimeError(f"Discord message is unavailable: {channel_id}/{message_id}")
        expected_hash = item.get("current_sha256")
        if isinstance(expected_hash, str) and _sha256(content) != expected_hash:
            raise RuntimeError(f"Discord message changed since plan: {channel_id}/{message_id}")
        acknowledgement = swing_board.submit_chart_context(
            value["event"],
            {
                "route": "id_stocks_swing",
                "ticker": item["ticker"],
                "title": item["title"],
                "summary": item["reasons"],
                "sentiment": item["sentiment"],
            },
            str(value["content"]),
            value["image"],
        )
        if not acknowledgement.accepted:
            raise RuntimeError(f"Board rejected backfill event: {item['event_key']}")
        if acknowledgement.board_pending or not acknowledgement.board_url:
            results.append({"message_id": message_id, "event_key": item["event_key"], "status": "board-pending"})
            continue
        final = render.render_post(
            _profile_for_render(),
            value["event"],
            title=str(item["title"]),
            summary=str(item["reasons"]),
            route="id_stocks_swing",
            sentiment=str(item["sentiment"]),
            board_url=acknowledgement.board_url,
        )
        if len(final) != 1 or not discord.edit_message_content(channel_id, message_id, final[0], client=client):
            raise RuntimeError(f"Discord message edit failed: {channel_id}/{message_id}")
        results.append({"message_id": message_id, "event_key": item["event_key"], "status": "edited", "board_url": acknowledgement.board_url})
    return {"manifest_version": MANIFEST_VERSION, "mode": "apply", "count": len(results), "results": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path(
            os.environ.get(
                "WHATSAPP_CHANNEL_WATCH_ARCHIVE_ROOT",
                str(Path.home() / ".hermes/state/whatsapp-channel-watch/archive"),
            )
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover_parser = subparsers.add_parser("discover")
    discover_parser.add_argument("--channel-id", default=BRI_SWING_CHANNEL_ID)
    discover_parser.add_argument("--limit", type=int, default=100)
    discover_parser.add_argument("--output", type=Path)
    for name in ("plan", "apply"):
        command = subparsers.add_parser(name)
        command.add_argument("--manifest", required=True, type=Path)
        if name == "apply":
            command.add_argument("--apply", action="store_true", required=True, help="confirm the guarded Discord and Board mutations")
    args = parser.parse_args(argv)
    if args.command == "discover":
        payload = discover(args.channel_id, args.limit)
        if args.output:
            _write_new(args.output, payload)
        else:
            print(_json(payload), end="")
        return 0
    result = plan(args.archive_root, args.manifest) if args.command == "plan" else apply(args.archive_root, args.manifest)
    print(_json(result), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"backfill: {exc}", file=sys.stderr)
        raise SystemExit(2)
