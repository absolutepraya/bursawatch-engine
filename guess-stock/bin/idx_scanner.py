"""Read-only TradingView Indonesia scanner adapter.

The adapter is intentionally provider-specific at the edge and source-neutral
after parsing. It returns the exact requested columns and the provider fetch
timestamp so the caller can audit freshness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import json
from typing import Any, Callable, Mapping, Sequence
from urllib.error import URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "https://scanner.tradingview.com/indonesia/scan"
DEFAULT_COLUMNS = (
    "name",
    "description",
    "close",
    "change",
    "volume",
    "average_volume_10d_calc",
    "average_volume_20d_calc",
    "MACD.macd",
    "MACD.signal",
    "MACD.hist",
    "RSI",
    "Perf.1M",
    "Perf.3M",
    "Perf.6M",
    "Perf.YTD",
    "Perf.Y",
)


class ScannerError(RuntimeError):
    """Base class for scanner failures."""


class ScannerUnavailable(ScannerError):
    """The provider could not return a usable response."""


@dataclass(frozen=True, slots=True)
class ScannerFilter:
    left: str
    operation: str
    right: object

    def to_dict(self) -> dict[str, object]:
        return {"left": self.left, "operation": self.operation, "right": self.right}


@dataclass(frozen=True, slots=True)
class ScannerRequest:
    columns: tuple[str, ...] = DEFAULT_COLUMNS
    filters: tuple[ScannerFilter, ...] = ()
    offset: int = 0
    limit: int = 150
    language: str = "en"

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError("at least one scanner column is required")
        if self.offset < 0 or self.limit <= 0 or self.limit > 5000:
            raise ValueError("scanner range must be offset >= 0 and limit between 1 and 5000")

    def payload(self) -> dict[str, object]:
        return {
            "filter": [item.to_dict() for item in self.filters],
            "options": {"lang": self.language},
            "markets": ["indonesia"],
            "symbols": {"query": {"types": ["stock"]}, "tickers": []},
            "columns": list(self.columns),
            "range": [self.offset, self.offset + self.limit],
        }


@dataclass(frozen=True, slots=True)
class ScannerResult:
    provider: str
    source_url: str
    fetched_at: str
    total_count: int
    columns: tuple[str, ...]
    rows: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
            "total_count": self.total_count,
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
        }


class TradingViewScanner:
    """Small HTTP edge for TradingView's public Indonesia scanner endpoint."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = 15.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.opener = opener

    def scan(self, request: ScannerRequest | None = None) -> ScannerResult:
        request = request or ScannerRequest()
        body = json.dumps(request.payload(), separators=(",", ":")).encode("utf-8")
        http_request = Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": "hermes-guess-stock/1"},
            method="POST",
        )
        try:
            response = self.opener(http_request, timeout=self.timeout)
            try:
                raw = response.read()
                status = getattr(response, "status", 200)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            if status < 200 or status >= 300:
                raise ScannerUnavailable(f"TradingView scanner returned HTTP {status}")
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except ScannerUnavailable:
            raise
        except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            raise ScannerUnavailable("TradingView scanner unavailable") from exc

        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), Sequence):
            raise ScannerUnavailable("TradingView scanner returned malformed data")
        total_count = payload.get("totalCount", 0)
        if not isinstance(total_count, int) or isinstance(total_count, bool):
            raise ScannerUnavailable("TradingView scanner returned an invalid total count")

        rows: list[Mapping[str, object]] = []
        for index, item in enumerate(payload["data"]):
            if not isinstance(item, Mapping) or not isinstance(item.get("s"), str) or not isinstance(item.get("d"), Sequence):
                raise ScannerUnavailable(f"TradingView scanner row {index} is malformed")
            values = item["d"]
            row: dict[str, object] = {
                "symbol": item["s"],
                "ticker": item["s"].split(":", 1)[-1],
            }
            row.update(dict(zip(request.columns, values)))
            rows.append(row)

        return ScannerResult(
            provider="tradingview-indonesia",
            source_url=self.endpoint,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            total_count=total_count,
            columns=request.columns,
            rows=tuple(rows),
        )


def _parse_filter(values: Sequence[str]) -> ScannerFilter:
    left, operation, right = values
    try:
        parsed_right: object = json.loads(right)
    except json.JSONDecodeError:
        parsed_right = right
    return ScannerFilter(left, operation, parsed_right)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only TradingView Indonesia scanner")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--columns", default=",".join(DEFAULT_COLUMNS))
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--filter", action="append", nargs=3, metavar=("FIELD", "OPERATION", "VALUE"))
    args = parser.parse_args()
    request = ScannerRequest(
        columns=tuple(item for item in args.columns.split(",") if item),
        filters=tuple(_parse_filter(values) for values in args.filter or ()),
        offset=args.offset,
        limit=args.limit,
    )
    print(json.dumps(TradingViewScanner(endpoint=args.endpoint).scan(request).to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
