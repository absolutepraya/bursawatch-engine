"""Bounded Yahoo security discovery, separate from news subject and facts."""
from __future__ import annotations

import re
import threading
import unicodedata

import news_subject


_SLOTS = threading.BoundedSemaphore(4)
_DETAIL_SLOTS = threading.BoundedSemaphore(2)
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


def _details(symbol: str) -> dict:
    import yfinance as yf
    return yf.Ticker(symbol).get_info()


def _headquarters_country(symbol: str, details) -> str | None:
    if not _DETAIL_SLOTS.acquire(blocking=False):
        return None
    results = []

    def run():
        try:
            results.append(details(symbol))
        except Exception:
            pass
        finally:
            _DETAIL_SLOTS.release()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(3.5)
    if worker.is_alive() or not results or not isinstance(results[0], dict):
        return None
    info = results[0]
    country = info.get("country")
    if info.get("symbol") != symbol or not isinstance(country, str) or not 1 <= len(country.strip()) <= 80:
        return None
    return country.strip()


def lookup_company(company: str, market: str = "ID", *, search=None, details=None) -> dict:
    if not isinstance(company, str) or not company.strip() or len(company) > 200:
        raise ValueError("company must contain one to 200 characters")
    if market not in {"ID", "US"}:
        raise ValueError("market must be ID or US")
    idx_symbol = re.fullmatch(r"([A-Z]{4})(?:\.JK)?", company.strip()) if market == "ID" else None
    expected_idx = idx_symbol.group(1) + ".JK" if idx_symbol else None
    unresolved = {"status": "unresolved", "company": company, "market": market}
    if not _SLOTS.acquire(blocking=False):
        return unresolved
    results = []

    def run():
        try:
            search_fn = search or _search
            queries = [expected_idx, idx_symbol.group(1)] if idx_symbol else [company]
            for query in dict.fromkeys(queries):
                try:
                    found = search_fn(query)
                    results.extend(found)
                except Exception:
                    continue
                if expected_idx and any(
                    isinstance(row, dict)
                    and row.get("symbol") == expected_idx
                    and row.get("exchange") == "JKT"
                    and row.get("quoteType") == "EQUITY"
                    and any(isinstance(row.get(field), str) and row[field].strip() for field in ("longname", "shortname"))
                    for row in found
                ):
                    break
        finally:
            _SLOTS.release()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    # IDX symbol lookup may make two sequential requests, each with a
    # three-second provider timeout. Reserve time for both attempts.
    worker.join(6.5 if expected_idx else 3.5)
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
            if expected_idx and (symbol != expected_idx or row.get("quoteType") != "EQUITY"):
                continue
            ticker = symbol[:-3]
        else:
            if exchange not in _US_EXCHANGES or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", symbol):
                continue
            ticker = symbol
        names = [row.get("longname"), row.get("shortname")]
        name = next((name for name in names if isinstance(name, str) and _name(name) == _name(company)), None)
        # An exact, explicitly requested exchange symbol is a different query
        # from a fuzzy company-name search. Keep both market and type checks.
        if name is None and row.get("quoteType") == "EQUITY" and (company.strip() == ticker or expected_idx == symbol):
            name = next((name for name in names if isinstance(name, str) and name.strip()), None)
        if name is None:
            continue
        if symbol in matches and _name(matches[symbol]["name"]) != _name(name):
            return unresolved
        matches[symbol] = {"status": "verified", "company": company, "market": market,
                           "ticker": ticker, "symbol": symbol, "exchange": exchange,
                           "name": name, "source_url": f"https://finance.yahoo.com/quote/{symbol}/"}
    if len(matches) != 1:
        return unresolved
    match = next(iter(matches.values()))
    if details is not None:
        country = _headquarters_country(match["symbol"], details)
        if country:
            match["headquarters_country"] = country
    return match


def lookup_payload(payload: object) -> dict:
    if type(payload) is not dict or set(payload) != {"company", "market"}:
        raise ValueError("lookup requires exactly company and market")
    return lookup_company(payload["company"], payload["market"], details=_details)


def _without_security(item: dict, subject: dict, ticker: str) -> dict:
    result = {**item, "ticker": ""}
    title = result.get("title")
    prefix = re.match(rf"^{re.escape(ticker)}\s*:\s*", title) if ticker and isinstance(title, str) else None
    if prefix is not None:
        body = title[prefix.end():].strip()
        result["title"] = body if subject["name"].casefold() in body.casefold() else subject["name"] + " " + body
    return result


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
    if "company" in subject:
        quote_route = news_subject.quote_route(subject, item.get("route", ""))
        if not ticker or quote_route is None:
            return _without_security(item, subject, ticker), None
        market = "US" if quote_route == "us_stocks_news" else "ID"
        identity = lookup_company(subject["name"], market)
        if identity.get("status") != "verified" and _source_binds_ticker(subject, ticker):
            identity = lookup_company(ticker, market)
        symbol_like_name = subject["name"].strip().casefold() == ticker.casefold()
        issuer_name = identity.get("name")
        exact_issuer = isinstance(issuer_name, str) and _name(issuer_name) == _name(subject["name"])
        issuer_pair = isinstance(issuer_name, str) and _source_binds_ticker(
            {"name": issuer_name, "evidence": source_text}, ticker
        )
        symbol_evidence = (not symbol_like_name or exact_issuer or issuer_pair
                           or _source_explicit_symbol(source_text, subject["evidence"], ticker))
        if identity.get("status") == "verified" and identity.get("ticker") == ticker and symbol_evidence:
            return item, ticker
        return _without_security(item, subject, ticker), None
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


def _source_binds_ticker(subject: dict, ticker: str) -> bool:
    """Accept only a short, explicit name/security pair in source evidence."""
    name = re.escape(subject["name"])
    symbol = re.escape(ticker)
    pattern = rf"(?<!\w){name}\s*(?:(?:stock|shares|saham)\s*,?\s*)?(?:\(\s*\$?{symbol}\s*\)|,\s*\${symbol}(?![A-Za-z0-9.-])|\${symbol}(?![A-Za-z0-9.-]))"
    return re.search(pattern, subject["evidence"], flags=re.IGNORECASE) is not None


def _source_explicit_symbol(source_text: str, evidence: str, ticker: str) -> bool:
    """Require a ticker headline or an explicit reference to the security."""
    symbol = re.escape(ticker)
    first_line = next((line.strip() for line in source_text.splitlines() if line.strip()), "")
    return (re.search(rf"^\${symbol}(?![A-Za-z0-9.-])", first_line) is not None
            or re.search(rf"(?m)^[ \t]*{symbol}[ \t]*:", source_text) is not None
            or re.search(rf"\b(?i:saham)\s+{symbol}(?![A-Za-z0-9.-])", source_text) is not None
            or re.search(rf"(?<!\w)\${symbol}(?![A-Za-z0-9.-])", evidence) is not None
            or re.search(rf"(?<!\w){symbol}\.JK(?![A-Za-z0-9.-])", evidence) is not None)
