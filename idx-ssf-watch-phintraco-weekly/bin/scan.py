from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from telegram_resilience import (
    PolyCopResilience,
    StateBlockedError as ResilienceStateBlockedError,
    acquire_probe_after_active_lease,
    is_transport_error,
)


WIB = ZoneInfo("Asia/Jakarta")
SOURCE_CHANNEL_ID = 1444713822
ALERT_CHANNEL_ID = "1525102458253217803"
HEARTBEAT_CHANNEL_ID = "1505162000420835388"
WATCHER_HEARTBEAT_NAME = "idx-ssf"
WATCHER_NAME = "idx-ssf-watch-phintraco-weekly"
MAX_FATAL_FINGERPRINTS_PER_HOUR = 64
CAPTURE_RETRY_MAX_ATTEMPTS = 5
CAPTURE_RETRY_BASE_DELAY = timedelta(minutes=1)
CAPTURE_RETRY_MAX_DELAY = timedelta(hours=1)
DELIVERY_RETRY_BASE_DELAY = timedelta(minutes=1)
DELIVERY_RETRY_MAX_DELAY = timedelta(hours=1)
TELEGRAM_MESSAGE_BASE_URL = "https://t.me/phintraprofits"
PHINTRACO_EMOJI = "<:phintraco:1531272488645038091>"
UP_EMOJI = "<:up:1531285100346740766>"
DOWN_EMOJI = "<:down:1531285063986053200>"
PDF_FILENAME_RE = re.compile(r"^weekly ssf review.*\.pdf$", re.IGNORECASE)


@dataclass(frozen=True)
class SsfCandidate:
    source_message_id: int
    filename: str
    message: Any


@dataclass(frozen=True)
class RunStats:
    source_status: str
    reports: int
    alerts: int
    degraded: bool


UNDERLYING_HEADER_RE = re.compile(
    r"(?m)^\s*([A-Z]{4})\s+(.+?)\s+Shares Statistics as of\s+(.+?)\s*$"
)


class InvalidSsfReport(ValueError):
    """The supplied PDF cannot safely be treated as a Weekly SSF Review."""


@dataclass(frozen=True)
class ContractRecommendation:
    horizon_months: int
    strategy: str
    purchase_price: str
    target_price: str
    support_resistance: str


@dataclass(frozen=True)
class UnderlyingSsfReview:
    ticker: str
    issuer_name: str
    share_price: str
    contracts: tuple[
        ContractRecommendation,
        ContractRecommendation,
        ContractRecommendation,
    ]
    chart_path: str | None


@dataclass(frozen=True)
class WeeklySsfReview:
    source_message_id: int
    report_date: date
    provider: str
    underlyings: tuple[
        UnderlyingSsfReview,
        UnderlyingSsfReview,
        UnderlyingSsfReview,
        UnderlyingSsfReview,
        UnderlyingSsfReview,
    ]


@dataclass(frozen=True)
class PdfImage:
    page: int
    width: int
    height: int
    ordinal: int


def run_poppler(*args: str) -> str:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return completed.stdout


def _normalise_whitespace(value: str) -> str:
    return " ".join(value.split())


def _run_pdf_inspection(*args: str) -> str:
    try:
        return run_poppler(*args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise InvalidSsfReport("unable to inspect source PDF") from error


def _validate_page_count(pdf_path: Path) -> None:
    info = _run_pdf_inspection("pdfinfo", str(pdf_path))
    page_matches = re.findall(r"(?m)^Pages:\s*(\d+)\s*$", info)
    if len(page_matches) != 1 or int(page_matches[0]) != 4:
        raise InvalidSsfReport("expected exactly four pages")


def _parse_pdfimages(inventory: str) -> tuple[PdfImage, ...]:
    images: list[PdfImage] = []
    row_pattern = re.compile(r"^\s*(\d+)\s+(\d+)\s+\S+\s+(\d+)\s+(\d+)\b")
    for line in inventory.splitlines():
        match = row_pattern.match(line)
        if match is None:
            continue
        page, ordinal, width, height = (int(value) for value in match.groups())
        images.append(
            PdfImage(page=page, width=width, height=height, ordinal=ordinal)
        )
    return tuple(images)


def _validate_technical_chart_inventory(pdf_path: Path) -> None:
    _validated_technical_charts(pdf_path)


def _require_contract_headers(layout_text: str) -> None:
    headers = ("1 Month Contract", "2 Month Contract", "3 Month Contract")
    positions = [layout_text.find(header) for header in headers]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise InvalidSsfReport("missing ordered contract headers")


def _extract_three_field_values(block: str, label: str) -> tuple[str, str, str]:
    label_lines = [line for line in block.splitlines() if label in line]
    if len(label_lines) != 1:
        raise InvalidSsfReport(f"expected one {label!r} field row")

    line = label_lines[0]
    positions = [match.start() for match in re.finditer(re.escape(label), line)]
    if len(positions) != 3:
        raise InvalidSsfReport(f"expected three {label!r} field values")

    values = tuple(
        _normalise_whitespace(
            line[position + len(label) : next_position]
        )
        for position, next_position in zip(positions, (*positions[1:], len(line)))
    )
    if any(not value for value in values):
        raise InvalidSsfReport(f"empty {label!r} field value")
    return values  # type: ignore[return-value]


def _extract_share_price(block: str) -> str:
    matches = re.findall(r"(?m)^\s*([0-9][0-9.,]*)\s+Value\s*$", block)
    if len(matches) != 1:
        raise InvalidSsfReport("expected one underlying price")
    return _normalise_whitespace(matches[0])


def _parse_underlying(header: re.Match[str], block: str) -> UnderlyingSsfReview:
    strategies = _extract_three_field_values(block, "Strategy")
    if any(strategy not in {"Long", "Short"} for strategy in strategies):
        raise InvalidSsfReport("unsupported contract strategy")

    purchase_prices = _extract_three_field_values(block, "Contract Purchase Price (IDR)")
    target_prices = _extract_three_field_values(block, "Potential Target Price (IDR)")
    support_resistance = _extract_three_field_values(block, "Support / Resistance")
    contracts = tuple(
        ContractRecommendation(
            horizon_months=horizon_months,
            strategy=strategy,
            purchase_price=purchase_price,
            target_price=target_price,
            support_resistance=support,
        )
        for horizon_months, strategy, purchase_price, target_price, support in zip(
            (1, 2, 3),
            strategies,
            purchase_prices,
            target_prices,
            support_resistance,
            strict=True,
        )
    )
    return UnderlyingSsfReview(
        ticker=header.group(1),
        issuer_name=_normalise_whitespace(header.group(2)),
        share_price=_extract_share_price(block),
        contracts=contracts,  # type: ignore[arg-type]
        chart_path=None,
    )


def _parse_report_date(layout_text: str) -> date:
    match = re.search(
        r"(?m)^\s*(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*$", layout_text
    )
    if match is None:
        raise InvalidSsfReport("missing report date")
    month_names = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "juli": 7,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
        "januari": 1,
        "februari": 2,
        "maret": 3,
        "mei": 5,
        "juni": 6,
        "agustus": 8,
        "oktober": 10,
        "november": 11,
        "desember": 12,
    }
    try:
        return date(
            int(match.group(3)), month_names[match.group(2).lower()], int(match.group(1))
        )
    except (KeyError, ValueError) as error:
        raise InvalidSsfReport("invalid report date") from error


