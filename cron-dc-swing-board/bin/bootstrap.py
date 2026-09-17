"""Reviewed Phintraco Swing-board bootstrap and backfill preparation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, time
import importlib
import json
import re
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from calendar import sessions_ago
from models import SourceEvent


SOURCE_CHANNEL_ID = 1444713822
BOOTSTRAP_WATCHER_NAME = "bursawatch-dc-swing-board-bootstrap"
WIB = ZoneInfo("Asia/Jakarta")
MAX_HISTORY_MESSAGES = 20_000
MAX_BOOTSTRAP_MEDIA_BYTES = 8 * 1024 * 1024
_TARGET_NUMBER = re.compile(
    r"\b(?:(?P<word>first|second|third|fourth|fifth|sixth)|"
    r"(?P<number>\d+)(?:st|nd|rd|th)?)\s+target\b",
    re.IGNORECASE,
)
_TARGET_VALUE = re.compile(
    r"\b(?:target|tp)\s+(?P<value>[0-9][0-9.,]*)\s+"
    r"(?:achieved|hit|reached)\b",
    re.IGNORECASE,
)
_TARGET_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
}


class BootstrapError(RuntimeError):
    """A safe, operator-facing bootstrap failure."""


@dataclass(frozen=True)
class ParsedHistoryEvent:
    message_id: int
    published_at: datetime
    call: Any


@dataclass(frozen=True)
class BootstrapCandidate:
    ticker: str
    original_buy_message_id: int | None
    original_buy_published_at: str | None
    status_message_ids: tuple[int, ...]
    status_summaries: tuple[str, ...]
    chart_available: bool | None
    missing_setup_reason: str | None
    intended_forum_operation: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BootstrapManifestEvent:
    """One reviewed source event for a bounded historical backfill."""

    source_message_id: int
    source_event_kind: str
    board_kind: str
    target_all_message_id: str | None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def lookback_window(now: datetime, lookback_sessions: int) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if not 1 <= lookback_sessions <= 250:
        raise ValueError("lookback_sessions must be between 1 and 250")
    end = now.astimezone(WIB)
    start_day = sessions_ago(end.date(), lookback_sessions)
    start = datetime.combine(start_day, time.min, tzinfo=WIB)
    return start, end


def _message_time(message: object) -> datetime | None:
    value = getattr(message, "date", None)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(WIB)


async def fetch_history(
    client: object,
    entity: object,
    start: datetime,
    end: datetime,
) -> tuple[object, ...]:
    """Fetch newest-to-oldest messages until the reviewed window is covered."""
    messages: list[object] = []
    iterator = client.iter_messages(entity, reverse=False)
    async for message in iterator:
        published_at = _message_time(message)
        if published_at is None:
            continue
        if published_at < start:
            break
        if published_at <= end:
            messages.append(message)
        if len(messages) > MAX_HISTORY_MESSAGES:
            raise BootstrapError(
                f"history window exceeds the {MAX_HISTORY_MESSAGES} message safety limit"
            )
    messages.sort(key=lambda item: (_message_time(item) or start, int(getattr(item, "id", 0))))
    return tuple(messages)


def _status_summary(call: Any) -> str:
    if getattr(call, "event_kind", None) == "STATUS":
        return str(getattr(call, "status", None) or "Source status update")
    outcomes = tuple(str(item) for item in getattr(call, "outcomes", ()) if item)
    return "; ".join(outcomes) or "Source status update"


def _is_terminal_status(call: Any, buy_call: Any) -> bool:
    if getattr(call, "event_kind", None) != "REMINDER":
        return False
    outcomes = tuple(str(item) for item in getattr(call, "outcomes", ()))
    lowered = " ".join(outcomes).casefold()
    if "stop-loss hit" in lowered or "all targets achieved" in lowered:
        return True
    target_count = len(tuple(getattr(buy_call, "targets", ())))
    for outcome in outcomes:
        match = _TARGET_NUMBER.search(outcome)
        if match is None:
            continue
        number = (
            _TARGET_WORDS[match.group("word").casefold()]
            if match.group("word")
            else int(match.group("number"))
        )
        if number == target_count:
            return True
    for outcome in outcomes:
        match = _TARGET_VALUE.search(outcome)
        if match is None:
            continue
        token = re.sub(r"[.,]", "", match.group("value"))
        target_values = tuple(
            str(getattr(target, "value", target)) for target in getattr(buy_call, "targets", ())
        )
        for index, target in enumerate(target_values, start=1):
            target_token = re.sub(r"[.,]", "", target)
            if token == target_token and index == target_count:
                return True
        # The live parser treats a small unmatched numeric token as a target
        # index. Keep that compatibility without mistaking a price such as
        # 3270 for target number 3270.
        try:
            fallback_index = int(token)
        except ValueError:
            continue
        if 1 <= fallback_index <= 6 and fallback_index == target_count:
            return True
    return False


def _source_event_from_history(
    event: ParsedHistoryEvent,
    watcher_module: object,
    media_path: str | None = None,
) -> SourceEvent:
    """Convert one parsed Phintraco event into the live board contract."""
    call = event.call
    event_kind = str(getattr(call, "event_kind", "")).upper()
    ticker = str(getattr(call, "ticker", "")).upper()
    if event_kind == "BUY":
        kind = "buy"
        source_title = f"{ticker}: {getattr(call, 'call_subtype', '')}"
        source_status = "New setup"
        plan = {
            "entry": str(getattr(call, "entry", "")),
            "stop_loss": str(getattr(call, "stop_loss", "")),
            "targets": [str(target.value) for target in getattr(call, "targets", ())],
        }
    elif event_kind == "STATUS":
        kind = "status"
        source_title = f"{ticker}: Hold"
        source_status = str(getattr(call, "status", None) or "Source status update")
        plan = None
    elif event_kind == "REMINDER":
        kind = "reminder"
        source_title = f"{ticker}: Reminder"
        source_status = "; ".join(str(item) for item in getattr(call, "outcomes", ()))
        plan = None
    else:
        raise BootstrapError(f"unsupported parsed Phintraco event kind: {event_kind or 'unknown'}")

    signal_datetime = getattr(call, "signal_datetime", None)
    if not isinstance(signal_datetime, datetime) or signal_datetime.tzinfo is None:
        raise BootstrapError(f"source event {event.message_id} has no timezone-aware signal date")
    formatter = getattr(watcher_module, "format_swing_alert", None)
    source_url_factory = getattr(watcher_module, "source_message_url", None)
    if formatter is None or source_url_factory is None:
        raise BootstrapError("Phintraco watcher formatter is unavailable")
    source_url = str(source_url_factory(event.message_id))
    payload = {
        "event_key": f"phintraco:{SOURCE_CHANNEL_ID}:{event.message_id}",
        "source": "phintraco",
        "kind": kind,
        "ticker": ticker,
        "published_at": signal_datetime.isoformat(),
        "source_url": source_url,
        "all_content": str(formatter(call)),
        "source_title": source_title,
        "source_status": source_status,
        "plan": plan,
        "media_path": media_path,
        "media_urls": [],
    }
    return SourceEvent.from_json(payload)


def _primary_history_events(
    candidates: Iterable[BootstrapCandidate], events: Iterable[ParsedHistoryEvent]
) -> tuple[ParsedHistoryEvent, ...]:
    """Select only approved complete BUY plans and their later statuses."""
    approved = {
        candidate.ticker: candidate
        for candidate in candidates
        if candidate.intended_forum_operation == "create Primary plan"
        and candidate.original_buy_message_id is not None
    }
    selected: list[ParsedHistoryEvent] = []
    for event in events:
        ticker = str(getattr(event.call, "ticker", "")).upper()
        candidate = approved.get(ticker)
        if candidate is None:
            continue
        if event.message_id == candidate.original_buy_message_id:
            selected.append(event)
        elif event.message_id in candidate.status_message_ids:
            selected.append(event)
    return tuple(sorted(selected, key=lambda item: (item.published_at, item.message_id)))


def build_candidates(events: Iterable[ParsedHistoryEvent]) -> tuple[BootstrapCandidate, ...]:
    grouped: dict[str, list[ParsedHistoryEvent]] = {}
    for event in sorted(events, key=lambda item: (item.published_at, item.message_id)):
        ticker = str(getattr(event.call, "ticker", "")).upper()
        if ticker:
            grouped.setdefault(ticker, []).append(event)

    candidates: list[BootstrapCandidate] = []
    for ticker in sorted(grouped):
        ticker_events = grouped[ticker]
        buys = [event for event in ticker_events if getattr(event.call, "event_kind", None) == "BUY"]
        statuses = [event for event in ticker_events if getattr(event.call, "event_kind", None) in {"STATUS", "REMINDER"}]
        latest_buy = buys[-1] if buys else None
        later_statuses = [
            event for event in statuses
            if latest_buy is None
            or (event.published_at, event.message_id) > (latest_buy.published_at, latest_buy.message_id)
        ]

        if latest_buy is None:
            candidates.append(
                BootstrapCandidate(
                    ticker=ticker,
                    original_buy_message_id=None,
                    original_buy_published_at=None,
                    status_message_ids=tuple(event.message_id for event in later_statuses),
                    status_summaries=tuple(_status_summary(event.call) for event in later_statuses),
                    chart_available=None,
                    missing_setup_reason="original complete BUY setup not found in lookback",
                    intended_forum_operation="create historical source-only item",
                )
            )
            continue

        resolved = False
        for event in later_statuses:
            if _is_terminal_status(event.call, latest_buy.call):
                resolved = True
        candidates.append(
            BootstrapCandidate(
                ticker=ticker,
                original_buy_message_id=latest_buy.message_id,
                original_buy_published_at=latest_buy.published_at.isoformat(),
                status_message_ids=tuple(event.message_id for event in later_statuses),
                status_summaries=tuple(_status_summary(event.call) for event in later_statuses),
                chart_available=bool(getattr(latest_buy.call, "has_source_chart", False)),
                missing_setup_reason=None,
                intended_forum_operation=(
                    "skip source-resolved plan" if resolved else "create Primary plan"
                ),
            )
        )
    return tuple(candidates)


def load_manifest(path: Path) -> tuple[BootstrapManifestEvent, ...]:
    """Load an explicitly reviewed, source-message-level bootstrap manifest."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BootstrapError(f"bootstrap manifest cannot be read: {path}") from exc
    if not isinstance(raw, dict) or set(raw) != {"version", "source_channel_id", "events"}:
        raise BootstrapError("bootstrap manifest has an unsupported shape")
    if raw["version"] != 1 or raw["source_channel_id"] != SOURCE_CHANNEL_ID:
        raise BootstrapError("bootstrap manifest targets the wrong source")
    entries = raw["events"]
    if not isinstance(entries, list) or not entries:
        raise BootstrapError("bootstrap manifest must contain at least one event")

    selected: list[BootstrapManifestEvent] = []
    seen: set[int] = set()
    for raw_entry in entries:
        if not isinstance(raw_entry, dict) or set(raw_entry) != {
            "source_message_id",
            "source_event_kind",
            "board_kind",
            "target_all_message_id",
        }:
            raise BootstrapError("bootstrap manifest event has an unsupported shape")
        source_message_id = raw_entry["source_message_id"]
        source_event_kind = raw_entry["source_event_kind"]
        board_kind = raw_entry["board_kind"]
        target_all_message_id = raw_entry["target_all_message_id"]
        if (
            type(source_message_id) is not int
            or source_message_id < 1
            or source_message_id in seen
        ):
            raise BootstrapError("bootstrap manifest source message IDs must be unique positive integers")
        if source_event_kind not in {"BUY", "STATUS", "REMINDER"}:
            raise BootstrapError("bootstrap manifest source event kind is unsupported")
        if board_kind not in {"buy", "status", "reminder", "social"}:
            raise BootstrapError("bootstrap manifest Board event kind is unsupported")
        if board_kind != "social" and board_kind != source_event_kind.casefold():
            raise BootstrapError("bootstrap manifest Board kind must match its source event kind")
        if target_all_message_id is not None and (
            type(target_all_message_id) is not str or not target_all_message_id.isdigit()
        ):
            raise BootstrapError("bootstrap manifest target All message ID is invalid")
        seen.add(source_message_id)
        selected.append(
            BootstrapManifestEvent(
                source_message_id=source_message_id,
                source_event_kind=source_event_kind,
                board_kind=board_kind,
                target_all_message_id=target_all_message_id,
            )
        )
    return tuple(selected)


