from __future__ import annotations

import json

import pytest

from idx_scanner import ScannerFilter, ScannerRequest, ScannerUnavailable, TradingViewScanner


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def read(self):
        return json.dumps(self.payload).encode()

    def close(self):
        self.closed = True


def test_request_contains_exchange_universe_and_requested_columns() -> None:
    request = ScannerRequest(
        columns=("name", "close", "MACD.hist"),
        filters=(ScannerFilter("close", "greater", 100),),
        offset=10,
        limit=20,
    )

    payload = request.payload()
    assert payload["markets"] == ["indonesia"]
    assert payload["symbols"] == {"query": {"types": ["stock"]}, "tickers": []}
    assert payload["range"] == [10, 30]
    assert payload["columns"] == ["name", "close", "MACD.hist"]
    assert payload["filter"] == [{"left": "close", "operation": "greater", "right": 100}]


def test_scanner_maps_rows_and_keeps_provider_metadata() -> None:
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        return FakeResponse({"totalCount": 844, "data": [{"s": "IDX:APEX", "d": [192, 189010000, -1.2]}]})

    result = TradingViewScanner(opener=opener).scan(
        ScannerRequest(columns=("close", "volume", "MACD.hist"), limit=1)
    )

    assert seen["url"].endswith("/indonesia/scan")
    assert seen["body"]["columns"] == ["close", "volume", "MACD.hist"]
    assert seen["timeout"] == 15.0
    assert result.provider == "tradingview-indonesia"
    assert result.total_count == 844
    assert result.rows[0] == {"symbol": "IDX:APEX", "ticker": "APEX", "close": 192, "volume": 189010000, "MACD.hist": -1.2}
    assert result.fetched_at.endswith("+00:00")


def test_malformed_response_fails_closed() -> None:
    def opener(request, timeout):
        return FakeResponse({"totalCount": "844", "data": []})

    with pytest.raises(ScannerUnavailable):
        TradingViewScanner(opener=opener).scan(ScannerRequest(columns=("close",)))