def parse_weekly_ssf_pdf(source_message_id: int, pdf_path: Path) -> WeeklySsfReview:
    """Strictly parse a four-page Phintraco Weekly SSF Review source PDF."""
    _validate_page_count(pdf_path)
    layout_text = _run_pdf_inspection("pdftotext", "-layout", str(pdf_path), "-")
    if not layout_text.strip():
        raise InvalidSsfReport("empty PDF layout text")
    _require_contract_headers(layout_text)
    _validate_technical_chart_inventory(pdf_path)

    headers = tuple(UNDERLYING_HEADER_RE.finditer(layout_text))
    if len(headers) != 5:
        raise InvalidSsfReport("expected exactly five underlyings")
    underlyings = tuple(
        _parse_underlying(
            header,
            layout_text[
                header.start() : headers[index + 1].start()
                if index + 1 < len(headers)
                else len(layout_text)
            ],
        )
        for index, header in enumerate(headers)
    )
    return WeeklySsfReview(
        source_message_id=source_message_id,
        report_date=_parse_report_date(layout_text),
        provider="Phintraco",
        underlyings=underlyings,  # type: ignore[arg-type]
    )


def ssf_alert_direction(
    contracts: tuple[
        ContractRecommendation,
        ContractRecommendation,
        ContractRecommendation,
    ],
) -> str:
    strategies = {contract.strategy for contract in contracts}
    if strategies == {"Long"}:
        return "LONG"
    if strategies == {"Short"}:
        return "SHORT"
    return "MIXED"


def _escape_discord_markdown(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]<>])", r"\\\1", value)


def _format_report_date(report_date: date) -> str:
    return f"{report_date.strftime('%a, %b')} {report_date.day} {report_date.year}"


def _format_contract_strategy(strategy: str) -> str:
    marker = UP_EMOJI if strategy == "Long" else DOWN_EMOJI
    return f"{_escape_discord_markdown(strategy)}{marker}"


def format_ssf_alert(
    underlying: UnderlyingSsfReview, report_date: date, source_message_id: int
) -> str:
    sections = []
    for contract in underlying.contracts:
        sections.append(
            "\n".join(
                (
                    f"**{contract.horizon_months}-month contract**",
                    f"Strategy: {_format_contract_strategy(contract.strategy)}",
                    f"Purchase price: {_escape_discord_markdown(contract.purchase_price)}",
                    f"Target price: {_escape_discord_markdown(contract.target_price)}",
                    "Support / resistance: "
                    f"{_escape_discord_markdown(contract.support_resistance)}",
                )
            )
        )
    alert = (
        f"### {PHINTRACO_EMOJI} [SSF] "
        f"{ssf_alert_direction(underlying.contracts)}: {underlying.ticker}\n\n"
        f"Report date: {_format_report_date(report_date)}\n"
        f"Underlying price: {_escape_discord_markdown(underlying.share_price)}\n\n"
        + "\n\n".join(sections)
        + "\n\nSource: "
        f"[Phintraco Sekuritas](<{TELEGRAM_MESSAGE_BASE_URL}/{source_message_id}>) | Weekly SSF Review"
    )
    if len(alert) >= 2000:
        raise InvalidSsfReport("formatted alert exceeds Discord character limit")
    return alert


class StateBlockedError(RuntimeError):
    """Existing delivery state is corrupt or cannot be safely interpreted."""


class ReportCaptureError(RuntimeError):
    """A source PDF or its chart extraction can be retried safely."""


STATE_VERSION = 1
STATE_ENV = "IDX_SSF_WATCH_PHINTRACO_WEEKLY_STATE_PATH"
DEFAULT_STATE_PATH = Path.home() / ".hermes" / "state" / "idx-ssf-watch-phintraco-weekly.json"


def empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "bootstrap_complete": False,
        "observed_message_id": 0,
        "report_jobs": {},
        "invalid_reports": {},
        "outbox": {},
        "last_poll_success": None,
        "last_delivery_success": None,
        "last_heartbeat_run": None,
        "last_error_notice": None,
        "stats": {"runs": 0, "reports": 0, "alerts": 0, "delivered": 0},
    }


def _state_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    configured_path = os.environ.get(STATE_ENV)
    if configured_path:
        return Path(configured_path)
    return DEFAULT_STATE_PATH