def _manifest_history_events(
    manifest: Iterable[BootstrapManifestEvent],
    events: Iterable[ParsedHistoryEvent],
) -> tuple[tuple[BootstrapManifestEvent, ParsedHistoryEvent], ...]:
    """Match every manifest item exactly once without ticker-level collapsing."""
    indexed = {event.message_id: event for event in events}
    selected: list[tuple[BootstrapManifestEvent, ParsedHistoryEvent]] = []
    for item in manifest:
        event = indexed.get(item.source_message_id)
        if event is None:
            raise BootstrapError(
                f"manifest source message {item.source_message_id} was not found in the history window"
            )
        actual_kind = str(getattr(event.call, "event_kind", "")).upper()
        if actual_kind != item.source_event_kind:
            raise BootstrapError(
                f"manifest source message {item.source_message_id} expected "
                f"{item.source_event_kind} but parser produced {actual_kind or 'unknown'}"
            )
        selected.append((item, event))
    return tuple(sorted(selected, key=lambda pair: (pair[1].published_at, pair[1].message_id)))


def _source_event_for_manifest(
    item: BootstrapManifestEvent,
    event: ParsedHistoryEvent,
    watcher_module: object,
    media_path: str | None = None,
) -> SourceEvent:
    """Preserve an orphan status as source-only context without inventing a plan."""
    source_event = _source_event_from_history(event, watcher_module, media_path)
    if item.board_kind == "social":
        return replace(source_event, kind="social", plan=None)
    if source_event.kind != item.board_kind:
        raise BootstrapError(
            f"manifest source message {item.source_message_id} cannot become {item.board_kind}"
        )
    return source_event


