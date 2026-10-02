"""Shared news writing, deterministic quotes and immutable Discord cards.

Source owners retain relevance, routing, leases, receipts and retry state.
This module never submits messages or decides whether a source is news.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
import re
import threading
import time

VERSION = "stock-news-v1"
LIMIT = 2000
MARKER = "*(Ringkasan)* "
GREEN = "<:green:1531274822221434911>"
RED = "<:red:1531274756853202974>"
GREY = "<:grey:1531279158913536182>"
WRITING_INSTRUCTION = (
    "For issuer news, start the headline with the exact exchange TICKER followed by a colon. For macro or industry news, use a natural headline. "
    "Report the news directly in factual Bahasa Indonesia, starting with the issuer, action, or actual subject. "
    "Avoid generic writer narration and saya/kami. Preserve attribution for research estimates, forecasts and guidance, "
    "including period, units and uncertainty. Prefer two short paragraphs separated by \\n\\n for longer summaries; "
    "a short or cohesive item can use one paragraph. Use judgment, without a fixed length threshold, padding or invented facts. "
    "Paragraph style must never make an eligible item undeliverable. Return plain summary text without a Ringkasan label; "
    "the renderer adds it once. Do not generate the latest quote or 1D/1W/1M/3M tracker in the summary. "
)
ITEMS_INSTRUCTION = (
    "Split clearly independent issuer developments into ordered items, one per issuer, even when several dividends or "
    "suspension reopenings share a sentence. GIAA rights issue and UNTR buyback are two items; dividends for DADA and NICL, "
    "ENRG rights issue and reopening SINI/SMMT/SONA are six items. Keep a connected transaction or a shared macro/sector "
    "thesis as one item, using its central issuer when appropriate. Mere company mentions are not separate stories. "
    "Preserve the original source URL and date. Omit missing amounts rather than inventing them. "
)


def normalize_summary(value: str, *, marked: bool = False) -> str:
    """Accept old labels and flexible spacing, without a semantic style gate."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace(MARKER.rstrip(), "")
    paragraphs = re.split(r"\n[^\S\n]*\n", value)
    body = "\n\n".join(" ".join(p.split()) for p in paragraphs if p.strip())
    return MARKER + body if marked else body


def ticker_from_title(title: str | None, route: str | None) -> str | None:
    if route not in {"id_stocks_news", "us_stocks_news"} or not isinstance(title, str):
        return None
    match = re.match(r"^([A-Z][A-Z0-9.\-]{0,19}):(?:\s|$)", title)
    return match.group(1) if match else None


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _delta(latest, previous):
    if previous is None or previous <= 0:
        return None, None
    return latest - previous, (latest / previous - 1) * 100


_QUOTE_SLOTS = threading.BoundedSemaphore(4)


def _bounded_quote(fetch, ticker, route, timeout):
    if not _QUOTE_SLOTS.acquire(blocking=False):
        return None
    complete = threading.Event()
    result = []

    def run():
        try:
            result.append(fetch(ticker, route))
        except Exception:
            result.append(None)
        finally:
            _QUOTE_SLOTS.release()
            complete.set()

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        _QUOTE_SLOTS.release()
        return None
    return result[0] if complete.wait(timeout) else None


def get_market_snapshot(ticker: str, route: str = "id_stocks_news") -> dict | None:
    return _bounded_quote(_fetch_market_snapshot, ticker, route, 3.0)


def _history_matches_quote_session(history, quote) -> bool:
    """Only apply session offsets when the quote and final bar share a date."""
    try:
        metadata = quote.get_history_metadata()
        exchange_timezone = ZoneInfo(metadata["exchangeTimezoneName"])
        market_time = metadata.get("regularMarketTime")
        if isinstance(market_time, datetime):
            if market_time.tzinfo is None:
                return False
            quote_date = market_time.astimezone(exchange_timezone).date()
        else:
            market_time = _number(market_time)
            if market_time is None or market_time <= 0:
                return False
            quote_date = datetime.fromtimestamp(market_time, exchange_timezone).date()
        last_bar = history.index[-1]
        if last_bar.tzinfo is not None:
            last_bar = last_bar.astimezone(exchange_timezone)
        return last_bar.date() == quote_date
    except Exception:
        return False