def _validate_state(state: object) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise StateBlockedError("state root must be an object")
    required_keys = set(empty_state())
    if set(state) != required_keys:
        raise StateBlockedError("state shape is unsupported")
    if state["version"] != STATE_VERSION:
        raise StateBlockedError("state version is unsupported")
    if not isinstance(state["bootstrap_complete"], bool):
        raise StateBlockedError("state bootstrap flag is invalid")
    if not isinstance(state["observed_message_id"], int):
        raise StateBlockedError("state observed message ID is invalid")
    for key in ("report_jobs", "invalid_reports", "outbox"):
        if not isinstance(state[key], dict):
            raise StateBlockedError(f"state {key} is invalid")
    for source_key, job in state["report_jobs"].items():
        if not isinstance(source_key, str) or not isinstance(job, dict):
            raise StateBlockedError("state report job is invalid")
        if not isinstance(job.get("source_message_id"), int) or not isinstance(
            job.get("phase"), str
        ):
            raise StateBlockedError("state report job metadata is invalid")
        if job.get("pdf_path") is not None and not isinstance(job.get("pdf_path"), str):
            raise StateBlockedError("state report job PDF path is invalid")
        retry = job.get("retry")
        if not isinstance(retry, dict) or not isinstance(retry.get("attempts"), int):
            raise StateBlockedError("state report job retry metadata is invalid")
        next_attempt_at = retry.get("next_attempt_at")
        if next_attempt_at is not None:
            if not isinstance(next_attempt_at, str):
                raise StateBlockedError("state report job retry schedule is invalid")
            try:
                if datetime.fromisoformat(next_attempt_at).utcoffset() is None:
                    raise ValueError
            except ValueError as error:
                raise StateBlockedError(
                    "state report job retry schedule is invalid"
                ) from error
        if not isinstance(job.get("event_keys"), list) or not all(
            isinstance(event_key, str) for event_key in job["event_keys"]
        ):
            raise StateBlockedError("state report job event keys are invalid")
    for source_key, invalid_report in state["invalid_reports"].items():
        if not isinstance(source_key, str) or not isinstance(invalid_report, dict):
            raise StateBlockedError("state invalid report is invalid")
        if not isinstance(invalid_report.get("reason"), str):
            raise StateBlockedError("state invalid report reason is invalid")
    for event_key, event in state["outbox"].items():
        if not isinstance(event_key, str) or not isinstance(event, dict):
            raise StateBlockedError("state outbox event is invalid")
        if event.get("phase") not in {
            "pending_text",
            "pending_chart",
            "pending_chart_cleanup",
            "delivered",
        }:
            raise StateBlockedError("state outbox event phase is invalid")
        if not isinstance(event.get("source_message_id"), int) or not isinstance(
            event.get("ticker"), str
        ) or not isinstance(event.get("text"), str):
            raise StateBlockedError("state outbox event payload is invalid")
        for nullable_key in (
            "chart_path",
            "text_discord_id",
            "chart_discord_id",
            "last_error",
        ):
            if event.get(nullable_key) is not None and not isinstance(
                event.get(nullable_key), str
            ):
                raise StateBlockedError("state outbox event metadata is invalid")
        if not isinstance(event.get("delivery_attempts"), int):
            raise StateBlockedError("state outbox retry metadata is invalid")
        event.setdefault("next_attempt_at", None)
        next_attempt_at = event["next_attempt_at"]
        if next_attempt_at is not None:
            if not isinstance(next_attempt_at, str):
                raise StateBlockedError("state outbox retry schedule is invalid")
            try:
                if datetime.fromisoformat(next_attempt_at).utcoffset() is None:
                    raise ValueError
            except ValueError as error:
                raise StateBlockedError(
                    "state outbox retry schedule is invalid"
                ) from error
    stats = state["stats"]
    if not isinstance(stats, dict) or set(stats) != {
        "runs",
        "reports",
        "alerts",
        "delivered",
    }:
        raise StateBlockedError("state statistics are invalid")
    if any(not isinstance(value, int) for value in stats.values()):
        raise StateBlockedError("state statistics contain non-integers")
    return state


def load_state(path: Path | None = None) -> dict[str, Any]:
    resolved_path = _state_path(path)
    try:
        with resolved_path.open(encoding="utf-8") as state_file:
            state = json.load(state_file)
    except FileNotFoundError:
        return empty_state()
    except (OSError, json.JSONDecodeError) as error:
        raise StateBlockedError("unable to read state") from error
    return _validate_state(state)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as file_handle:
        os.fsync(file_handle.fileno())


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    _validate_state(state)
    resolved_path = _state_path(path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = resolved_path.with_name(f".{resolved_path.name}.{os.getpid()}.tmp")
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        file_descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            os.fchmod(temporary_file.fileno(), 0o600)
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, resolved_path)
        _fsync_directory(resolved_path.parent)
    except BaseException:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def discord_nonce(event_key: str, leg: str) -> str:
    identity = f"idx-ssf-watch-phintraco-weekly:{event_key}:{leg}"
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def _serialise_review(review: WeeklySsfReview) -> dict[str, Any]:
    return {
        "source_message_id": review.source_message_id,
        "report_date": review.report_date.isoformat(),
        "provider": review.provider,
        "underlyings": [
            {
                "ticker": underlying.ticker,
                "issuer_name": underlying.issuer_name,
                "share_price": underlying.share_price,
                "contracts": [
                    {
                        "horizon_months": contract.horizon_months,
                        "strategy": contract.strategy,
                        "purchase_price": contract.purchase_price,
                        "target_price": contract.target_price,
                        "support_resistance": contract.support_resistance,
                    }
                    for contract in underlying.contracts
                ],
            }
            for underlying in review.underlyings
        ],
    }


def _retry_metadata(job: dict[str, Any]) -> dict[str, Any]:
    retry = job.setdefault("retry", {"attempts": 0, "last_error": None})
    retry.setdefault("attempts", 0)
    retry.setdefault("last_error", None)
    retry.setdefault("next_attempt_at", None)
    return retry


def _record_retry(job: dict[str, Any], error: Exception, now: datetime) -> None:
    retry = _retry_metadata(job)
    retry["attempts"] += 1
    retry["last_error"] = str(error)
    if retry["attempts"] >= CAPTURE_RETRY_MAX_ATTEMPTS:
        retry["next_attempt_at"] = None
        return
    delay = min(
        CAPTURE_RETRY_BASE_DELAY * (2 ** (retry["attempts"] - 1)),
        CAPTURE_RETRY_MAX_DELAY,
    )
    retry["next_attempt_at"] = (now.astimezone(WIB) + delay).isoformat()