async def parse_history(
    client: object,
    entity: object,
    messages: Iterable[object],
    watcher_module: object,
) -> tuple[ParsedHistoryEvent, ...]:
    parsed: list[ParsedHistoryEvent] = []
    for message in messages:
        published_at = _message_time(message)
        if published_at is None:
            continue
        call = watcher_module.parse_source_event(message)
        if call is None:
            call = await watcher_module.parse_reply_status_event(client, entity, message)
        if call is not None:
            parsed.append(ParsedHistoryEvent(int(message.id), published_at, call))
    return tuple(parsed)


def _load_watcher_module() -> object:
    try:
        return importlib.import_module("scan")
    except ModuleNotFoundError as exc:
        raise BootstrapError(
            "Phintraco watcher parser is unavailable; check the watcher runtime path"
        ) from exc


async def _connect_telegram(now: datetime, watcher_module: object) -> tuple[object, object]:
    try:
        from telegram_resilience import (
            PolyCopResilience,
            acquire_probe_after_active_lease,
            is_transport_error,
        )
    except ModuleNotFoundError as exc:
        raise BootstrapError("Telegram resilience runtime is unavailable") from exc

    control = PolyCopResilience.from_defaults()
    decision = await acquire_probe_after_active_lease(control, BOOTSTRAP_WATCHER_NAME, now)
    if decision.kind != "probe":
        raise BootstrapError(f"Telegram resilience is not ready: {decision.kind}")

    client = watcher_module.make_client()
    try:
        await client.connect()
        checker = getattr(client, "is_user_authorized", None)
        if checker is not None and not await checker():
            control.record_auth_required(decision.lease_id, BOOTSTRAP_WATCHER_NAME, now)
            raise BootstrapError("Telegram session authorization is required")
        control.record_authenticated_success(decision.lease_id, BOOTSTRAP_WATCHER_NAME, now, None, None)
        return client, control
    except BootstrapError:
        await _disconnect_quietly(client)
        raise
    except Exception as exc:
        if is_transport_error(exc):
            control.record_transport_failure(decision.lease_id, BOOTSTRAP_WATCHER_NAME, exc, now)
        await _disconnect_quietly(client)
        raise BootstrapError(f"Telegram history read failed: {type(exc).__name__}") from exc


