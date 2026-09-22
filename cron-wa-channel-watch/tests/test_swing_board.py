from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from models import ChannelEvent, ChannelMedia
import swing_board


def technical_event(text: str = "#TechnicalReview\nTINS breakout resistance 4.600.") -> ChannelEvent:
    return ChannelEvent(
        channel_jid="120363419226413141@newsletter",
        message_id="technical-001",
        published_at=datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc),
        text=text,
        links=(),
        media=(ChannelMedia(kind="image", index=0, mime="image/jpeg"),),
        received_at=datetime(2026, 9, 21, 9, 31, tzinfo=timezone.utc),
    )


def technical_item(ticker: str | None) -> dict[str, object]:
    return {
        "title": "TINS: Breakout Resistance 4.600",
        "summary": "TINS menembus resistance 4.600.",
        "route": "id_stocks_swing",
        "ticker": ticker,
        "sentiment": "Bearish",
    }


def archived_image(tmp_path: Path) -> Path:
    image = tmp_path / "archive" / "media" / "chart.jpg"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"chart")
    return image


def test_single_ticker_technical_review_submits_social_chart_context(tmp_path):
    captured: dict[str, object] = {}

    def recording_run(arguments: list[str], payload: str):
        captured["arguments"] = arguments
        captured["payload"] = json.loads(payload)
        return SimpleNamespace(returncode=0, stdout='{"accepted":true,"board_pending":true}\n', stderr="")

    submission = swing_board.submit_chart_context(
        technical_event(),
        technical_item("TINS"),
        "All Swing text",
        archived_image(tmp_path),
        run=recording_run,
    )

    assert submission.accepted is True
    assert submission.board_pending is True
    assert captured["arguments"][-2:] == ["submit-source-event", "--stdin"]
    assert captured["payload"] == {
        "event_key": "120363419226413141@newsletter:technical-001",
        "source": "whatsapp",
        "kind": "social",
        "ticker": "TINS",
        "published_at": "2026-09-21T09:30:00+00:00",
        "source_url": "https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c",
        "all_content": "All Swing text",
        "source_title": "TINS: Breakout Resistance 4.600",
        "source_status": "Bearish",
        "plan": None,
        "media_path": str(archived_image(tmp_path)),
        "media_urls": [],
    }


def test_multiple_tickers_or_missing_image_never_submits_board(tmp_path):
    image = archived_image(tmp_path)

    assert swing_board.is_eligible(technical_event(), technical_item("TINS"), None) is False
    assert swing_board.is_eligible(technical_event("#TechnicalReview\nTINS dan ANTM breakout."), technical_item("TINS"), image) is False