def _retry_is_due(job: dict[str, Any], now: datetime) -> bool:
    retry = _retry_metadata(job)
    if retry["attempts"] >= CAPTURE_RETRY_MAX_ATTEMPTS:
        return False
    next_attempt_at = retry["next_attempt_at"]
    if next_attempt_at is None:
        return True
    return datetime.fromisoformat(next_attempt_at) <= now.astimezone(WIB)



def _delivery_retry_is_due(event: dict[str, Any], now: datetime) -> bool:
    next_attempt_at = event.setdefault("next_attempt_at", None)
    if next_attempt_at is None:
        return True
    return datetime.fromisoformat(next_attempt_at) <= now.astimezone(WIB)


def _record_delivery_retry(
    event: dict[str, Any], error: Exception, now: datetime
) -> None:
    event["delivery_attempts"] += 1
    event["last_error"] = str(error)
    delay = DELIVERY_RETRY_BASE_DELAY
    for _ in range(event["delivery_attempts"] - 1):
        delay = min(delay * 2, DELIVERY_RETRY_MAX_DELAY)
        if delay == DELIVERY_RETRY_MAX_DELAY:
            break
    event["next_attempt_at"] = (now.astimezone(WIB) + delay).isoformat()

def enqueue_review(
    state: dict[str, Any],
    review: WeeklySsfReview,
    chart_paths: list[Path] | tuple[Path, ...],
) -> None:
    """Atomically stage exactly one text-plus-chart event per source underlying."""
    if len(chart_paths) != len(review.underlyings) or len(chart_paths) != 5:
        raise ValueError("expected exactly five cached technical charts")
    if any(not chart_path.is_file() for chart_path in chart_paths):
        raise ValueError("all charts must be durable files before enqueueing")

    source_key = str(review.source_message_id)
    if source_key in state["invalid_reports"]:
        raise StateBlockedError("cannot enqueue a terminally invalid report")
    report_job = state["report_jobs"].setdefault(
        source_key,
        {
            "source_message_id": review.source_message_id,
            "phase": "captured",
            "pdf_path": None,
            "retry": {"attempts": 0, "last_error": None, "next_attempt_at": None},
            "event_keys": [],
            "review": _serialise_review(review),
        },
    )
    event_keys = []
    for underlying, chart_path in zip(review.underlyings, chart_paths, strict=True):
        event_key = f"{review.source_message_id}:{underlying.ticker}"
        if event_key in state["outbox"]:
            raise StateBlockedError(f"duplicate outbox event {event_key}")
        state["outbox"][event_key] = {
            "source_message_id": review.source_message_id,
            "ticker": underlying.ticker,
            "phase": "pending_text",
            "text": format_ssf_alert(underlying, review.report_date, review.source_message_id),
            "chart_path": os.fspath(chart_path),
            "text_discord_id": None,
            "chart_discord_id": None,
            "delivery_attempts": 0,
            "next_attempt_at": None,
            "last_error": None,
        }
        event_keys.append(event_key)
    report_job["event_keys"] = event_keys
    report_job["phase"] = "queued"
    report_job["review"] = _serialise_review(review)


def _validated_technical_charts(pdf_path: Path) -> tuple[PdfImage, ...]:
    inventory = _run_pdf_inspection("pdfimages", "-list", str(pdf_path))
    try:
        images = _parse_pdfimages(inventory)
        technical_charts = tuple(
            image for image in images if image.width >= 1000 and image.height >= 500
        )
        if len(technical_charts) != 5:
            raise AssertionError
        if [image.page for image in technical_charts] != [1, 1, 2, 2, 3]:
            raise AssertionError
        return technical_charts
    except (AssertionError, ValueError) as error:
        raise InvalidSsfReport("unexpected technical-chart distribution") from error


def extract_charts(
    state: dict[str, Any],
    review: WeeklySsfReview,
    pdf_path: Path,
    state_path: Path | None = None,
) -> tuple[Path, Path, Path, Path, Path]:
    """Extract validated source-image ordinals into durable per-underlying cache files."""
    if not pdf_path.is_file():
        raise ReportCaptureError("cached source PDF is missing")
    technical_charts = _validated_technical_charts(pdf_path)
    media_dir = _state_path(state_path).parent / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    source_key = str(review.source_message_id)
    targets = tuple(
        media_dir / f"{source_key}-{image.ordinal}-{underlying.ticker}.png"
        for image, underlying in zip(technical_charts, review.underlyings, strict=True)
    )
    if all(target.is_file() for target in targets):
        return targets  # type: ignore[return-value]

    extraction_prefix = media_dir / f".{source_key}.extracting"
    for stale_path in media_dir.glob(f"{extraction_prefix.name}-*.png"):
        stale_path.unlink()
    try:
        subprocess.run(
            ("pdfimages", "-png", str(pdf_path), str(extraction_prefix)),
            check=True,
            capture_output=True,
            timeout=30,
        )
        for image, target in zip(technical_charts, targets, strict=True):
            extracted_path = extraction_prefix.with_name(
                f"{extraction_prefix.name}-{image.ordinal:03d}.png"
            )
            if not extracted_path.is_file():
                raise ReportCaptureError(
                    f"pdfimages did not produce validated ordinal {image.ordinal}"
                )
            _fsync_file(extracted_path)
            os.replace(extracted_path, target)
        _fsync_directory(media_dir)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ReportCaptureError("unable to extract technical charts") from error
    finally:
        for stale_path in media_dir.glob(f"{extraction_prefix.name}-*.png"):
            stale_path.unlink()
    return targets  # type: ignore[return-value]


def record_invalid_report(
    state: dict[str, Any], source_message_id: int, reason: str
) -> None:
    """Record a terminal validation failure without creating an outbox event."""
    source_key = str(source_message_id)
    state["report_jobs"].pop(source_key, None)
    for event_key, event in tuple(state["outbox"].items()):
        if event.get("source_message_id") == source_message_id:
            del state["outbox"][event_key]
    state["invalid_reports"][source_key] = {"reason": _bounded_reason(reason)}