async def _disconnect_quietly(client: object) -> None:
    disconnect = getattr(client, "disconnect", None)
    if disconnect is None:
        return
    try:
        await disconnect()
    except Exception:
        pass


async def collect_report(
    *,
    now: datetime,
    lookback_sessions: int,
    client: object | None = None,
    watcher_module: object | None = None,
) -> dict[str, object]:
    start, end = lookback_window(now, lookback_sessions)
    watcher_module = watcher_module or _load_watcher_module()
    owned_client = client is None
    if owned_client:
        client, _control = await _connect_telegram(end, watcher_module)
    try:
        entity = await watcher_module.resolve_source(client)
        messages = await fetch_history(client, entity, start, end)
        events = await parse_history(client, entity, messages, watcher_module)
        candidates = build_candidates(events)
        return _report_payload(
            lookback_sessions=lookback_sessions,
            start=start,
            end=end,
            messages=messages,
            events=events,
            candidates=candidates,
        )
    finally:
        if owned_client:
            await _disconnect_quietly(client)


async def collect_manifest_report(
    *,
    now: datetime,
    lookback_sessions: int,
    manifest_path: Path,
    client: object | None = None,
    watcher_module: object | None = None,
) -> dict[str, object]:
    """Read and validate only an explicitly reviewed message-level manifest."""
    manifest = load_manifest(manifest_path)
    start, end = lookback_window(now, lookback_sessions)
    watcher_module = watcher_module or _load_watcher_module()
    owned_client = client is None
    if owned_client:
        client, _control = await _connect_telegram(end, watcher_module)
    try:
        entity = await watcher_module.resolve_source(client)
        messages = await fetch_history(client, entity, start, end)
        events = await parse_history(client, entity, messages, watcher_module)
        selected = _manifest_history_events(manifest, events)
        report = _report_payload(
            lookback_sessions=lookback_sessions,
            start=start,
            end=end,
            messages=messages,
            events=events,
            candidates=(),
        )
        report["manifest_events"] = [
            {
                **item.as_dict(),
                "ticker": str(getattr(event.call, "ticker", "")).upper(),
                "published_at": event.published_at.isoformat(),
            }
            for item, event in selected
        ]
        return report
    finally:
        if owned_client:
            await _disconnect_quietly(client)


