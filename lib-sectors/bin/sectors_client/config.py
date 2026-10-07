"""Explicit package-local credential loading. Never shell-source environment files."""
from dataclasses import dataclass, field
from pathlib import Path
import re
from .models import ORIGIN, ValidationError


@dataclass(frozen=True)
class Config:
    store_path: Path
    caller: str
    billing_window: str
    caller_limit: int | None = None
    host_limit: int = 1000
    api_key: str = field(default='', repr=False)
    cache_only: bool = True
    origin: str = ORIGIN
    timeout_seconds: float = 15
    max_bytes: int = 8_000_000
    user_agent: str = 'Bursawatch-Sectors/1.0'
    lease_seconds: float = 60
    wait_seconds: float = 2
    max_attempts: int = 2

    def __post_init__(self):
        object.__setattr__(self, 'store_path', Path(self.store_path))
        if self.origin != ORIGIN:
            raise ValidationError('Sectors API origin is fixed')
        for value in (self.caller, self.billing_window):
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value):
                raise ValidationError('invalid coordination identity')
        if self.caller_limit is None:
            # No caller cap: only the shared host ceiling applies.
            object.__setattr__(self, 'caller_limit', self.host_limit)
        for value in (self.caller_limit, self.host_limit, self.max_bytes, self.max_attempts):
            if type(value) is not int or value <= 0:
                raise ValidationError('invalid positive limit')
        if self.host_limit > 1000 or self.caller_limit > self.host_limit:
            raise ValidationError('credit limit exceeds host allowance')
        if not 0 < self.timeout_seconds <= 120 or not 0 < self.lease_seconds <= 3600 or not 0 <= self.wait_seconds <= 60:
            raise ValidationError('invalid bounded timeout')
        if not self.user_agent or '\n' in self.user_agent or '\r' in self.user_agent:
            raise ValidationError('invalid User-Agent')
        if not isinstance(self.api_key, str) or '\n' in self.api_key or '\r' in self.api_key:
            raise ValidationError('invalid provider key')
        if not self.cache_only and not self.api_key:
            raise ValidationError('provider key required for network mode')

    @classmethod
    def from_env_file(cls, path, **kwargs):
        key = None
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            name, sep, value = line.partition('=')
            if name.strip() != 'SECTORS_API_KEY':
                continue
            if not sep or key is not None:
                raise ValidationError('invalid provider credential file')
            value = value.strip()
            if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                value = value[1:-1]
            if not value or any(c.isspace() for c in value) or '$' in value or '`' in value:
                raise ValidationError('invalid provider credential value')
            key = value
        if key is None:
            raise ValidationError('provider credential is missing')
        return cls(api_key=key, **kwargs)