def capture_report(
    state: dict[str, Any],
    source_message_id: int,
    download_pdf: Callable[[Path], None],
    state_path: Path | None = None,
    now: datetime | None = None,
) -> WeeklySsfReview | None:
    """Download, validate, cache, and queue one source report without losing retry state."""
    source_key = str(source_message_id)
    if source_key in state["invalid_reports"]:
        return None
    resolved_state_path = _state_path(state_path)
    reports_dir = resolved_state_path.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = reports_dir / f"{source_message_id}.pdf"
    temporary_pdf_path = reports_dir / f"{source_message_id}.pdf.tmp"
    job = state["report_jobs"].setdefault(
        source_key,
        {
            "source_message_id": source_message_id,
            "phase": "pending_download",
            "pdf_path": os.fspath(pdf_path),
            "retry": {"attempts": 0, "last_error": None, "next_attempt_at": None},
            "event_keys": [],
        },
    )
    capture_now = (now or datetime.now(WIB)).astimezone(WIB)
    if job["event_keys"]:
        return None

    if not pdf_path.is_file():
        job["phase"] = "downloading"
        save_state(state, resolved_state_path)
        try:
            download_pdf(temporary_pdf_path)
            _fsync_file(temporary_pdf_path)
            os.replace(temporary_pdf_path, pdf_path)
            _fsync_directory(reports_dir)
        except Exception as error:
            try:
                temporary_pdf_path.unlink()
            except FileNotFoundError:
                pass
            job["phase"] = "pending_download"
            _record_retry(job, error, capture_now)
            save_state(state, resolved_state_path)
            return None

    try:
        review = parse_weekly_ssf_pdf(source_message_id, pdf_path)
    except InvalidSsfReport as error:
        record_invalid_report(state, source_message_id, str(error))
        try:
            pdf_path.unlink()
        except FileNotFoundError:
            pass
        save_state(state, resolved_state_path)
        return None

    job["phase"] = "captured"
    job["review"] = _serialise_review(review)
    save_state(state, resolved_state_path)
    try:
        chart_paths = extract_charts(state, review, pdf_path, resolved_state_path)
        enqueue_review(state, review, chart_paths)
    except InvalidSsfReport as error:
        record_invalid_report(state, source_message_id, str(error))
        try:
            pdf_path.unlink()
        except FileNotFoundError:
            pass
        save_state(state, resolved_state_path)
        return None
    except ReportCaptureError as error:
        job["phase"] = "pending_extraction"
        _record_retry(job, error, capture_now)
        save_state(state, resolved_state_path)
        return review
    save_state(state, resolved_state_path)
    return review


def _discord_request(
    endpoint: str, bot_token: str, body: bytes, content_type: str
) -> dict[str, Any]:
    request = Request(
        f"https://discord.com/api/v10{endpoint}",
        data=body,
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": content_type,
            "User-Agent": "idx-ssf-watch-phintraco-weekly/1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            decoded_response = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Discord API request failed") from error
    if not isinstance(decoded_response, dict) or not isinstance(
        decoded_response.get("id"), str
    ):
        raise RuntimeError("Discord API response is missing a message ID")
    return decoded_response


def post_discord_text(
    channel_id: str, bot_token: str, content: str, nonce: str
) -> str:
    response = _discord_request(
        f"/channels/{channel_id}/messages",
        bot_token,
        json.dumps(
            {"content": content, "nonce": nonce, "enforce_nonce": True},
            separators=(",", ":"),
        ).encode("utf-8"),
        "application/json",
    )
    return response["id"]


def post_discord_file(
    channel_id: str, bot_token: str, chart_path: Path, nonce: str
) -> str:
    chart_data = chart_path.read_bytes()
    boundary = f"----idxssf{nonce}"
    payload = (
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"payload_json\"\r\n"
        "Content-Type: application/json\r\n\r\n"
        + json.dumps(
            {"nonce": nonce, "enforce_nonce": True},
            separators=(",", ":"),
        )
        + f"\r\n--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"files[0]\"; filename=\"{chart_path.name}\"\r\n"
        "Content-Type: image/png\r\n\r\n"
    ).encode("utf-8") + chart_data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    response = _discord_request(
        f"/channels/{channel_id}/messages",
        bot_token,
        payload,
        f"multipart/form-data; boundary={boundary}",
    )
    return response["id"]


