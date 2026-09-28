"""Closed value objects shared by the IDX Swing plan board."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from media_store import validate_media_url


_EVENT_KEYS = frozenset(
    {
        "event_key",
        "source",
        "kind",
        "ticker",
        "published_at",
        "source_url",
        "all_content",
        "source_title",
        "source_status",
        "plan",
        "media_path",
        "media_urls",
        "matched_setup_event_key",
    }
)
_OPTIONAL_EVENT_KEYS = frozenset({"matched_setup_event_key"})
_PLAN_KEYS = frozenset({"entry", "stop_loss", "targets"})
_KINDS = frozenset({"buy", "status", "reminder", "social", "context"})
_PHINTRACO_SOURCE = "phintraco"
_TICKER = re.compile(r"[A-Z]{1,10}")
_WEEKLY_SETUP_KEY = re.compile(r"phintraco:\d+:weekly:\d+:(?P<ticker>[A-Z]{1,10})")


class MarketState(StrEnum):
    BELOW_ENTRY = "Below entry"
    ENTRY_ZONE = "Entry zone"
    ABOVE_ENTRY = "Above entry"
    TP1_REACHED = "TP1 reached"
    TP2_REACHED = "TP2 reached"
    TP3_REACHED = "TP3 reached"
    TP4_REACHED = "TP4 reached"
    TP5_REACHED = "TP5 reached"
    TP6_REACHED = "TP6 reached"
    STOP_LOSS_BREACHED = "Stop-loss breached"

    @classmethod
    def from_target_number(cls, number: int) -> MarketState:
        if not 1 <= number <= 6:
            raise ValueError("target number must be between 1 and 6")
        return getattr(cls, f"TP{number}_REACHED")


@dataclass(frozen=True)
class PlanLevels:
    entry: str
    stop_loss: str
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _non_empty_string(self.entry):
            raise ValueError("plan entry must be a non-empty string")
        if not _non_empty_string(self.stop_loss):
            raise ValueError("plan stop_loss must be a non-empty string")
        if not self.targets or any(not _non_empty_string(target) for target in self.targets):
            raise ValueError("plan targets must contain non-empty strings")


@dataclass(frozen=True)
class SourceOutcome:
    """A source-confirmed market-state outcome, never an inferred action."""

    state: MarketState
    source_status: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, MarketState):
            raise ValueError("source outcome state must be a MarketState")
        if not _non_empty_string(self.source_status):
            raise ValueError("source_status must be a non-empty string")


@dataclass(frozen=True)
class Checkpoint:
    session_date: str
    checked_at: str
    close_price: str | None
    state: MarketState | None
    unavailable: bool = False

    @classmethod
    def market(
        cls,
        *,
        session_date: str,
        checked_at: str,
        close_price: str,
        state: MarketState,
    ) -> Checkpoint:
        return cls(session_date, checked_at, close_price, state)

    @classmethod
    def unavailable_at(cls, *, session_date: str, checked_at: str) -> Checkpoint:
        return cls(session_date, checked_at, None, None, unavailable=True)

    def __post_init__(self) -> None:
        if not _non_empty_string(self.session_date):
            raise ValueError("session_date must be a non-empty string")
        _parse_aware_timestamp(self.checked_at)
        if self.state is not None and not isinstance(self.state, MarketState):
            raise ValueError("checkpoint state must be a MarketState")
        if self.unavailable:
            if self.close_price is not None or self.state is not None:
                raise ValueError("unavailable checkpoint cannot contain market facts")
        elif not _non_empty_string(self.close_price) or self.state is None:
            raise ValueError("market checkpoint requires close_price and state")


@dataclass(frozen=True)
class SourceEvent:
    event_key: str
    source: str
    kind: str
    ticker: str
    published_at: datetime
    source_url: str
    all_content: str
    source_title: str
    source_status: str | None
    plan: PlanLevels | None
    media_path: str | None
    media_urls: tuple[str, ...]
    media_paths: tuple[str, ...] = ()
    matched_setup_event_key: str | None = None

    def __post_init__(self) -> None:
        if not self.media_paths and self.media_path is not None:
            object.__setattr__(self, "media_paths", (self.media_path,))

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> SourceEvent:
        if not isinstance(payload, Mapping):
            raise ValueError("source event must be an object")
        unknown = set(payload) - _EVENT_KEYS - {"media_paths"}
        missing = (_EVENT_KEYS - _OPTIONAL_EVENT_KEYS) - set(payload)
        if unknown:
            raise ValueError(f"source event contains unknown keys: {sorted(unknown)}")
        if missing:
            raise ValueError(f"source event is missing keys: {sorted(missing)}")

        event_key = _required_string(payload["event_key"], "event_key")
        source = _required_string(payload["source"], "source")
        kind = _required_string(payload["kind"], "kind").lower()
        if kind not in _KINDS:
            raise ValueError(f"unsupported source event kind: {kind}")
        ticker = _required_string(payload["ticker"], "ticker").upper()
        if not _TICKER.fullmatch(ticker):
            raise ValueError("ticker must be 1 to 10 letters")
        published_at = _parse_aware_timestamp(payload["published_at"])
        source_url = _validate_url(payload["source_url"], "source_url")
        all_content = _required_string(payload["all_content"], "all_content")
        source_title = _required_string(payload["source_title"], "source_title")
        source_status = payload["source_status"]
        if source_status is not None:
            source_status = _required_string(source_status, "source_status")
        plan = _parse_plan(payload["plan"])
        media_path = _parse_media_path(payload["media_path"])
        media_paths = _parse_media_paths(payload.get("media_paths"), media_path, "media_paths" in payload)
        media_urls = _parse_media_urls(payload["media_urls"])
        matched_setup_event_key = payload.get("matched_setup_event_key")
        if matched_setup_event_key is not None:
            matched_setup_event_key = _required_string(
                matched_setup_event_key, "matched_setup_event_key"
            )
            match = _WEEKLY_SETUP_KEY.fullmatch(matched_setup_event_key)
            if match is None:
                raise ValueError("matched_setup_event_key must identify a weekly Phintraco setup")
            if source != _PHINTRACO_SOURCE or kind not in {"status", "reminder"}:
                raise ValueError("matched_setup_event_key is valid only for Phintraco updates")
            if match.group("ticker") != ticker:
                raise ValueError("matched_setup_event_key ticker must match the source event")

        if kind == "buy":
            if source != _PHINTRACO_SOURCE:
                raise ValueError("buy source event must originate from phintraco")
            if plan is None:
                raise ValueError("buy source event requires complete plan levels")
        if kind != "buy" and plan is not None:
            raise ValueError(f"{kind} source event cannot contain plan levels")
        return cls(
            event_key=event_key,
            source=source,
            kind=kind,
            ticker=ticker,
            published_at=published_at,
            source_url=source_url,
            all_content=all_content,
            source_title=source_title,
            source_status=source_status,
            plan=plan,
            media_path=media_path,
            media_urls=media_urls,
            media_paths=media_paths,
            matched_setup_event_key=matched_setup_event_key,
        )


@dataclass(frozen=True)
class SubmittedEvent:
    """Result of durable source-event intake."""

    id: int
    inserted: bool


@dataclass(frozen=True)
class Episode:
    """A single board-owned ticker lifecycle."""

    id: int
    ticker: str
    lifecycle: str
    title: str
    opened_at: datetime
    latest_material_at: datetime
    closed_at: datetime | None = None
    thread_id: str | None = None
    starter_message_id: str | None = None
    starter_source_event_id: int | None = None
    lifecycle_tag: str | None = None
    market_tag: str | None = None
    resolution_reason: str | None = None
    quiet_started_at: datetime | None = None
    archived_at: datetime | None = None


@dataclass(frozen=True)
class OutboxOperation:
    """A persisted Discord intent. It contains no HTTP client or side effect."""

    id: int
    operation: str
    episode_id: int
    payload: Mapping[str, Any]
    dedupe_key: str
    attempts: int
    next_attempt_at: datetime
    status: str
    last_error: str | None = None
    claim_token: str | None = None

    @property
    def kind(self) -> str:
        """Compatibility spelling for callers that describe an operation as a kind."""
        return self.operation


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _required_string(value: object, name: str) -> str:
    if not _non_empty_string(value):
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _parse_aware_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("published_at must be an ISO timestamp string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("published_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("published_at must include a timezone")
    return parsed


def _validate_url(value: object, name: str) -> str:
    url = _required_string(value, name)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must use http or https")
    return url


def _parse_plan(value: object) -> PlanLevels | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("plan must be an object or null")
    if set(value) != _PLAN_KEYS:
        raise ValueError("plan must contain only entry, stop_loss, and targets")
    targets = value["targets"]
    if not isinstance(targets, list):
        raise ValueError("plan targets must be a list")
    return PlanLevels(
        _required_string(value["entry"], "plan entry"),
        _required_string(value["stop_loss"], "plan stop_loss"),
        tuple(_required_string(target, "plan target") for target in targets),
    )


def _parse_media_path(value: object) -> str | None:
    if value is None:
        return None
    path = _required_string(value, "media_path")
    if not Path(path).is_absolute():
        raise ValueError("media_path must be an absolute path")
    return path


def _parse_media_paths(value: object, media_path: str | None, present: bool) -> tuple[str, ...]:
    if not present:
        return (media_path,) if media_path else ()
    if type(value) is not list or len(value) > 16:
        raise ValueError("media_paths must be a list of at most 16 paths")
    paths = tuple(_parse_media_path(item) for item in value)
    if any(path is None for path in paths) or len(set(paths)) != len(paths):
        raise ValueError("media_paths must be unique absolute paths")
    if (paths[0] if paths else None) != media_path:
        raise ValueError("media_path must match the first media_paths entry")
    return paths


def _parse_media_urls(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("media_urls must be a list")
    return tuple(validate_media_url(_validate_url(url, "media_url")) for url in value)
