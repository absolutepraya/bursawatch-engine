from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Callable, Protocol

from classification import is_technical_review
from models import ChannelEvent


BRI_CHANNEL_URL = "https://www.whatsapp.com/channel/0029VbAjdnb60eBhwVdJxj1c"
_TICKER_RE = re.compile(r"^[A-Z]{2,5}$")
_SOURCE_TICKER_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{2,5}(?![A-Z0-9])")
_IGNORED_SOURCE_TOKENS = {"IDX", "IDR", "WIB"}


class BoardRunner(Protocol):
    def __call__(self, arguments: list[str], payload: str) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class BoardSubmission:
    accepted: bool
    board_url: str | None
    board_pending: bool


def _leading_source_tickers(text: str) -> set[str]:
    """Read only the declared ticker group immediately after the review tag."""
    lines = text.splitlines()
    tag_seen = False
    for line in lines:
        if not tag_seen:
            if is_technical_review(line):
                tag_seen = True
            continue
        declared = line.split(">", 1)[0] if ">" in line else line
        candidates = {
            token for token in _SOURCE_TICKER_RE.findall(declared) if token not in _IGNORED_SOURCE_TOKENS
        }
        if candidates:
            return candidates
    return set()


def is_eligible(event: ChannelEvent, item: dict[str, object], archived_image: Path | None) -> bool:
    ticker = item.get("ticker")
    return (
        is_technical_review(event.text)
        and item.get("route") == "id_stocks_swing"
        and isinstance(ticker, str)
        and _TICKER_RE.fullmatch(ticker) is not None
        and _leading_source_tickers(event.text) == {ticker}
        and archived_image is not None
        and archived_image.is_absolute()
        and archived_image.is_file()
        and not archived_image.is_symlink()
    )


def _default_runner(arguments: list[str], payload: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )


def _arguments() -> list[str]:
    wrapper = os.environ.get(
        "WHATSAPP_CHANNEL_WATCH_SWING_BOARD_SCRIPT",
        str(Path.home() / ".hermes/scripts/bursawatch-dc-swing-board.sh"),
    )
    return [wrapper, "submit-source-event", "--stdin"]


def submit_chart_context(
    event: ChannelEvent,
    item: dict[str, object],
    all_content: str,
    archived_image: Path,
    *,
    run: BoardRunner = _default_runner,
) -> BoardSubmission:
    if not is_eligible(event, item, archived_image):
        raise ValueError("technical review is not eligible for Board Chart context")
    sentiment = item.get("sentiment")
    if not isinstance(sentiment, str) or sentiment not in {"Bullish", "Bearish", "Sideways"}:
        raise ValueError("technical review Board context requires a validated sentiment")
    payload = {
        "event_key": event.event_key,
        "source": "whatsapp",
        "kind": "social",
        "ticker": item["ticker"],
        "published_at": event.published_at.isoformat(),
        "source_url": BRI_CHANNEL_URL,
        "all_content": all_content,
        "source_title": item["title"],
        "source_status": sentiment,
        "plan": None,
        "media_path": str(archived_image),
        "media_urls": [],
    }
    result = run(_arguments(), json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    if result.returncode != 0:
        raise RuntimeError("Swing Board source-event submission failed")
    try:
        acknowledgement = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("Swing Board acknowledgement is invalid") from exc
    if type(acknowledgement) is not dict or type(acknowledgement.get("accepted")) is not bool:
        raise ValueError("Swing Board acknowledgement is invalid")
    board_url = acknowledgement.get("board_url")
    board_pending = acknowledgement.get("board_pending", False)
    if board_url is not None and not isinstance(board_url, str):
        raise ValueError("Swing Board acknowledgement is invalid")
    if type(board_pending) is not bool:
        raise ValueError("Swing Board acknowledgement is invalid")
    return BoardSubmission(
        accepted=acknowledgement["accepted"],
        board_url=board_url,
        board_pending=board_pending,
    )
