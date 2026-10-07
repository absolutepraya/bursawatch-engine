"""Shared news writing, deterministic quotes and immutable Discord cards.

Source owners retain relevance, routing, leases, receipts and retry state.
This module never submits messages or decides whether a source is news.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import math
import re
import sys
import threading
import time

VERSION = "stock-news-v1"
LIMIT = 2000
MARKER = "*(Ringkasan)* "
GREEN = "<:green:1531274822221434911>"
RED = "<:red:1531274756853202974>"
GREY = "<:grey:1531279158913536182>"
UP = "<:up:1531285100346740766>"
DOWN = "<:down:1531285063986053200>"
HOLD = "<:hold:1531284248235868333>"
from writing_contract import COMMON_WRITING_INSTRUCTION, PresentationCategory, category_instruction

WRITING_INSTRUCTION = COMMON_WRITING_INSTRUCTION + (
    "For issuer news, start the headline with the exact exchange TICKER followed by a colon. "
    "For macro or industry news, use a natural headline. Return plain summary text without a Ringkasan label; "
    "the renderer adds it once. Do not generate the latest quote or 1D/1W/1M/3M tracker in the summary. "
) + category_instruction("macro") + category_instruction("industry")
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


def normalize_headline(title: str, route: str | None = None) -> str:
    """Capitalize the subject without changing names or rejecting unusual prose."""
    ticker = ticker_from_title(title, route)
    start = len(ticker) + 1 if ticker else 0
    for index in range(start, len(title)):
        character = title[index]
        if character.lower() != character.upper():
            upper = character.upper()
            # Expanding a Unicode character must not consume more transport space.
            return title[:index] + upper + title[index + 1:] if len(upper) == 1 else title
    return title


def _normalize_heading(heading: str, route: str | None) -> str:
    first, separator, rest = heading.partition("\n")
    match = re.match(r"^###\s+(?:<a?:[^:>]+:\d+>\s+)?", first)
    if match is None:
        return heading
    return first[:match.end()] + normalize_headline(first[match.end():], route) + separator + rest


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


def _bounded_quote(fetch, ticker, route, timeout, slots=None):
    slots = slots or _QUOTE_SLOTS
    if not slots.acquire(blocking=False):
        return None
    complete = threading.Event()
    result = []

    def run():
        try:
            result.append(fetch(ticker, route))
        except Exception:
            result.append(None)
        finally:
            slots.release()
            complete.set()

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        slots.release()
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


_CONTEXT_SLOTS = threading.BoundedSemaphore(4)
_CONTEXT_CACHE: dict = {}
_CONTEXT_LOCK = threading.Lock()
SECTORS_STORE_PATH = Path.home() / ".hermes" / "state" / "sectors-client.sqlite3"
SECTORS_KEY_FILE = Path.home() / ".hermes" / "bursawatch-sectors.env"
SECTORS_CALLER = "news-context"
SECTORS_REPORT_COST = 2
_RATING_LEVELS = (("strong_buy", "Strong Buy", UP), ("buy", "Buy", UP), ("hold", "Hold", HOLD),
                  ("sell", "Sell", DOWN), ("strong_sell", "Strong Sell", DOWN))
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_NON_TERMINAL = {"tbk", "pt", "inc", "ltd", "co", "corp", "persero", "no", "st"}
MAX_ABOUT_SENTENCE = 300


def _sectors_library():
    """Locate lib-sectors beside this checkout or in the installed runtime. Absent means no Sectors lines."""
    here = Path(__file__).resolve()
    for base in (here.parents[2] / "lib-sectors", Path.home() / ".agents" / "skills" / "lib-sectors"):
        if (base / "bin" / "sectors_client").is_dir():
            if str(base / "bin") not in sys.path:
                sys.path.append(str(base / "bin"))
            return base
    return None


def _sectors_client(now: datetime):
    base = _sectors_library()
    key_file = next((path for path in (SECTORS_KEY_FILE, base / ".env" if base else None) if path is not None and path.is_file()), None)
    if base is None or key_file is None:
        return None
    from sectors_client import Config, SectorsClient
    window = now.astimezone(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m")
    config = Config.from_env_file(key_file, store_path=SECTORS_STORE_PATH, caller=SECTORS_CALLER,
                                  billing_window=window, cache_only=False, timeout_seconds=3, wait_seconds=1)
    return SectorsClient(config)


def _fetch_sectors(ticker: str, route: str) -> dict | None:
    """Optional Sectors analyst consensus and overview through the shared coordinated client.

    One report identity per ticker and ISO week gives the seven-day cache: the shared store
    never refetches an identity, and a new week is a new caller-owned generation.
    """
    now = datetime.now(timezone.utc)
    client = _sectors_client(now)
    if client is None:
        return None
    from sectors_client import RequestIdentity
    week = now.astimezone(ZoneInfo("Asia/Jakarta")).isocalendar()
    identity = RequestIdentity(f"/v2/company/report/{ticker}/", {"sections": "overview,future"},
                               generation=f"news-context:{week[0]}-W{week[1]:02d}")
    # The cutoff is "visible now": a response fetched during this call must be readable by it.
    report = client.get(identity, cutoff=now + timedelta(minutes=1), max_cost=SECTORS_REPORT_COST).payload
    overview = report.get("overview") if isinstance(report, Mapping) else None
    future = report.get("future") if isinstance(report, Mapping) else None
    rating = future.get("analyst_rating_breakdown") if isinstance(future, Mapping) else None
    return {"overview": overview if isinstance(overview, Mapping) else None,
            "rating": rating if isinstance(rating, Mapping) else None}


def _fetch_business_summary(ticker: str, route: str) -> str | None:
    import yfinance as yf
    summary = yf.Ticker(f"{ticker}.JK").info.get("longBusinessSummary")
    return summary if isinstance(summary, str) else None


def _cache_day() -> str:
    return datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()


def get_company_context(ticker: str, route: str = "id_stocks_news") -> dict | None:
    """Bounded optional analyst and company context for IDX issuers, cached per ticker and WIB day."""
    if route != "id_stocks_news" or not re.fullmatch(r"[A-Z]{4}", ticker or ""):
        return None
    cache_key = (ticker, _cache_day())
    with _CONTEXT_LOCK:
        if cache_key in _CONTEXT_CACHE:
            return _CONTEXT_CACHE[cache_key]
    sectors = _bounded_quote(_fetch_sectors, ticker, route, 3.0, _CONTEXT_SLOTS) or {}
    summary = _bounded_quote(_fetch_business_summary, ticker, route, 3.0, _CONTEXT_SLOTS)
    result = {"overview": sectors.get("overview"), "rating": sectors.get("rating"), "business_summary": summary}
    if not any(result.values()):
        return None
    with _CONTEXT_LOCK:
        if len(_CONTEXT_CACHE) > 512:
            _CONTEXT_CACHE.clear()
        _CONTEXT_CACHE[cache_key] = result
    return result


def _first_sentence(text) -> str | None:
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    for match in re.finditer(r"[.!?](?=\s+[A-Z\"'(])", text):
        previous = text[:match.start()].rsplit(" ", 1)[-1].lower().rstrip(".")
        if previous in _NON_TERMINAL:
            continue
        text = text[:match.end()]
        break
    if not text:
        return None
    if len(text) > MAX_ABOUT_SENTENCE:
        text = text[:MAX_ABOUT_SENTENCE - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def _format_market_cap(value) -> str | None:
    value = _number(value)
    if value is None or value <= 0:
        return None
    unit, scale = ("T", 1e12) if value >= 1e12 else ("M", 1e9)
    return "Rp" + f"{value / scale:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".") + f" {unit}"


def analyst_block(rating) -> str | None:
    if not isinstance(rating, Mapping):
        return None
    counts = [_number(rating.get(key)) for key, _, _ in _RATING_LEVELS]
    if any(count is None or count < 0 for count in counts):
        return None
    counts = [int(count) for count in counts]
    total = sum(counts)
    if total <= 0:
        return None
    top = max(range(len(counts)), key=lambda index: (counts[index], -index))
    _, label, emoji = _RATING_LEVELS[top]
    breakdown = ", ".join(f"{name} {count}" for (_, name, _), count in zip(_RATING_LEVELS, counts))
    try:
        updated = datetime.strptime(str(rating.get("updated_on"))[:10], "%Y-%m-%d")
        breakdown += f" (per {updated.day:02d} {_MONTHS[updated.month - 1]} {updated.year})"
    except ValueError:
        pass
    return (f"Konsensus analis: {emoji} **{label.upper()}** ({total} analis, {round(counts[top] * 100 / total)}% {label})\n"
            + breakdown)


def about_block(ticker: str, context) -> str | None:
    if not isinstance(context, Mapping):
        return None
    overview = context.get("overview") if isinstance(context.get("overview"), Mapping) else {}
    parts = []
    sentence = _first_sentence(context.get("business_summary"))
    if sentence:
        parts.append(sentence)
    sector, sub_industry = overview.get("sector"), overview.get("sub_industry")
    classification = None
    if isinstance(sector, str) and sector.strip():
        classification = f"Sektor {sector.strip()}"
        if isinstance(sub_industry, str) and sub_industry.strip():
            classification += f" ({sub_industry.strip()})"
    capitalization = _format_market_cap(overview.get("market_cap"))
    facts = ", ".join(part for part in (classification, f"kapitalisasi pasar {capitalization}" if capitalization else None) if part)
    if facts:
        parts.append(facts[0].upper() + facts[1:] + ".")
    return f"Tentang {ticker}:\n" + " ".join(parts) if parts else None


def company_context_block(ticker, context) -> str | None:
    if not ticker or not isinstance(context, Mapping):
        return None
    blocks = [analyst_block(context.get("rating")), about_block(ticker, context)]
    return "\n\n".join(block for block in blocks if block) or None


def discord_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _fit_index(value: str, limit: int) -> int:
    units = 0
    for index, character in enumerate(value):
        units += 2 if ord(character) > 0xFFFF else 1
        if units > limit:
            return index
    return len(value)


def render_card(heading: str, summary: str, source_url: str, source_label: str, *, route=None, snapshot=None, ticker=None, context=None) -> list[str]:
    heading = _normalize_heading(heading, route)
    body = normalize_summary(summary, marked=True)
    sections = [heading, body]
    if route in {"id_stocks_news", "us_stocks_news"}:
        sections.append(market_block(snapshot, "USD" if route == "us_stocks_news" else "IDR"))
    if route == "id_stocks_news":
        extra = company_context_block(ticker, context)
        if extra:
            sections.append(extra)
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


def freeze_cards(items: list[dict], heading_for, source_url: str, source_label: str, *, fetch=None, target_for=None, context_fetch=None) -> list[dict]:
    # Injected quote fetchers keep their exact legacy output unless a context fetcher is also injected.
    context_fetch = context_fetch if context_fetch is not None else (get_company_context if fetch is None else None)
    fetch = fetch or get_market_snapshot
    cards = []
    quote_deadline = time.monotonic() + 9.0
    context_deadline = time.monotonic() + 9.0
    for item in deduplicate_items(items):
        route, title = item.get("route"), item.get("title") or ""
        title = normalize_headline(title, route)
        item = {**item, "title": title}
        ticker = ticker_from_title(title, route)
        try:
            snapshot = _bounded_quote(fetch, ticker, route, min(3.0, max(0, quote_deadline - time.monotonic()))) if ticker and time.monotonic() < quote_deadline else None
        except Exception:
            snapshot = None
        context = None
        if context_fetch and ticker and route == "id_stocks_news" and time.monotonic() < context_deadline:
            try:
                context = context_fetch(ticker, route)
            except Exception:
                context = None
        cards.append({"destination": target_for(item) if target_for else None, "title": title, "summary": normalize_summary(item["summary"]), "route": route, "ticker": ticker,
                      "market_data_as_of": _field(snapshot, "as_of"),
                      "messages": render_card(heading_for(item), item["summary"], source_url, source_label, route=route, snapshot=snapshot, ticker=ticker, context=context)})
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
