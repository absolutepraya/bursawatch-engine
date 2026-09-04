from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


@dataclass(frozen=True)
class DiscordChannel:
    key: str
    channel_id: str
    description: str


@dataclass(frozen=True)
class Profile:
    id: str
    enabled: bool
    source: str
    profile_url: str
    handle: str
    display_name: str
    platform_emoji: str
    emoji: str
    discord_channels: tuple[DiscordChannel, ...]
    forward_post: bool
    forward_reel: bool
    forward_media: bool
    enable_llm_title: bool
    enable_llm_summary: bool
    enable_llm_routing: bool
    enable_llm_relevance_filter: bool
    additional_prompt_instruction: str
    max_items_per_poll: int
    ocr_languages: tuple[str, ...]
    ocr_min_confidence: float
    max_reel_frames: int

    @property
    def feed_url(self) -> str:
        return f"http://127.0.0.1:1200/instagram/user/{self.handle}?format=json"

    @property
    def uses_llm(self) -> bool:
        return any((
            self.enable_llm_title,
            self.enable_llm_summary,
            self.enable_llm_routing,
            self.enable_llm_relevance_filter,
        ))

    def channel_for(self, key: str) -> DiscordChannel:
        for channel in self.discord_channels:
            if channel.key == key:
                return channel
        raise KeyError(key)


@dataclass(frozen=True)
class WatchConfig:
    version: int
    profiles: tuple[Profile, ...]


class PublicationKind(StrEnum):
    POST = "post"
    REEL = "reel"


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


@dataclass(frozen=True)
class SourceMedia:
    url: str
    kind: MediaKind
    index: int


@dataclass(frozen=True)
class SourcePost:
    profile_id: str
    publication_id: str
    url: str
    published_at: datetime
    caption_html: str
    kind: PublicationKind
    media: tuple[SourceMedia, ...]


@dataclass(frozen=True)
class DownloadedAsset:
    source: SourceMedia
    path: Path
    sha256: str
    size_bytes: int
    content_type: str


@dataclass(frozen=True)
class DownloadLimits:
    max_asset_bytes: int = 25 * 1024 * 1024
    max_publication_bytes: int = 128 * 1024 * 1024
    timeout_seconds: int = 30


@dataclass(frozen=True)
class DownloadedPublication:
    assets: tuple[DownloadedAsset, ...]
    media_root: Path
