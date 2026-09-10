from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class DiscordChannel:
    key: str
    channel_id: str
    description: str


@dataclass(frozen=True)
class ChannelProfile:
    id: str
    enabled: bool
    channel_jid: str
    channel_url: str
    display_name: str
    discord_channels: tuple[DiscordChannel, ...]
    forward_media: bool
    enable_llm_title: bool
    enable_llm_summary: bool
    enable_llm_routing: bool
    enable_llm_relevance_filter: bool
    relevance_scope: str
    additional_prompt_instruction: str
    max_items_per_poll: int

    @property
    def uses_llm(self) -> bool:
        return any(
            (
                self.enable_llm_title,
                self.enable_llm_summary,
                self.enable_llm_routing,
                self.enable_llm_relevance_filter,
            )
        )

    def channel_for(self, key: str) -> DiscordChannel:
        for channel in self.discord_channels:
            if channel.key == key:
                return channel
        raise KeyError(key)


@dataclass(frozen=True)
class WatchConfig:
    version: int
    profiles: tuple[ChannelProfile, ...]


@dataclass(frozen=True)
class ChannelMedia:
    kind: str
    index: int
    mime: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class ChannelEvent:
    channel_jid: str
    message_id: str
    published_at: datetime
    text: str
    links: tuple[str, ...]
    media: tuple[ChannelMedia, ...]
    received_at: datetime

    @property
    def event_key(self) -> str:
        return f"{self.channel_jid}:{self.message_id}"
