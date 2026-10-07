import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib-bursawatch-discord-delivery" / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib-bursawatch-control" / "bin"))


@pytest.fixture
def profile_payload() -> dict:
    return {
        "id": "kutekians",
        "enabled": True,
        "profile_url": "https://x.com/Kutekians",
        "handle": "Kutekians",
        "display_name": "Almer Sad, CFA",
        "twitter_emoji": "<:twitter:1531672630602498129>",
        "emoji": "<:kutekians:1531673483459821729>",
        "discord_channels": [{
            "key": "macro_news",
            "channel_id": "1531655369884045382",
            "description": "Broad economic, business, market, sector, and cross-asset analysis.",
        }],
        "forward_normal_post": True,
        "forward_quote_post": True,
        "forward_reply": False,
        "forward_repost": False,
        "forward_media": True,
        "media_policy": "all",
        "enable_llm_title": False,
        "enable_llm_summary": False,
        "enable_llm_routing": False,
        "enable_llm_relevance_filter": True,
        "additional_prompt_instruction": "",
        "max_items_per_poll": 50,
        "thread_handling": {
            "mode": "self_chain",
            "max_posts": 10,
            "max_age_minutes": 240,
            "settle_minutes": 60,
        },
    }


@pytest.fixture
def config_path(tmp_path: Path, profile_payload: dict) -> Path:
    path = tmp_path / "watches.json"
    path.write_text(json.dumps({"version": 1, "profiles": [profile_payload]}), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def isolated_news_quotes(monkeypatch):
    import render
    monkeypatch.setattr(render.news_format, "get_market_snapshot", lambda *args: None)
    monkeypatch.setattr(render.news_format, "get_company_context", lambda *args: None)
