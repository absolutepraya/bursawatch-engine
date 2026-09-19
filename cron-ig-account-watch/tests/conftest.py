import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"))


@pytest.fixture
def profile_payload() -> dict:
    return {
        "id": "beyondthefundamental",
        "enabled": True,
        "source": "rsshub",
        "profile_url": "https://www.instagram.com/beyondthefundamental",
        "handle": "beyondthefundamental",
        "display_name": "Beyond thy Fundamental",
        "platform_emoji": "📸",
        "emoji": "",
        "discord_channels": [
            {
                "key": "macro_news",
                "channel_id": "1531655369884045382",
                "description": "Broad economic, business, market, sector, and cross-asset analysis.",
            },
            {
                "key": "id_stocks_news",
                "channel_id": "1525102508714889257",
                "description": "Direct IDX-listed company, earnings, corporate action, fundamental, and valuation analysis.",
            },
        ],
        "forward_post": True,
        "forward_reel": True,
        "forward_media": True,
        "enable_llm_title": True,
        "enable_llm_summary": True,
        "enable_llm_routing": True,
        "enable_llm_relevance_filter": True,
        "additional_prompt_instruction": "Always use the caption and all carousel OCR together. Preserve the account's own thesis.",
        "max_items_per_poll": 20,
        "ocr_languages": ["ind", "eng"],
        "ocr_min_confidence": 0.70,
        "max_reel_frames": 5,
    }


@pytest.fixture
def config_path(tmp_path: Path, profile_payload: dict) -> Path:
    path = tmp_path / "watches.json"
    path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    return path
