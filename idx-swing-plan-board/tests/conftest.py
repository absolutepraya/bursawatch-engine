import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
# The board contract intentionally owns the short module name ``calendar``.
# Pytest may have already imported the standard-library module during startup.
sys.modules.pop("calendar", None)


def example_buy_event(
    key: str = "phintraco:1444713822:33655", ticker: str = "SCMA"
):
    from models import SourceEvent

    return SourceEvent.from_json(
        {
            "event_key": key,
            "source": "phintraco",
            "kind": "buy",
            "ticker": ticker,
            "published_at": "2026-09-19T09:05:00+07:00",
            "source_url": "https://t.me/phintraprofits/33655",
            "all_content": f"### <:phintraco:1> {ticker.upper()}: Buy",
            "source_title": f"{ticker.upper()}: Trading Buy",
            "source_status": "New setup",
            "plan": {
                "entry": "208 to 212",
                "stop_loss": "<200",
                "targets": ["230"],
            },
            "media_path": None,
            "media_urls": [],
        }
    )


def social_event(key: str, ticker: str, source_title: str):
    from models import SourceEvent

    return SourceEvent.from_json(
        {
            "event_key": key,
            "source": "x",
            "kind": "social",
            "ticker": ticker,
            "published_at": "2026-09-19T09:05:00+07:00",
            "source_url": "https://x.com/marketwriter/status/101",
            "all_content": source_title,
            "source_title": source_title,
            "source_status": None,
            "plan": None,
            "media_path": None,
            "media_urls": [],
        }
    )
