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

    def unresolved_for(reason: str) -> dict:
        """Say why: only `no_match` means the provider answered and genuinely knows nothing."""
        return {**unresolved, "reason": reason}

    if not _SLOTS.acquire(blocking=False):
        return unresolved_for("busy")
    results = []
    answered = []

    def run():
        try:
            search_fn = search or _search
            queries = [expected_idx, idx_symbol.group(1)] if idx_symbol else [company]
            for query in dict.fromkeys(queries):
                try:
                    found = search_fn(query)
                    results.extend(found)
                    answered.append(query)
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
        return unresolved_for("timeout")
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
            return unresolved_for("ambiguous")
        matches[symbol] = {"status": "verified", "company": company, "market": market,
                           "ticker": ticker, "symbol": symbol, "exchange": exchange,
                           "name": name, "source_url": f"https://finance.yahoo.com/quote/{symbol}/"}
    if len(matches) != 1:
        return unresolved_for("ambiguous" if matches else "no_match" if answered else "error")
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
        result["title"] = news_subject.name_headline(subject["name"], body, ticker)
    return result


def prepare_item(item: dict, source_text: str, *, market: str = "ID", source_openings: tuple[str, ...] = ()) -> tuple[dict, str | None]:
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
        if not ticker and quote_route == "id_stocks_news" and _is_symbol_name(subject):
            # The sender wrote only a symbol. Verify it like a proposed ticker rather than leaving it unprefixed.
            ticker = subject["name"].strip()
            item = {**item, "ticker": ticker}
        if not ticker or quote_route is None:
            return _without_security(item, subject, ticker), None
        market = "US" if quote_route == "us_stocks_news" else "ID"
        symbol_like_name = subject["name"].strip().casefold() == ticker.casefold()
        explicit_symbol = _source_explicit_symbol(source_text, subject["evidence"], ticker, source_openings)
        identity = lookup_company(subject["name"], market)
        if identity.get("status") != "verified" and (_source_binds_ticker(subject, ticker)
                                                       or (symbol_like_name and explicit_symbol)):
            identity = lookup_company(ticker, market)
        if (symbol_like_name and identity.get("status") != "verified" and identity.get("reason") == "no_match"
                and market == "ID" and _is_symbol_name(subject) and subject["name"].strip() == ticker):
            # This is a forwarder: an IDX symbol the sender wrote, which Yahoo has no record of at all, is
            # kept as written. Its tracker falls back to placeholders. Any ambiguity or provider failure
            # still drops the ticker below.
            return item, ticker
        issuer_name = identity.get("name")
        if symbol_like_name and (not isinstance(issuer_name, str) or not issuer_name.strip()):
            return _without_security(item, subject, ticker), None
        if (not symbol_like_name and not _issuer_named_in(subject["name"], _focus_sentence(item["subject"]["evidence"]))
                and not _source_binds_ticker(subject, ticker, anchored=True)):
            return _without_security(item, subject, ticker), None
        exact_issuer = isinstance(issuer_name, str) and _name(issuer_name) == _name(subject["name"])
        issuer_pair = isinstance(issuer_name, str) and _source_binds_ticker(
            {"name": issuer_name, "evidence": subject["evidence"]}, ticker, anchored=True
        )
        symbol_evidence = not symbol_like_name or exact_issuer or issuer_pair or explicit_symbol
        if symbol_like_name and isinstance(issuer_name, str):
            evidence = subject["evidence"]
            named_issuer = _name(issuer_name) != ticker.casefold() and _issuer_named_in(issuer_name, evidence, anchored=True)
            if not issuer_pair and not named_issuer:
                return _without_security(item, subject, ticker), None
            # A symbol can identify different companies on different exchanges.
            # If the focus evidence names a different issuer, do not let the
            # model-selected market attach this issuer's quote to it.
            other_market = "US" if market == "ID" else "ID"
            other = lookup_company(ticker, other_market)
            other_name = other.get("name") if other.get("status") == "verified" else None
            if (isinstance(other_name, str) and _name(other_name) != _name(issuer_name)
                    and _issuer_named_in(other_name, evidence)):
                return _without_security(item, subject, ticker), None
            # Even an unavailable other-market lookup must not turn an explicit
            # different legal company name into proof of this issuer.
            if (_has_legal_company_name(evidence) and not _issuer_named_in(issuer_name, evidence)
                    and not _source_binds_ticker({"name": issuer_name, "evidence": evidence}, ticker)):
                return _without_security(item, subject, ticker), None
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


