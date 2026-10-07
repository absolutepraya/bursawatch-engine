"""Explicit package credential loading. Importing never reads an environment."""
from dataclasses import dataclass, field
from pathlib import Path
import math
import os
import stat

from .models import ChartImgError


@dataclass(frozen=True)
class ChartImgConfig:
    api_key: str = field(repr=False)
    timeout_seconds: float = 30.0
    max_bytes: int = 8_000_000

    def __post_init__(self):
        if not isinstance(self.api_key, str) or not self.api_key.strip() or any(ord(c) < 33 or ord(c) > 126 for c in self.api_key):
            raise ChartImgError('invalid_config')
        if (not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(self.timeout_seconds)
                or not 0 < self.timeout_seconds <= 90 or type(self.max_bytes) is not int
                or not 0 < self.max_bytes <= 8_000_000):
            raise ChartImgError('invalid_config')


def load_config(path: Path | str) -> ChartImgConfig:
    """Read only CHART_IMG_API_KEY from the explicit file, without shell evaluation."""
    try:
        with Path(path).open(encoding='utf-8') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
                raise ChartImgError('invalid_config')
            text = stream.read(64_001)
            if len(text) > 64_000:
                raise ChartImgError('invalid_config')
        values = []
        for line in text.splitlines():
            key, separator, value = line.strip().partition('=')
            if separator and key == 'CHART_IMG_API_KEY':
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                    value = value[1:-1]
                values.append(value)
        if len(values) != 1:
            raise ChartImgError('invalid_config')
        return ChartImgConfig(values[0])
    except Exception:
        raise ChartImgError('invalid_config') from None