def _fetch_market_snapshot(ticker: str, route: str) -> dict | None:
    """Bounded native-currency Yahoo snapshot. Every provider failure is optional."""
    if route not in {"id_stocks_news", "us_stocks_news"} or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,19}", ticker):
        return None
    try:
        import yfinance as yf
        symbol = f"{ticker}.JK" if route == "id_stocks_news" else ticker.replace(".", "-")
        quote = yf.Ticker(symbol)
        history = quote.history(period="1y", interval="1d", auto_adjust=False, raise_errors=True, timeout=5)
        # Keep missing sessions in place so offsets cannot slide across gaps.
        closes = [n if n is not None and n > 0 else None for n in map(_number, history.get("Close", []))]
        fast = quote.fast_info
        currency = "IDR" if route == "id_stocks_news" else "USD"
        actual_currency = fast.get("currency")
        if actual_currency is not None and actual_currency != currency:
            return None
        fast_latest = _number(fast.get("last_price"))
        if fast_latest is not None and fast_latest <= 0:
            fast_latest = None
        latest = fast_latest if fast_latest is not None else (closes[-1] if closes else None)
        if latest is None or latest <= 0:
            return None
        aligned = bool(closes) and (fast_latest is None or _history_matches_quote_session(history, quote))
        prior = _number(fast.get("previous_close"))
        if prior is None and aligned and len(closes) >= 2:
            prior = closes[-2]
        result = {"latest_price": latest, "currency": currency, "as_of": datetime.now(timezone.utc).isoformat()}
        for name, earlier in (("one_day", prior), ("one_week", closes[-6] if aligned and len(closes) >= 6 else None),
                              ("one_month", closes[-23] if aligned and len(closes) >= 23 else None),
                              ("three_month", closes[-67] if aligned and len(closes) >= 67 else None)):
            result[name + "_change"], result[name + "_percent"] = _delta(latest, earlier)
        return result
    except Exception:
        return None


def _field(snapshot, key):
    return snapshot.get(key) if isinstance(snapshot, Mapping) else getattr(snapshot, key, None)


def deduplicate_items(items):
    """Keep the first identical news item in one new submission, in order."""
    unique, seen = [], set()
    for item in items:
        route = _field(item, "route")
        if route in {"id_stocks_news", "us_stocks_news", "macro_news", "id_industry_news"}:
            title = _field(item, "title") or ""
            key = (route, " ".join(title.split()),
                   " ".join(normalize_summary(_field(item, "summary")).split()),
                   _field(item, "ticker") or ticker_from_title(title, route), _field(item, "sentiment"))
            if key in seen:
                continue
            seen.add(key)
        unique.append(item)
    return unique


def market_block(snapshot, currency: str = "IDR") -> str:
    def amount(value, signed=False):
        prefix = "+" if signed and value > 0 else "-" if signed and value < 0 else ""
        text = f"{round(abs(value)):,}".replace(",", ".") if currency == "IDR" else f"{abs(value):,.2f}"
        return prefix + text

    def metric(label, key):
        change, percent = _number(_field(snapshot, key + "_change")), _number(_field(snapshot, key + "_percent"))
        if change is None or percent is None:
            return f"{GREY} {label}: **-**"
        direction = GREEN if change > 0 else RED if change < 0 else GREY
        return f"{direction} {label}: **{amount(change, True)} ({percent:+.2f}%)**"

    latest = _number(_field(snapshot, "latest_price"))
    price = amount(latest) if latest is not None and latest > 0 else "-"
    return (f"Harga terakhir ({currency}): **{price}**\n"
            f"{metric('1D', 'one_day')}, {metric('1W', 'one_week')},\n"
            f"{metric('1M', 'one_month')}, {metric('3M', 'three_month')}")


