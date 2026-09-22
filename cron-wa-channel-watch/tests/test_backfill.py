from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

import archive
from models import ChannelEvent, ChannelMedia


MODULE_PATH = Path(__file__).resolve().parents[1] / "bin" / "bursawatch-wa-channel-backfill.py"
SPEC = importlib.util.spec_from_file_location("wa_backfill", MODULE_PATH)
assert SPEC and SPEC.loader
wa_backfill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wa_backfill)


def source(tmp_path: Path) -> tuple[Path, ChannelEvent]:
    root = tmp_path / "archive"
    staging = tmp_path / "staging"
    staging.mkdir()
    staged = staging / "chart.jpg"
    staged.write_bytes(b"chart")
    event = ChannelEvent(
        channel_jid="120363419226413141@newsletter",
        message_id="wa-swing-1",
        published_at=datetime(2026, 9, 22, 4, 26, tzinfo=timezone.utc),
        text="#TechnicalReview\nTINS breakout resistance 4.600.",
        links=(),
        media=(ChannelMedia(kind="image", index=0, mime="image/jpeg", path=str(staged)),),
        received_at=datetime(2026, 9, 22, 4, 27, tzinfo=timezone.utc),
    )
    archive.ensure(root, wa_backfill.BRI_PROFILE_ID, event, None, staging_root=staging)
    return root, event


def manifest(tmp_path: Path, event: ChannelEvent, current: str) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({
        "manifest_version": 1,
        "items": [{
            "discord_channel_id": wa_backfill.BRI_SWING_CHANNEL_ID,
            "discord_message_id": "123456789012345678",
            "current_sha256": hashlib.sha256(current.encode()).hexdigest(),
            "event_key": event.event_key,
            "title": "TINS: Breakout Resistance 4.600",
            "reasons": "TINS bertahan di atas support.",
            "sentiment": "Bullish",
            "ticker": "TINS",
        }],
    }), encoding="utf-8")
    return path


def test_backfill_plan_is_archive_backed_and_read_only(tmp_path):
    root, event = source(tmp_path)
    current = "old BRI message"
    result = wa_backfill.plan(root, manifest(tmp_path, event, current))
    assert result["count"] == 1
    assert result["operations"][0]["message_action"] == "edit-content-in-place"
    assert (root / "media").is_dir()


def test_backfill_apply_requires_guard_and_edits_existing_message(tmp_path, monkeypatch):
    root, event = source(tmp_path)
    current = "old BRI message"
    path = manifest(tmp_path, event, current)
    with monkeypatch.context() as context:
        context.delenv("WHATSAPP_CHANNEL_WATCH_ALLOW_BACKEDIT", raising=False)
        try:
            wa_backfill.apply(root, path)
        except RuntimeError as exc:
            assert "ALLOW_BACKEDIT" in str(exc)
        else:
            raise AssertionError("backfill apply must require the environment guard")

    monkeypatch.setenv("WHATSAPP_CHANNEL_WATCH_ALLOW_BACKEDIT", "1")
    monkeypatch.setattr(wa_backfill.discord, "get_message", lambda *_args: {"content": current})
    monkeypatch.setattr(
        wa_backfill.swing_board,
        "submit_chart_context",
        lambda *_args, **_kwargs: wa_backfill.swing_board.BoardSubmission(
            True,
            "https://discord.com/channels/940285152335110204/999",
            False,
        ),
    )
    edits = []
    monkeypatch.setattr(wa_backfill.discord, "edit_message_content", lambda *args, **kwargs: edits.append(args) or True)
    result = wa_backfill.apply(root, path)
    assert result["results"][0]["status"] == "edited"
    assert edits and edits[0][1] == "123456789012345678"
