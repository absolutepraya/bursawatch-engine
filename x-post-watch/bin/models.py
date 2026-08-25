from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True)
class DiscordChannel:
    key: str
    channel_id: str
    description: str


@dataclass(frozen=True)
class ThreadHandling:
    mode: str
    max_posts: int
    max_age_minutes: int
    settle_minutes: int


@dataclass(frozen=True)
class Profile:
    id: str
    enabled: bool
    profile_url: str
    handle: str
    display_name: str
    twitter_emoji: str
    emoji: str
    discord_channels: tuple[DiscordChannel, ...]
    forward_normal_post: bool
    forward_quote_post: bool
    forward_reply: bool
    forward_repost: bool
    forward_media: bool
    enable_llm_title: bool
    enable_llm_summary: bool
    enable_llm_routing: bool
    enable_llm_relevance_filter: bool
    additional_prompt_instruction: str
    max_items_per_poll: int
    thread_handling: ThreadHandling

    @property
    def feed_url(self) -> str:
        return f"http://127.0.0.1:1200/twitter/user/{self.handle}?format=json"

    @property
    def uses_llm(self) -> bool:
        return self.enable_llm_title or self.enable_llm_summary or self.enable_llm_routing or self.enable_llm_relevance_filter

    def channel_for(self, key: str) -> DiscordChannel:
        for channel in self.discord_channels:
            if channel.key == key:
                return channel
        raise KeyError(key)


@dataclass(frozen=True)
class WatchConfig:
    version: int
    profiles: tuple[Profile, ...]


class PostKind(StrEnum):
    NORMAL = "normal"
    QUOTE = "quote"
    REPLY = "reply"
    REPOST = "repost"
    ARTICLE = "article"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class SourceMedia:
    url: str
    index: int


@dataclass(frozen=True)
class SourcePost:
    profile_id: str
    post_id: str
    url: str
    published_at: datetime
    content_html: str
    kind: PostKind
    quoted_url: str | None
    quoted_content_html: str | None
    media: tuple[SourceMedia, ...]
    quoted_media: tuple[SourceMedia, ...]
    related_url: str | None = None
    quoted_article_url: str | None = None
    quoted_article_label: str | None = None
