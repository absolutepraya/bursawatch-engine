"""Bounded Yahoo security discovery, separate from news subject and facts."""
from __future__ import annotations

import re
import threading
import unicodedata

import news_subject


_SLOTS = threading.BoundedSemaphore(4)
_US_EXCHANGES = frozenset({"NMS", "NGM", "NCM", "NYQ", "ASE", "PCX", "BTS", "BATS"})


def _name(value: str) -> str:
    tokens = re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold())
    if tokens and tokens[0] == "pt":
        tokens.pop(0)
    while tokens and tokens[-1] in {"tbk", "inc", "incorporated", "corp", "corporation", "ltd", "limited", "plc"}:
        tokens.pop()
    return " ".join(tokens)


def _search(company: str) -> list[dict]:
    import yfinance as yf
    return yf.Search(company, max_results=8, news_count=0, lists_count=0,
                     include_cb=False, enable_fuzzy_query=False, timeout=3).quotes


def lookup_company(company: str, market: str = "ID", *, search=None) -> dict:
    if not isinstance(company, str) or not company.strip() or len(company) > 200:
        raise ValueError("company must contain one to 200 characters")
    if market not in {"ID", "US"}:
        raise ValueError("market must be ID or US")
    unresolved = {"status": "unresolved", "company": company, "market": market}
    if not _SLOTS.acquire(blocking=False):
        return unresolved
    results = []

    def run():
        try:
            results.extend((search or _search)(company))
        except Exception:
            pass
        finally:
            _SLOTS.release()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(3.5)
    if worker.is_alive():
        return unresolved
    matches = {}
    for row in results:
        if not isinstance(row, dict) or row.get("quoteType") not in {"EQUITY", "ETF"}:
            continue
        symbol, exchange = row.get("symbol"), row.get("exchange")
        if not isinstance(symbol, str):
            continue
        if market == "ID":
            if not re.fullmatch(r"[A-Z]{4}\.JK", symbol) or exchange != "JKT":
                continue
            ticker = symbol[:-3]
        else:
            if exchange not in _US_EXCHANGES or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", symbol):
                continue
            ticker = symbol
        names = [row.get("longname"), row.get("shortname")]
        name = next((name for name in names if isinstance(name, str) and _name(name) == _name(company)), None)
        if name is None:
            continue
        matches[symbol] = {"status": "verified", "company": company, "market": market,
                           "ticker": ticker, "symbol": symbol, "exchange": exchange,
                           "name": name, "source_url": f"https://finance.yahoo.com/quote/{symbol}/"}
    return next(iter(matches.values())) if len(matches) == 1 else unresolved


def lookup_payload(payload: object) -> dict:
    if type(payload) is not dict or set(payload) != {"company", "market"}:
        raise ValueError("lookup requires exactly company and market")
    return lookup_company(payload["company"], payload["market"])


def prepare_item(item: dict, source_text: str, *, market: str = "ID") -> tuple[dict, str | None]:
    """Verify externally discovered tickers; degrade lookup failure to name-only."""
    subject = news_subject.validate_subject(item["subject"], source_text)
    if item.get("route") != "exclude":
        news_subject.validate_route(subject, item["route"])
    ticker = item.get("ticker")
    if ticker is None:
        ticker = ""
    if not isinstance(ticker, str):
        raise ValueError("ticker must be text")
    if subject["kind"] != "company":
        if ticker:
            raise ValueError("noncompany subject cannot have a ticker")
        return item, None
    # A ticker supplied by the source keeps the existing source-only contract.
    # Discovery is needed only when the agent proposes a ticker from its lookup.
    try:
        news_subject.validate_ticker(ticker, source_text, market=market)
        return item, None
    except ValueError:
        news_subject.validate_ticker(ticker, ticker, market=market)
    identity = lookup_company(subject["name"], market)
    if identity.get("status") == "verified" and identity.get("ticker") == ticker:
        return item, ticker
    result = {**item, "ticker": ""}
    title = result.get("title")
    if isinstance(title, str) and title.startswith(ticker + ":"):
        result["title"] = subject["name"] + ":" + title[len(ticker) + 1:]
    return result, None