def _report_payload(
    *,
    lookback_sessions: int,
    start: datetime,
    end: datetime,
    messages: Iterable[object],
    events: Iterable[ParsedHistoryEvent],
    candidates: Iterable[BootstrapCandidate],
) -> dict[str, object]:
    messages = tuple(messages)
    events = tuple(events)
    candidates = tuple(candidates)
    return {
            "source_channel_id": SOURCE_CHANNEL_ID,
            "lookback_sessions": lookback_sessions,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "messages_scanned": len(messages),
            "parsed_events": len(events),
            "candidate_count": len(candidates),
            "candidates": [candidate.as_dict() for candidate in candidates],
        }


async def apply_primary_candidates(
    *,
    now: datetime,
    lookback_sessions: int,
    engine: object,
    client: object | None = None,
    watcher_module: object | None = None,
) -> dict[str, object]:
    """Backfill only complete, source-unresolved Primary plans.

    Telegram history and all chart media are prepared before the first board
    transition. The board engine then receives the same immutable SourceEvent
    contract as the live watcher, so its normal idempotency and outbox rules
    govern the externally visible work.
    """
    start, end = lookback_window(now, lookback_sessions)
    watcher_module = watcher_module or _load_watcher_module()
    owned_client = client is None
    temporary_root = Path(tempfile.mkdtemp(prefix="bursawatch-swing-bootstrap-"))
    try:
        if owned_client:
            client, _control = await _connect_telegram(end, watcher_module)
        entity = await watcher_module.resolve_source(client)
        messages = await fetch_history(client, entity, start, end)
        events = await parse_history(client, entity, messages, watcher_module)
        candidates = build_candidates(events)
        selected = _primary_history_events(candidates, events)
        message_by_id = {int(getattr(message, "id", 0)): message for message in messages}

        prepared: list[SourceEvent] = []
        for event in selected:
            raw_message = message_by_id.get(event.message_id)
            if raw_message is None:
                raise BootstrapError(f"source message {event.message_id} disappeared from history")
            media_path = None
            if bool(getattr(event.call, "has_source_chart", False)):
                media_path = str(
                    await _download_history_media(
                        client, entity, raw_message, temporary_root
                    )
                )
            prepared.append(_source_event_from_history(event, watcher_module, media_path))

        from board import _own_media

        applied: list[dict[str, object]] = []
        for event in prepared:
            owned_event = _own_media(event)
            result = engine.submit(owned_event, now)
            applied.append(
                {
                    "ticker": owned_event.ticker,
                    "source_message_id": int(owned_event.event_key.rsplit(":", 1)[-1]),
                    "kind": owned_event.kind,
                    "result": result,
                }
            )
        drained = 0
        for _ in range(20):
            completed = int(engine.drain(now=now, limit=100))
            drained += completed
            if completed == 0:
                break
        report = _report_payload(
            lookback_sessions=lookback_sessions,
            start=start,
            end=end,
            messages=messages,
            events=events,
            candidates=candidates,
        )
        report["allowlist_count"] = sum(
            candidate.intended_forum_operation == "create Primary plan"
            for candidate in candidates
        )
        report["selected_event_count"] = len(selected)
        report["applied"] = applied
        report["drained"] = drained
        return report
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
        if owned_client:
            await _disconnect_quietly(client)