def discord_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _fit_index(value: str, limit: int) -> int:
    units = 0
    for index, character in enumerate(value):
        units += 2 if ord(character) > 0xFFFF else 1
        if units > limit:
            return index
    return len(value)


def render_card(heading: str, summary: str, source_url: str, source_label: str, *, route=None, snapshot=None) -> list[str]:
    body = normalize_summary(summary, marked=True)
    sections = [heading, body]
    if route in {"id_stocks_news", "us_stocks_news"}:
        sections.append(market_block(snapshot, "USD" if route == "us_stocks_news" else "IDR"))
    sections.append(f"[View on {source_label}](<{source_url}>)")
    content = "\n\n".join(sections)
    if discord_length(content) <= LIMIT:
        return [content]
    compact = "\n\n".join([heading, " ".join(body.split()), *sections[2:]])
    if discord_length(compact) <= LIMIT:
        return [compact]
    # Split prose without losing facts; keep market block and source anchor atomic.
    messages = []
    remainder = heading + "\n\n" + body
    while discord_length(remainder) > LIMIT:
        maximum = _fit_index(remainder, LIMIT)
        cut = remainder.rfind(" ", 0, maximum + 1)
        cut = cut if cut > 0 else maximum
        messages.append(remainder[:cut].rstrip())
        remainder = remainder[cut:].lstrip()
    messages.append(remainder)
    for section in sections[2:]:
        if discord_length(messages[-1]) + discord_length(section) + 2 <= LIMIT:
            messages[-1] += "\n\n" + section
        else:
            messages.append(section)
    return messages


def freeze_cards(items: list[dict], heading_for, source_url: str, source_label: str, *, fetch=None, target_for=None) -> list[dict]:
    fetch = fetch or get_market_snapshot
    cards = []
    quote_deadline = time.monotonic() + 9.0
    for item in deduplicate_items(items):
        route, title = item.get("route"), item.get("title") or ""
        ticker = ticker_from_title(title, route)
        try:
            snapshot = _bounded_quote(fetch, ticker, route, min(3.0, max(0, quote_deadline - time.monotonic()))) if ticker and time.monotonic() < quote_deadline else None
        except Exception:
            snapshot = None
        cards.append({"destination": target_for(item) if target_for else None, "title": title, "summary": normalize_summary(item["summary"]), "route": route, "ticker": ticker,
                      "market_data_as_of": _field(snapshot, "as_of"),
                      "messages": render_card(heading_for(item), item["summary"], source_url, source_label, route=route, snapshot=snapshot)})
    return cards


def validate_cards(cards) -> list[dict]:
    if type(cards) is not list or not 1 <= len(cards) <= 16:
        raise ValueError("news cards must be a bounded nonempty array")
    for card in cards:
        if type(card) is not dict or set(card) != {"title", "summary", "route", "ticker", "market_data_as_of", "messages", "destination"}:
            raise ValueError("news card has an invalid schema")
        if card["destination"] is not None and (type(card["destination"]) is not str or not card["destination"].isdigit()):
            raise ValueError("news card destination is invalid")
        if any(type(card[k]) is not str for k in ("title", "summary", "route")):
            raise ValueError("news card text is invalid")
        if card["route"] not in {"id_stocks_news", "us_stocks_news", "macro_news", "id_industry_news"}:
            raise ValueError("news card route is invalid")
        if card["ticker"] != ticker_from_title(card["title"], card["route"]):
            raise ValueError("news card ticker conflicts with its headline")
        if card["market_data_as_of"] is not None:
            stamp = datetime.fromisoformat(card["market_data_as_of"])
            if stamp.tzinfo is None:
                raise ValueError("news card market timestamp must be aware")
        messages = card["messages"]
        if type(messages) is not list or not 1 <= len(messages) <= 4 or any(type(m) is not str or not m or discord_length(m) > LIMIT for m in messages):
            raise ValueError("news card messages are invalid")
    return cards
