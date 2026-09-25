"""Environment-only service configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    api_token: str
    admin_token: str
    bot_token_path: Path
    state_path: Path
    media_path: Path
    emoji_token: str | None = None

    @classmethod
    def from_environment(cls) -> "Config":
        required = ("DISCORD_DELIVERY_API_TOKEN", "DISCORD_DELIVERY_ADMIN_TOKEN",
                    "DISCORD_DELIVERY_BOT_TOKEN_PATH", "DISCORD_DELIVERY_STATE_PATH",
                    "DISCORD_DELIVERY_MEDIA_PATH")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise ValueError("missing Discord delivery configuration: " + ", ".join(missing))
        port = int(os.environ.get("DISCORD_DELIVERY_PORT", "9120"))
        if not 1 <= port <= 65535:
            raise ValueError("invalid Discord delivery port")
        api_token = os.environ["DISCORD_DELIVERY_API_TOKEN"]
        admin_token = os.environ["DISCORD_DELIVERY_ADMIN_TOKEN"]
        emoji_token = os.environ.get("DISCORD_DELIVERY_EMOJI_TOKEN") or None
        if api_token == admin_token or emoji_token in {api_token, admin_token}:
            raise ValueError("client, admin, and emoji tokens must differ")
        return cls(
            host=os.environ.get("DISCORD_DELIVERY_HOST", "127.0.0.1"), port=port,
            api_token=api_token, admin_token=admin_token,
            bot_token_path=Path(os.environ["DISCORD_DELIVERY_BOT_TOKEN_PATH"]),
            state_path=Path(os.environ["DISCORD_DELIVERY_STATE_PATH"]),
            media_path=Path(os.environ["DISCORD_DELIVERY_MEDIA_PATH"]),
            emoji_token=emoji_token,
        )