async def apply_manifest(
    *,
    now: datetime,
    lookback_sessions: int,
    manifest_path: Path,
    engine: object,
    client: object | None = None,
    watcher_module: object | None = None,
) -> dict[str, object]:
    """Backfill only reviewed source IDs, never a ticker-wide candidate set."""
    manifest = load_manifest(manifest_path)
    start, end = lookback_window(now, lookback_sessions)
    watcher_module = watcher_module or _load_watcher_module()
    owned_client = client is None
    temporary_root = Path(tempfile.mkdtemp(prefix="bursawatch-swing-manifest-"))
    try:
        if owned_client:
            client, _control = await _connect_telegram(end, watcher_module)
        entity = await watcher_module.resolve_source(client)
        messages = await fetch_history(client, entity, start, end)
        events = await parse_history(client, entity, messages, watcher_module)
        selected = _manifest_history_events(manifest, events)
        message_by_id = {int(getattr(message, "id", 0)): message for message in messages}

        prepared: list[tuple[BootstrapManifestEvent, SourceEvent]] = []
        for item, event in selected:
            raw_message = message_by_id.get(event.message_id)
            if raw_message is None:
                raise BootstrapError(f"source message {event.message_id} disappeared from history")
            media_path = None
            if bool(getattr(event.call, "has_source_chart", False)):
                media_path = str(
                    await _download_history_media(client, entity, raw_message, temporary_root)
                )
            prepared.append(
                (item, _source_event_for_manifest(item, event, watcher_module, media_path))
            )

        from board import _own_media

        applied: list[dict[str, object]] = []
        for item, event in prepared:
            owned_event = _own_media(event)
            result = engine.submit(owned_event, now)
            applied.append(
                {
                    "ticker": owned_event.ticker,
                    "source_message_id": item.source_message_id,
                    "target_all_message_id": item.target_all_message_id,
                    "kind": owned_event.kind,
                    "result": result,
                }
            )
        drained = 0
        for _ in range(20):
            completed = int(engine.drain(now=now, limit=100))
            drained += completed
            if completed == 0:
                break
        return {
            "source_channel_id": SOURCE_CHANNEL_ID,
            "lookback_sessions": lookback_sessions,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "manifest_count": len(manifest),
            "selected_event_count": len(prepared),
            "applied": applied,
            "drained": drained,
        }
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
        if owned_client:
            await _disconnect_quietly(client)