def _is_symbol_name(subject: dict) -> bool:
    """A subject named only by a four-letter IDX-style symbol that the focus evidence also contains."""
    name = subject["name"].strip()
    return (re.fullmatch(r"[A-Z]{4}", name) is not None
            and re.search(rf"(?<![A-Za-z0-9]){name}(?![A-Za-z0-9])", subject["evidence"]) is not None)


def _source_binds_ticker(subject: dict, ticker: str, *, anchored: bool = False) -> bool:
    """Accept only a short, explicit name/security pair in source evidence."""
    name = re.escape(subject["name"])
    symbol = re.escape(ticker)
    end = r"(?!\w|[.-]\w)"
    start = r"\A\s*" if anchored else r"(?<!\w)"
    pattern = rf"{start}{name}[ \t]*(?:(?:stock|shares|saham)[ \t]*,?[ \t]*)?(?:\([ \t]*\$?{symbol}[ \t]*\)|,[ \t]*\${symbol}{end}|\${symbol}{end})"
    if re.search(pattern, subject["evidence"], flags=re.IGNORECASE) is not None:
        return True
    # Indonesian legal suffix punctuation and the parenthesized state-owned
    # designation vary between source articles and the provider's name. Do
    # not fuzzy-match the substantive issuer name or an intervening company.
    issuer = subject["name"]
    match = re.fullmatch(r"(?i)PT\s+(.+?)\s+(?:\(Persero\)\s+)?Tbk\.?", issuer.strip())
    if not match:
        return False
    core = re.escape(match.group(1))
    idx_pair = rf"{start}(?:PT\s+)?{core}\s+(?:\(Persero\)\s+)?Tbk\.?[ \t]*\([ \t]*\$?{symbol}[ \t]*\)"
    return re.search(idx_pair, subject["evidence"], flags=re.IGNORECASE) is not None


def _issuer_named_in(name: str, evidence: str, *, anchored: bool = False) -> bool:
    """Match a normalized issuer name in the bounded focus evidence."""
    tokens = _name(name).split()
    if not tokens or sum(map(len, tokens)) < 4:
        return False
    start = r"\A\s*(?:pt\s+)?" if anchored else r"(?<!\w)"
    pattern = start + r"[\W_]+".join(map(re.escape, tokens)) + r"(?!\w)"
    return re.search(pattern, unicodedata.normalize("NFKC", evidence).casefold()) is not None


_ABBREVIATIONS = frozenset({"inc", "corp", "ltd", "co", "tbk", "pt", "persero", "no", "st", "dr", "mr", "mrs", "ms", "jr", "sr", "vs"})


def _focus_sentence(evidence: str) -> str:
    """The first sentence or line: the focus company is named there, not in a later counterparty mention.

    Takes the raw evidence, because validation collapses line breaks. A sentence ends at `.`, `!` or `?`
    followed by whitespace, whatever case the next sentence starts with, except after a legal or title
    abbreviation such as `Inc.`, `Tbk.` or `Dr.`.
    """
    text = evidence.strip()
    for match in re.finditer(r"\n|(\w*)([.!?])[\"')\]]*\s+", text):
        if match.group(2) is None:
            return text[:match.start()]
        if match.group(1).casefold() not in _ABBREVIATIONS:
            return text[:match.end(2)]
    return text


def _has_legal_company_name(evidence: str) -> bool:
    """Recognize legal-name markers that require issuer corroboration."""
    return re.search(r"(?i)\b(?:corporation|incorporated|inc|corp|tbk|limited|ltd|plc)\b", evidence) is not None


def _source_explicit_symbol(source_text: str, evidence: str, ticker: str, source_openings: tuple[str, ...] = ()) -> bool:
    """Require a ticker headline or an explicit reference to the security."""
    symbol = re.escape(ticker)
    end = r"(?!\w|[.-]\w)"
    sources = [source_text, *(part for part in source_openings if part and part in source_text)]
    first_lines = (next((line.strip() for line in part.splitlines() if line.strip()), "") for part in sources)
    focus_mentioned = re.search(rf"(?<!\w){symbol}(?!\w)", evidence, re.IGNORECASE) is not None
    return ((focus_mentioned and any(re.search(rf"^\${symbol}{end}", line) is not None for line in first_lines))
            or (focus_mentioned and re.search(rf"(?m)^[ \t]*{symbol}[ \t]*:", source_text) is not None)
            or re.search(rf"\b(?i:saham)[ \t]+\$?{symbol}{end}", evidence) is not None
            or re.search(rf"(?<!\w)\${symbol}{end}", evidence) is not None
            or re.search(rf"(?<!\w){symbol}\.JK{end}", evidence) is not None)
