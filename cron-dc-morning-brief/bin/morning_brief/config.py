"""Explicit offline morning owner configuration, separate from provider credentials."""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class MorningConfig:
    run_store_path: Path
    sectors_store_path: Path
    mode: str = 'cache_only'

    def __post_init__(self):
        object.__setattr__(self, 'run_store_path', Path(self.run_store_path))
        object.__setattr__(self, 'sectors_store_path', Path(self.sectors_store_path))
        if self.run_store_path.resolve() == self.sectors_store_path.resolve():
            raise ValueError('morning and provider stores must be separate')
        if self.mode not in {'cache_only', 'synthetic_preview'}:
            raise ValueError('only explicit offline modes supported')

    @classmethod
    def from_mapping(cls, fields: Mapping):
        if set(fields) - {'run_store_path', 'sectors_store_path', 'mode'}:
            raise ValueError('unknown morning configuration field')
        return cls(**fields)
