"""Immutable rendering identity and byte validation, without market-data inference."""
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
import warnings
from typing import Mapping

from PIL import Image


class ChartImgError(Exception):
    """Only controlled codes cross the provider boundary; no raw error text."""
    def __init__(self, code: str, *, retry_at: datetime | None = None):
        self.code = code
        self.retry_at = retry_at
        super().__init__(code)


def aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ChartImgError('invalid_timestamp')
    return value.astimezone(timezone.utc)


def canonical(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        raise ChartImgError('invalid_request') from None


@dataclass(frozen=True)
class RenderRequest:
    profile_revision: str
    layout_revision: str
    symbol: str
    interval: str
    time_range: str
    cutoff: datetime
    layout_id: str | None = None
    width: int = 800
    height: int = 600
    options: Mapping | str | None = field(default=None, repr=False)

    def __post_init__(self):
        for revision in (self.profile_revision, self.layout_revision):
            if not isinstance(revision, str) or not revision.strip() or len(revision) > 200:
                raise ChartImgError('invalid_request')
        if not isinstance(self.symbol, str) or not re.fullmatch(r'[A-Za-z0-9_:.!-]{1,100}', self.symbol):
            raise ChartImgError('invalid_request')
        if self.layout_id is not None and (not isinstance(self.layout_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', self.layout_id)):
            raise ChartImgError('invalid_request')
        if self.interval not in {'1', '3', '5', '15', '30', '45', '60', '120', '180', '240', '1D', '1W', '1M'}:
            raise ChartImgError('invalid_request')
        if self.time_range not in {'1D', '5D', '1M', '3M', '6M', 'YTD', '1Y', '5Y', 'ALL'}:
            raise ChartImgError('invalid_request')
        if any(type(x) is not int or not 1 <= x <= 4096 for x in (self.width, self.height)) or self.width * self.height > 16_000_000:
            raise ChartImgError('invalid_request')
        object.__setattr__(self, 'cutoff', aware(self.cutoff))
        try:
            options = json.loads(self.options) if isinstance(self.options, str) else dict(self.options or {})
        except (TypeError, ValueError):
            raise ChartImgError('invalid_request') from None
        # Only these provider presentation fields can be supplied. Authentication,
        # URLs, output storage and overriding identity fields never enter options.
        if not isinstance(options, dict) or set(options) - {'theme', 'studies', 'style', 'timezone', 'override', 'backgroundColor'}:
            raise ChartImgError('invalid_request')
        if self.layout_id is not None and options:
            raise ChartImgError('unsupported_layout_options')
        if 'theme' in options and options['theme'] not in {'light', 'dark'}:
            raise ChartImgError('invalid_request')
        if 'studies' in options and (not isinstance(options['studies'], list) or any(not isinstance(x, dict) for x in options['studies'])):
            raise ChartImgError('invalid_request')
        for name in ('style', 'timezone', 'backgroundColor'):
            if name in options and (not isinstance(options[name], str) or not options[name].strip()):
                raise ChartImgError('invalid_request')
        if 'override' in options and not isinstance(options['override'], dict):
            raise ChartImgError('invalid_request')
        serialized = canonical(options)
        if len(serialized.encode()) > 64_000:
            raise ChartImgError('invalid_request')
        object.__setattr__(self, 'options', serialized)

    @property
    def endpoint(self) -> str:
        if self.layout_id:
            return '/v2/tradingview/layout-chart/' + self.layout_id
        return '/v2/tradingview/advanced-chart'

    @property
    def payload(self) -> dict:
        payload = json.loads(self.options)
        payload.update(symbol=self.symbol, interval=self.interval, width=self.width, height=self.height, format='png')
        if self.layout_id is None:
            payload['range'] = self.time_range
        return payload

    @property
    def identity_json(self) -> str:
        return canonical(dict(profile_revision=self.profile_revision, layout_revision=self.layout_revision,
                              symbol=self.symbol, interval=self.interval, time_range=self.time_range,
                              cutoff=self.cutoff.isoformat(), endpoint=self.endpoint, payload=self.payload))

    @property
    def identity(self) -> str:
        return sha256(self.identity_json.encode()).hexdigest()


@dataclass(frozen=True)
class AsOfVerification:
    """Caller attestation from external evidence, never inferred from pixels here."""
    image_sha256: str
    request_identity: str
    last_bar_date: str
    verified_at: datetime
    method: str
    evidence_ref: str
    time_range: str

    def __post_init__(self):
        if any(not isinstance(x, str) or not re.fullmatch(r'[a-f0-9]{64}', x) for x in (self.image_sha256, self.request_identity)):
            raise ChartImgError('invalid_verification')
        try:
            date.fromisoformat(self.last_bar_date)
        except (TypeError, ValueError):
            raise ChartImgError('invalid_verification') from None
        object.__setattr__(self, 'verified_at', aware(self.verified_at))
        if any(not isinstance(x, str) or not x.strip() for x in (self.method, self.evidence_ref, self.time_range)):
            raise ChartImgError('invalid_verification')


@dataclass(frozen=True)
class ImageArtifact:
    request: RenderRequest
    data: bytes = field(repr=False)
    content_type: str
    format: str
    width: int
    height: int
    sha256: str
    retrieved_at: datetime
    verification: AsOfVerification | None = None

    def with_verification(self, proof: AsOfVerification) -> 'ImageArtifact':
        if (proof.image_sha256 != self.sha256 or proof.request_identity != self.request.identity or proof.time_range != self.request.time_range
                or date.fromisoformat(proof.last_bar_date) > self.request.cutoff.date()
                or proof.verified_at < self.retrieved_at):
            raise ChartImgError('verification_mismatch')
        return replace(self, verification=proof)


def validate_image(data: bytes, content_type: str, request: RenderRequest,
                   retrieved_at: datetime, *, max_bytes: int = 8_000_000) -> ImageArtifact:
    if not isinstance(data, bytes) or not 0 < len(data) <= max_bytes or not isinstance(content_type, str) or content_type.split(';')[0].strip().lower() != 'image/png':
        raise ChartImgError('invalid_image')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format != 'PNG' or image.size != (request.width, request.height) or getattr(image, 'n_frames', 1) != 1:
                    raise ChartImgError('invalid_image')
                image.verify()
            with Image.open(BytesIO(data)) as image:
                image.load()  # Header validation alone cannot establish byte validity.
    except Exception:
        raise ChartImgError('invalid_image') from None
    return ImageArtifact(request, data, 'image/png', 'PNG', request.width, request.height,
                         sha256(data).hexdigest(), aware(retrieved_at))