async def _download_history_media(
    client: object,
    entity: object,
    message: object,
    temporary_root: Path,
) -> Path:
    downloader = getattr(client, "download_media", None)
    if downloader is None:
        raise BootstrapError("Telegram client cannot download source charts")
    try:
        content = await downloader(message, bytes)
    except Exception as exc:
        raise BootstrapError(
            f"source chart download failed for message {getattr(message, 'id', '?')}"
        ) from exc
    if not isinstance(content, bytes) or not content:
        raise BootstrapError(
            f"source chart is unavailable for message {getattr(message, 'id', '?')}"
        )
    if len(content) > MAX_BOOTSTRAP_MEDIA_BYTES:
        raise BootstrapError(
            f"source chart exceeds {MAX_BOOTSTRAP_MEDIA_BYTES // (1024 * 1024)} MiB "
            f"for message {getattr(message, 'id', '?')}"
        )
    destination = temporary_root / f"phintraco-{int(getattr(message, 'id', 0))}.jpg"
    destination.write_bytes(content)
    return destination


def format_report(report: dict[str, object]) -> str:
    lines = [
        "IDX Swing board bootstrap dry-run",
        f"Source channel: {report['source_channel_id']}",
        f"Lookback sessions: {report['lookback_sessions']}",
        f"Window: {report['window_start']} to {report['window_end']}",
        f"Messages scanned: {report['messages_scanned']}",
        f"Parsed events: {report['parsed_events']}",
        f"Candidates: {report['candidate_count']}",
    ]
    for index, raw in enumerate(report["candidates"], start=1):
        candidate = raw
        assert isinstance(candidate, dict)
        lines.extend(
            [
                "",
                f"{index}. {candidate['ticker']}",
                f"   Original BUY source ID: {candidate['original_buy_message_id'] or 'none'}",
                f"   Later status source IDs: {', '.join(str(item) for item in candidate['status_message_ids']) or 'none'}",
                f"   Status summaries: {'; '.join(candidate['status_summaries']) or 'none'}",
                f"   Chart available: {candidate['chart_available'] if candidate['chart_available'] is not None else 'unknown'}",
                f"   Missing setup reason: {candidate['missing_setup_reason'] or 'none'}",
                f"   Intended forum operation: {candidate['intended_forum_operation']}",
            ]
        )
    return "\n".join(lines)


def format_apply_report(report: Mapping[str, object]) -> str:
    applied = tuple(report.get("applied", ()))
    by_result: dict[str, int] = {}
    for raw in applied:
        if isinstance(raw, Mapping):
            result = str(raw.get("result", "unknown"))
            by_result[result] = by_result.get(result, 0) + 1
    result_text = ", ".join(
        f"{name}={count}" for name, count in sorted(by_result.items())
    ) or "none"
    return "\n".join(
        [
            "IDX Swing board bootstrap apply",
            f"Source channel: {report['source_channel_id']}",
            f"Lookback sessions: {report['lookback_sessions']}",
            f"Window: {report['window_start']} to {report['window_end']}",
            f"Allowlisted Primary plans: {report.get('allowlist_count', 0)}",
            f"Selected source events: {report.get('selected_event_count', 0)}",
            f"Submitted events: {len(applied)} ({result_text})",
            f"Discord operations drained: {report.get('drained', 0)}",
        ]
    )
