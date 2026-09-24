"""Client-side immutable media download model."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaDownload:
    data: bytes
    content_type: str
    filename: str
    kind: str
    sha256: str