def _first_undelivered_event(state: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for event_key, event in state["outbox"].items():
        if event["phase"] != "delivered" or event["chart_path"] is not None:
            return event_key, event
    return None


def _has_pending_report_job(state: dict[str, Any]) -> bool:
    return any(job.get("phase") != "completed" for job in state["report_jobs"].values())


def _cleanup_completed_jobs(state: dict[str, Any], state_path: Path | None) -> bool:
    changed = False
    for job in state["report_jobs"].values():
        event_keys = job.get("event_keys", [])
        if not event_keys or not all(
            state["outbox"].get(event_key, {}).get("phase") == "delivered"
            and state["outbox"].get(event_key, {}).get("chart_path") is None
            for event_key in event_keys
        ):
            continue
        if job.get("phase") != "completed":
            job["phase"] = "completed"
            changed = True
        pdf_value = job.get("pdf_path")
        if pdf_value:
            try:
                Path(pdf_value).unlink()
            except FileNotFoundError:
                pass
            job["pdf_path"] = None
            changed = True
    return changed


def drain_outbox(
    state: dict[str, Any],
    channel_id: str,
    bot_token: str,
    state_path: Path | None = None,
    now: datetime | None = None,
) -> int:
    """Deliver source-order text then cached chart, stopping at a deferred or failed leg."""
    resolved_state_path = _state_path(state_path)
    delivery_now = (now or datetime.now(WIB)).astimezone(WIB)
    delivered_legs = 0
    if _cleanup_completed_jobs(state, resolved_state_path):
        save_state(state, resolved_state_path)

    while (next_event := _first_undelivered_event(state)) is not None:
        event_key, event = next_event
        if not _delivery_retry_is_due(event, delivery_now):
            return delivered_legs
        try:
            if event["phase"] == "pending_text":
                event["text_discord_id"] = post_discord_text(
                    channel_id,
                    bot_token,
                    event["text"],
                    discord_nonce(event_key, "text"),
                )
                event["phase"] = "pending_chart"
                event["last_error"] = None
                event["next_attempt_at"] = None
                save_state(state, resolved_state_path)
                delivered_legs += 1
                continue
            if event["phase"] == "pending_chart":
                chart_path = Path(event["chart_path"])
                event["chart_discord_id"] = post_discord_file(
                    channel_id,
                    bot_token,
                    chart_path,
                    discord_nonce(event_key, "chart"),
                )
                event["phase"] = "pending_chart_cleanup"
                event["last_error"] = None
                event["next_attempt_at"] = None
                save_state(state, resolved_state_path)
                delivered_legs += 1
                continue
            if event["phase"] in {"pending_chart_cleanup", "delivered"}:
                chart_path_value = event["chart_path"]
                if chart_path_value is None:
                    raise StateBlockedError("chart cleanup is missing its cached chart")
                phase_before_cleanup = event["phase"]
                Path(chart_path_value).unlink(missing_ok=True)
                if phase_before_cleanup == "pending_chart_cleanup":
                    state["stats"]["delivered"] += 1
                    state["last_delivery_success"] = delivery_now.isoformat()
                event["phase"] = "delivered"
                event["chart_path"] = None
                event["last_error"] = None
                event["next_attempt_at"] = None
                _cleanup_completed_jobs(state, resolved_state_path)
                save_state(state, resolved_state_path)
                continue
            raise StateBlockedError(f"unsupported outbox phase {event['phase']!r}")
        except (OSError, RuntimeError) as error:
            _record_delivery_retry(event, error, delivery_now)
            save_state(state, resolved_state_path)
            return delivered_legs
    return delivered_legs


def _bounded_reason(reason: str) -> str:
    """Keep operational reasons useful without retaining sensitive source details."""
    clean = re.sub(r"\s+", " ", str(reason)).strip()
    clean = re.sub(
        r"""(?ix)\b
        (?P<key>[a-z_]*(?:token|secret|session|password|api[_-]?(?:key|hash))[a-z_]*)
        \s*(?:=|:)\s*
        (?:"[^"]*"|'[^']*'|[^\s,;]+)
        """,
        r"\g<key>=<redacted>",
        clean,
    )
    clean = re.sub(r"(?<!\w)(?:~|/)[^\s]+", "<path>", clean)
    clean = re.sub(r"\bb[\"'][^\"']{1,512}[\"']", "<bytes>", clean)
    clean = re.sub(r"\S+\.pdf(?:\S*)", "<pdf>", clean, flags=re.IGNORECASE)
    return clean[:180] or "unspecified failure"


def _fatal_hour_key(now: datetime) -> str:
    return now.astimezone(WIB).strftime("%Y-%m-%dT%H:%z")


def error_fingerprint(reason: str) -> str:
    return hashlib.sha256(_bounded_reason(reason).encode("utf-8")).hexdigest()[:16]


def format_heartbeat(now: datetime, stats: RunStats) -> str:
    return (
        f"🫀 idx-ssf · {now.astimezone(WIB):%H:%M} WIB · "
        f"source={stats.source_status} · reports={stats.reports} · alerts={stats.alerts}"
        + (" ⚠️" if stats.degraded else "")
    )


def format_fatal(now: datetime, reason: str) -> str:
    return (
        f"❌ idx-ssf · {now.astimezone(WIB):%H:%M} WIB · "
        f"failed: {_bounded_reason(reason)}"
    )


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def post_operational_text(content: str, nonce: str, dry_run: bool) -> str | None:
    """Post an operations message, leaving dry-run delivery observable but side-effect free."""
    if dry_run or os.environ.get("IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST") == "1":
        return f"dry-run-{nonce}"
    token = _env("DISCORD_BOT_TOKEN")
    if token is None:
        return None
    return post_discord_text(HEARTBEAT_CHANNEL_ID, token, content, nonce)


def post_heartbeat(
    state: dict[str, Any],
    now: datetime,
    stats: RunStats,
    dry_run: bool,
    force_heartbeat: bool = False,
) -> bool:
    nonce_prefix = "force-heartbeat" if force_heartbeat else "heartbeat"
    message_id = post_operational_text(
        format_heartbeat(now, stats),
        f"{nonce_prefix}-{now.astimezone(WIB):%Y%m%d%H%M}",
        dry_run,
    )
    if message_id is None:
        return False
    state["last_heartbeat_run"] = now.astimezone(WIB).isoformat()
    save_state(state)
    return True


def report_fatal(
    state: dict[str, Any], now: datetime, reason: str, dry_run: bool
) -> bool:
    """Post at most one instance of an operational failure fingerprint each hour."""
    fingerprint = error_fingerprint(reason)
    hour = _fatal_hour_key(now)
    previous = state.get("last_error_notice")
    fingerprints: list[str] = []
    if isinstance(previous, dict) and previous.get("hour") == hour:
        raw_fingerprints = previous.get("fingerprints")
        if isinstance(raw_fingerprints, list):
            fingerprints = [
                value for value in raw_fingerprints if isinstance(value, str)
            ][-MAX_FATAL_FINGERPRINTS_PER_HOUR:]
    if fingerprint in fingerprints:
        return False
    message_id = post_operational_text(
        format_fatal(now, reason), f"fatal-{fingerprint}-{hour}", dry_run
    )
    if message_id is None:
        return False
    state["last_error_notice"] = {
        "hour": hour,
        "fingerprints": (fingerprints + [fingerprint])[
            -MAX_FATAL_FINGERPRINTS_PER_HOUR:
        ],
    }
    save_state(state)
    return True


@contextlib.contextmanager
def run_lock() -> Any:
    """Acquire the watcher lock without waiting for another invocation."""
    path = _state_path().parent / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def make_client() -> Any:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    api_id = _env("TELEGRAM_API_ID")
    api_hash = _env("TELEGRAM_API_HASH")
    session = _env("POLYCOP_SESSION_STRING")
    if api_id is None or api_hash is None or session is None:
        raise RuntimeError("Telegram credentials are incomplete")
    return TelegramClient(StringSession(session), int(api_id), api_hash)


def resilience() -> PolyCopResilience:
    return PolyCopResilience.from_defaults()


def _connection_metadata(client: object) -> tuple[int | None, str | None]:
    session = getattr(client, "session", None)
    dc_id = getattr(session, "dc_id", None)
    endpoint = getattr(session, "server_address", None)
    port = getattr(session, "port", None)
    if isinstance(endpoint, str) and isinstance(port, int):
        endpoint = f"{endpoint}:{port}"
    return (dc_id if isinstance(dc_id, int) else None, endpoint if isinstance(endpoint, str) else None)


async def _is_client_authorized(client: object) -> bool:
    checker = getattr(client, "is_user_authorized", None)
    if checker is None:
        return True
    return bool(await checker())


async def _get_client_identity(client: object) -> object | None:
    getter = getattr(client, "get_me", None)
    return await getter() if getter is not None else None


async def _disconnect_quietly(client: object) -> None:
    disconnect = getattr(client, "disconnect", None)
    if disconnect is None:
        return
    try:
        await disconnect()
    except Exception:
        pass


def deliver_resilience_notification(
    control: PolyCopResilience, now: datetime, dry_run: bool
) -> None:
    try:
        notification = control.claim_notification(WATCHER_NAME, now)
    except ResilienceStateBlockedError:
        return
    if notification is None:
        return
    try:
        message_id = post_operational_text(
            notification.content, notification.event_key, dry_run
        )
    except Exception:
        return
    if message_id is None:
        return
    try:
        control.acknowledge_notification(notification.claim_id, now)
    except (ResilienceStateBlockedError, ValueError):
        return


def _report_resilience_state_blocked(now: datetime, dry_run: bool) -> None:
    try:
        post_operational_text(
            f"❌ telegram-polycop · {now.astimezone(WIB):%H:%M} WIB · control state unavailable",
            f"telegram-resilience-state-blocked-{now.astimezone(WIB):%Y%m%d%H}",
            dry_run,
        )
    except Exception:
        pass


async def resolve_source(client: Any) -> Any:
    dialogs = await client.get_dialogs()
    for dialog in dialogs:
        entity = getattr(dialog, "entity", None)
        if getattr(entity, "id", None) == SOURCE_CHANNEL_ID:
            return entity
    raise RuntimeError("Phintraco source channel is not accessible")


async def latest_source_message_id(client: Any, entity: Any) -> int:
    messages = await client.get_messages(entity, limit=1)
    return int(messages[0].id) if messages else 0


async def fetch_unseen_messages(client: Any, entity: Any, minimum_id: int) -> list[Any]:
    return [
        message
        async for message in client.iter_messages(
            entity, min_id=minimum_id, reverse=True
        )
    ]


def _candidate_filename(message: Any) -> str | None:
    document = getattr(message, "document", None)
    if document is None or getattr(document, "mime_type", None) != "application/pdf":
        return None
    for attribute in getattr(document, "attributes", ()):
        filename = getattr(attribute, "file_name", None)
        if isinstance(filename, str):
            return filename
    file_name = getattr(getattr(message, "file", None), "name", None)
    return file_name if isinstance(file_name, str) else None


def discover_candidates(messages: list[Any] | tuple[Any, ...]) -> tuple[SsfCandidate, ...]:
    """Return only strict Weekly SSF PDF candidates in ascending Telegram ID order."""
    candidates = []
    for message in messages:
        filename = _candidate_filename(message)
        source_message_id = getattr(message, "id", None)
        if (
            isinstance(source_message_id, int)
            and filename is not None
            and PDF_FILENAME_RE.fullmatch(filename) is not None
        ):
            candidates.append(SsfCandidate(source_message_id, filename, message))
    return tuple(sorted(candidates, key=lambda candidate: candidate.source_message_id))


def select_newest_valid_candidate(
    candidates: tuple[SsfCandidate, ...] | list[SsfCandidate],
) -> SsfCandidate | None:
    """Choose the newest candidate from a caller-supplied validated candidate set."""
    return max(candidates, key=lambda candidate: candidate.source_message_id, default=None)


async def _download_candidate(
    client: Any, candidate: SsfCandidate, temporary_pdf_path: Path
) -> None:
    await client.download_media(candidate.message, file=os.fspath(temporary_pdf_path))


async def _capture_candidate(
    client: Any, state: dict[str, Any], candidate: SsfCandidate, now: datetime
) -> WeeklySsfReview | None:
    loop = asyncio.get_running_loop()

    def download(temporary_pdf_path: Path) -> None:
        future = asyncio.run_coroutine_threadsafe(
            _download_candidate(client, candidate, temporary_pdf_path), loop
        )
        future.result()

    return await asyncio.to_thread(
        capture_report, state, candidate.source_message_id, download, None, now
    )


def _queued_review(state: dict[str, Any], source_message_id: int) -> bool:
    job = state["report_jobs"].get(str(source_message_id), {})
    event_keys = job.get("event_keys")
    return (
        job.get("phase") == "queued"
        and isinstance(event_keys, list)
        and bool(event_keys)
        and all(event_key in state["outbox"] for event_key in event_keys)
    )


async def _retry_pending_reports(
    client: Any, entity: Any, state: dict[str, Any], now: datetime
) -> tuple[int, bool]:
    reports = 0
    degraded = False
    for source_key, job in tuple(state["report_jobs"].items()):
        if job.get("phase") not in {"pending_download", "pending_extraction"}:
            continue
        if not _retry_is_due(job, now):
            degraded = True
            continue
        source_message_id = int(source_key)
        message = await client.get_messages(entity, ids=source_message_id)
        candidate_messages = discover_candidates((message,) if message is not None else ())
        if not candidate_messages:
            degraded = True
            continue
        review = await _capture_candidate(client, state, candidate_messages[0], now)
        if review is not None and _queued_review(state, source_message_id):
            reports += 1
        elif source_key in state["report_jobs"]:
            degraded = True
    return reports, degraded


async def _bootstrap(
    client: Any,
    entity: Any,
    state: dict[str, Any],
    newest_source_message_id: int,
    now: datetime,
) -> tuple[str, int, int, bool]:
    if newest_source_message_id > 0:
        async for message in client.iter_messages(
            entity, max_id=newest_source_message_id + 1
        ):
            candidates = discover_candidates((message,))
            if not candidates:
                continue
            candidate = candidates[0]
            if _queued_review(state, candidate.source_message_id):
                state["observed_message_id"] = newest_source_message_id
                state["bootstrap_complete"] = True
                save_state(state)
                return (
                    "ok",
                    0,
                    len(state["report_jobs"][str(candidate.source_message_id)]["event_keys"]),
                    False,
                )
            job = state["report_jobs"].get(str(candidate.source_message_id))
            if isinstance(job, dict) and job.get("phase") in {
                "pending_download",
                "pending_extraction",
            }:
                return "missing", 0, 0, True
            review = await _capture_candidate(client, state, candidate, now)
            if review is not None and _queued_review(state, candidate.source_message_id):
                state["observed_message_id"] = newest_source_message_id
                state["bootstrap_complete"] = True
                save_state(state)
                return (
                    "ok",
                    1,
                    len(state["report_jobs"][str(candidate.source_message_id)]["event_keys"]),
                    False,
                )
            if str(candidate.source_message_id) in state["report_jobs"]:
                return "missing", 0, 0, True
    state["observed_message_id"] = newest_source_message_id
    state["bootstrap_complete"] = True
    save_state(state)
    return "missing", 0, 0, False


async def _ingest_unseen(
    client: Any, entity: Any, state: dict[str, Any], now: datetime
) -> tuple[str, int, int, bool]:
    messages = await fetch_unseen_messages(
        client, entity, int(state["observed_message_id"])
    )
    candidates_by_id = {
        candidate.source_message_id: candidate for candidate in discover_candidates(messages)
    }
    source_status = "missing"
    reports = alerts = 0
    degraded = False
    for message in messages:
        source_message_id = int(message.id)
        candidate = candidates_by_id.get(source_message_id)
        if candidate is not None:
            review = await _capture_candidate(client, state, candidate, now)
            if review is not None and _queued_review(state, source_message_id):
                source_status = "ok"
                reports += 1
                alerts += len(state["report_jobs"][str(source_message_id)]["event_keys"])
            elif str(source_message_id) in state["invalid_reports"]:
                source_status = "invalid"
            else:
                degraded = True
        state["observed_message_id"] = source_message_id
        save_state(state)
    state["last_poll_success"] = datetime.now(WIB).isoformat()
    save_state(state)
    return source_status, reports, alerts, degraded


async def run(
    now: datetime | None = None,
    dry_run: bool = False,
    force_heartbeat: bool = False,
) -> dict[str, bool]:
    now = now or datetime.now(WIB)
    with run_lock() as acquired:
        if not acquired:
            return {"wakeAgent": False}
        control = resilience()
        decision = await acquire_probe_after_active_lease(control, WATCHER_NAME, now)
        if decision.kind == "state_blocked":
            _report_resilience_state_blocked(now, dry_run)
            return {"wakeAgent": False}
        if decision.kind != "probe":
            deliver_resilience_notification(control, now, dry_run)
            return {"wakeAgent": False}

        client = make_client()
        try:
            await client.connect()
            if not await _is_client_authorized(client):
                control.record_auth_required(decision.lease_id, WATCHER_NAME, now)
                deliver_resilience_notification(control, now, dry_run)
                await _disconnect_quietly(client)
                return {"wakeAgent": False}
            await _get_client_identity(client)
            dc_id, endpoint = _connection_metadata(client)
            control.record_authenticated_success(
                decision.lease_id, WATCHER_NAME, now, dc_id, endpoint
            )
            deliver_resilience_notification(control, now, dry_run)
        except Exception as error:
            if is_transport_error(error):
                control.record_transport_failure(
                    decision.lease_id, WATCHER_NAME, error, now
                )
                deliver_resilience_notification(control, now, dry_run)
                await _disconnect_quietly(client)
                return {"wakeAgent": False}
            await _disconnect_quietly(client)
            raise

        state = load_state()
        state["stats"]["runs"] += 1
        save_state(state)
        try:
            entity = await resolve_source(client)
            newest_source_message_id = await latest_source_message_id(client, entity)
            retry_reports, retry_degraded = await _retry_pending_reports(
                client, entity, state, now
            )
            if not state["bootstrap_complete"]:
                source_status, reports, alerts, degraded = await _bootstrap(
                    client, entity, state, newest_source_message_id, now
                )
            else:
                source_status, reports, alerts, degraded = await _ingest_unseen(
                    client, entity, state, now
                )
            reports += retry_reports
            degraded = degraded or retry_degraded
            if state["bootstrap_complete"]:
                state["last_poll_success"] = now.astimezone(WIB).isoformat()
                save_state(state)
        finally:
            await client.disconnect()
        token = _env("DISCORD_BOT_TOKEN")
        delivered = 0
        if _first_undelivered_event(state) is not None:
            if dry_run:
                degraded = True
            elif token is None:
                degraded = True
            else:
                delivered = drain_outbox(state, ALERT_CHANNEL_ID, token, now=now)
        degraded = (
            degraded
            or _first_undelivered_event(state) is not None
            or _has_pending_report_job(state)
        )
        state["stats"]["reports"] += reports
        state["stats"]["alerts"] += alerts
        state["stats"]["delivered"] += delivered
        save_state(state)
        stats = RunStats(source_status, reports, alerts, degraded)
        post_heartbeat(
            state,
            now,
            stats,
            dry_run,
            force_heartbeat=force_heartbeat,
        )
        return {"wakeAgent": False}


def _report_fatal_best_effort(now: datetime, reason: str, dry_run: bool) -> None:
    try:
        with run_lock() as acquired:
            if acquired:
                report_fatal(load_state(), now, reason, dry_run)
    except Exception:
        pass


def main() -> int:
    now = datetime.now(WIB)
    dry_run = os.environ.get("IDX_SSF_WATCH_PHINTRACO_WEEKLY_NO_POST") == "1"
    force_heartbeat = (
        os.environ.get("IDX_SSF_WATCH_PHINTRACO_WEEKLY_FORCE_HEARTBEAT") == "1"
    )
    try:
        result = asyncio.run(
            run(
                now=now,
                dry_run=dry_run,
                force_heartbeat=force_heartbeat,
            )
        )
    except Exception as error:
        _report_fatal_best_effort(now, str(error), dry_run)
        result = {"wakeAgent": False}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
