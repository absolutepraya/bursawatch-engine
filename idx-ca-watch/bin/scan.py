#!/usr/bin/env python3
"""idx-ca-watch scanner. See DESIGN.md."""
from __future__ import annotations
import os, sys, json, time, datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

API_URL = "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
FIN_REPORT_URL = "https://www.idx.co.id/primary/ListedCompany/GetFinancialReport"
IDX_BASE = "https://www.idx.co.id"
ALERT_CHANNEL = "1517510484025151538"      # scored CA alerts (agent reply via cron deliver)
HEARTBEAT_CHANNEL = "1505162000420835388"  # heartbeats / bootstrap / status / errors
SEEN_TTL_DAYS = 45
PAGE_SIZE = 100
MAX_ROWS = 200
LOOKBACK_HOURS = 2
WIB = dt.timezone(dt.timedelta(hours=7))

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_STATE = SKILL_DIR / "state" / "state.json"
CHART_SCRIPT = Path.home() / ".agents" / "skills" / "chart" / "bin" / "chart.sh"


def state_path() -> Path:
    return Path(os.environ.get("IDX_CA_STATE_PATH", str(DEFAULT_STATE)))


@dataclass
class Disclosure:
    id2: str
    no: str
    ts: str               # ISO, WIB
    ticker: str
    title: str
    subject: str
    form_id: str
    is_saham: bool
    pdf_urls: list[str] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)


def normalize_ticker(raw: str | None) -> str:
    return (raw or "").strip().upper()


def parse_announcements(payload: dict) -> list[Disclosure]:
    out: list[Disclosure] = []
    for rep in (payload or {}).get("Replies", []) or []:
        p = rep.get("pengumuman") or {}
        atts = rep.get("attachments") or []
        out.append(Disclosure(
            id2=p.get("Id2") or "",
            no=p.get("NoPengumuman") or "",
            ts=p.get("TglPengumuman") or "",
            ticker=normalize_ticker(p.get("Kode_Emiten")),
            title=p.get("JudulPengumuman") or "",
            subject=p.get("PerihalPengumuman") or "",
            form_id=str(p.get("Form_Id") or ""),
            is_saham=bool(p.get("EfekEmiten_Saham")),
            pdf_urls=[a.get("FullSavePath") for a in atts if a.get("FullSavePath")],
            filenames=[a.get("OriginalFilename") or "" for a in atts],
        ))
    return out


# Order matters: more specific CA types first; "material_fact"/generic last.
INTERESTING_PATTERNS: list[tuple[str, list[str]]] = [
    ("rights_issue", ["pmhmetd", "hmetd", "rights issue", "penambahan modal dengan hak"]),
    ("private_placement", ["pmthmetd", "tanpa hak memesan", "private placement", "penambahan modal tanpa hak"]),
    ("tender_offer", ["penawaran tender", "tender offer", "tender wajib", "tender sukarela"]),
    ("ma", ["akuisisi", "pengambilalihan", "penggabungan usaha", "merger", "peleburan"]),
    ("buyback", ["pembelian kembali", "buyback", "saham treasuri"]),
    ("reverse_split", ["penggabungan saham", "reverse stock split"]),
    ("stock_split", ["pemecahan saham", "stock split"]),
    ("dividend", ["dividen"]),
    ("pledge", ["gadai saham", "repo saham", "jaminan saham"]),
    ("affiliate", ["transaksi afiliasi", "benturan kepentingan"]),
    ("ownership", ["pemegang saham pengendali", "perubahan kepemilikan", "pengambilalihan saham", "kepemilikan saham"]),
    ("contract", ["kontrak baru", "perjanjian penting", "joint venture", "kerja sama strategis", "penandatanganan kontrak"]),
    ("material_fact", ["informasi atau fakta material", "fakta material", "keterbukaan informasi"]),
]
RED_FLAG_PATTERNS: list[tuple[str, list[str]]] = [
    ("uma", ["unusual market activity", "(uma)", " uma"]),
    ("suspend", ["suspensi", "penghentian sementara perdagangan", "suspend"]),
    ("fca_ppk", ["pemantauan khusus", "full call auction", "papan pemantauan"]),
    ("pkpu", ["pkpu", "penundaan kewajiban pembayaran", "pailit", "kepailitan"]),
]
SKIP_PATTERNS = ["laporan keuangan", "financial statement", "public expose", "paparan publik",
                 "laporan tahunan", "annual report", "prospektus ringkas", "jadwal "]


@dataclass
class Classification:
    interesting: bool
    ca_type: str | None
    red_flags: list[str]


def _haystack(d: Disclosure) -> str:
    return " ".join([d.title, d.subject] + d.filenames).lower()


def classify(d: Disclosure) -> Classification:
    h = _haystack(d)
    red_flags = [name for name, pats in RED_FLAG_PATTERNS if any(p in h for p in pats)]
    ca_type = None
    for name, pats in INTERESTING_PATTERNS:
        if any(p in h for p in pats):
            ca_type = name
            break
    # A specific CA type (anything but the generic catch) keeps it even if a skip word co-occurs.
    specific = ca_type is not None and ca_type != "material_fact"
    skipped = any(s in h for s in SKIP_PATTERNS)
    if red_flags:
        return Classification(True, ca_type, red_flags)
    if specific:
        return Classification(True, ca_type, red_flags)
    if ca_type == "material_fact" and not skipped:
        return Classification(True, "material_fact", red_flags)
    return Classification(False, None, red_flags)


def _empty_state() -> dict:
    return {"seen": {}, "last_run": None, "stats": {"runs": 0}}


def load_state() -> dict:
    p = state_path()
    if not p.exists():
        return _empty_state()
    try:
        st = json.loads(p.read_text())
        st.setdefault("seen", {})
        st.setdefault("stats", {"runs": 0})
        return st
    except (json.JSONDecodeError, ValueError):
        ts = dt.datetime.now(WIB).strftime("%Y%m%d_%H%M%S")
        p.rename(p.with_name(f"state.corrupt-{ts}.json"))
        return _empty_state()


def save_state(state: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(p)


def is_bootstrap(state: dict) -> bool:
    return not state.get("seen")


def _parse_ts(ts: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(ts)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=WIB)
    except (ValueError, TypeError):
        return None


def prune_state(state: dict, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(WIB)
    cutoff = now - dt.timedelta(days=SEEN_TTL_DAYS)
    keep = {}
    for k, v in state.get("seen", {}).items():
        t = _parse_ts(v.get("ts", ""))
        if t is None or t >= cutoff:
            keep[k] = v
    state["seen"] = keep
    return state


def mark_seen(state, d: Disclosure, *, interesting: bool, scored: bool = False,
              score=None, ca_type: str | None = None) -> None:
    state.setdefault("seen", {})[d.id2] = {
        "ts": d.ts, "ticker": d.ticker, "type": ca_type, "interesting": interesting,
        "scored": scored, "score": score,
    }


def record_score(id2: str, score, *, ticker: str = "", ts: str = "", ca_type: str | None = None) -> None:
    """Mark a scored item seen with its final score. Called after the alert is posted
    (or after a 🔴/AVOID decision) so the item is not re-escalated next hour."""
    state = load_state()
    state.setdefault("seen", {})[id2] = {
        "ts": ts or dt.datetime.now(WIB).isoformat(), "ticker": ticker, "type": ca_type,
        "interesting": True, "scored": True, "score": score,
    }
    save_state(state)


def select_new(disclosures: list[Disclosure], state: dict) -> list[Disclosure]:
    seen = state.get("seen", {})
    return [d for d in disclosures if d.id2 and d.id2 not in seen]


DISQUALIFY_FLAGS = {"uma", "suspend", "fca_ppk", "pkpu"}


def disqualified(red_flags: list[str]) -> tuple[bool, str | None]:
    for flag in red_flags:
        if flag in DISQUALIFY_FLAGS:
            return True, flag
    return False, None


def format_heartbeat(now: dt.datetime, checked: int, new_count: int,
                     interesting_count: int, degraded: bool = False) -> str:
    segs = ["🫀 idx-ca", f"{now.strftime('%H:%M')} WIB",
            f"{checked} checked", f"{new_count} new", f"{interesting_count} flagged"]
    return " · ".join(segs) + (" ⚠️" if degraded else "")


def _ttm_yoy(values: list) -> float | None:
    """YoY growth: sum of the latest 4 values vs the prior 4 (values newest-first)."""
    nums = [v for v in (values or []) if v is not None]
    if len(nums) < 8:
        return None
    latest = sum(nums[:4])
    prior = sum(nums[4:8])
    if prior == 0:
        return None
    return (latest - prior) / abs(prior)


def health_verdict(h: dict) -> tuple[str, bool]:
    h = h or {}
    if all(h.get(k) is None for k in ("roe", "net_margin", "net_cash", "current_ratio",
                                      "fcf_pos", "ni_ttm", "ni_yoy")):
        return ("n/a", False)
    ni_ttm = h.get("ni_ttm")
    ni_yoy = h.get("ni_yoy")
    cr = h.get("current_ratio")
    distress = (
        (ni_ttm is not None and ni_ttm < 0)
        or (ni_yoy is not None and ni_yoy < -0.5)
        or (cr is not None and cr < 1 and not h.get("net_cash"))
    )
    if distress:
        return ("weak", True)
    score = 0
    if (h.get("roe") or 0) > 0.10:
        score += 1
    if (h.get("net_margin") or 0) > 0.08:
        score += 1
    if h.get("net_cash"):
        score += 1
    if (cr or 0) > 1.5:
        score += 1
    if h.get("fcf_pos"):
        score += 1
    if (ni_yoy if ni_yoy is not None else -1) >= 0:
        score += 1
    if score >= 4:
        return ("healthy", False)
    if score >= 2:
        return ("mixed", False)
    return ("weak", False)


SCORE_COMPONENT_LIMITS = {
    "materiality": 3,
    "fundamental_impact": 3,
    "structure_alignment": 2,
    "execution_certainty": 2,
}
PUBLISH_BLOCKING_FLAGS = {"uma", "suspend", "fca_ppk", "pkpu"}
PUBLISH_REQUIRED_TEXT_FIELDS = ("ticker", "company_name", "ca_label", "summary", "pdf_url")


def publication_score(components: dict[str, int]) -> int:
    if set(components) != set(SCORE_COMPONENT_LIMITS):
        raise ValueError("score components are incomplete")
    for name, maximum in SCORE_COMPONENT_LIMITS.items():
        value = components[name]
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError(f"invalid {name} score")
    return sum(components.values())


def validate_publication_fields(fields: dict) -> None:
    for name in PUBLISH_REQUIRED_TEXT_FIELDS:
        if not isinstance(fields.get(name), str) or not fields[name].strip():
            raise ValueError(f"{name} is required")
    components = fields.get("score_components")
    if not isinstance(components, dict):
        raise ValueError("score components are required")
    total = publication_score(components)
    if fields.get("score") != total:
        raise ValueError("score must equal component total")
    if not 7 <= total <= 10:
        raise ValueError("published score must be 7 to 10")
    if components["materiality"] < 2:
        raise ValueError("materiality must be at least 2")
    if components["fundamental_impact"] < 2:
        raise ValueError("fundamental impact must be at least 2")
    if components["execution_certainty"] < 1:
        raise ValueError("execution certainty must be at least 1")
    if set(fields.get("red_flags") or ()) & PUBLISH_BLOCKING_FLAGS:
        raise ValueError("red flag blocks publication")
    if health_verdict(fields.get("health") or {})[1]:
        raise ValueError("financial distress blocks publication")
    context = fields.get("fundamental_context") or {}
    denominator_keys = ("market_cap", "total_revenue", "total_assets", "shares_outstanding")
    if not any(context.get(key) for key in denominator_keys):
        raise ValueError("materiality denominator is required")


IDX_EMOJI = "<:idx:1531974045266874499>"
ALERT_SEPARATOR = "┈┈┈┈┈┈┈┈┈┈┈┈┈"


def render_alert(fields: dict) -> str:
    return "\n".join([
        f"### {IDX_EMOJI} {fields['ticker']} ({fields['company_name']})",
        fields["summary"].strip(),
        ALERT_SEPARATOR,
        f"*Jenis aksi:* {fields['ca_label']}",
        f"*Skor katalis:* {fields['score']}/10",
        f"*Sumber:* [Keterbukaan Informasi BEI](<{fields['pdf_url']}>)",
    ])


def cli_post_alert(argv: list) -> int:
    if argv and argv[0] == "--json":
        raw = argv[1]
    else:
        raw = sys.stdin.read()
    fields = json.loads(raw)
    validate_publication_fields(fields)
    text = render_alert(fields)
    ok = post_discord(ALERT_CHANNEL, text, media_path=fields.get("chart_path"),
                      dry_run=os.environ.get("IDX_CA_WATCH_NO_POST") == "1")
    print("posted" if ok else "post-failed")
    return 0 if ok else 1


def build_item_payload(d: Disclosure, c: Classification, health: dict,
                       pdf_text: str, fin_report_text: str, chart_path: str | None) -> dict:
    fundamental_context = {
        key: (health or {}).get(key)
        for key in ("market_cap", "total_revenue", "total_assets", "shares_outstanding")
    }
    return {
        "id2": d.id2, "ticker": d.ticker, "title": d.title, "subject": d.subject,
        "ts": d.ts, "ca_type": c.ca_type, "red_flags": c.red_flags,
        "company_name": (health or {}).get("company_name") or d.ticker,
        "fundamental_context": fundamental_context,
        "pdf_url": d.pdf_urls[0] if d.pdf_urls else None,
        "pdf_text": pdf_text[:20000] if pdf_text else "",
        "fin_report_text": fin_report_text[:8000] if fin_report_text else "",
        "health": health, "chart_path": chart_path,
    }


def _ua() -> str:
    return ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


IMPERSONATE_PROFILES = ["chrome124", "safari17_0", "chrome123", "chrome120",
                        "chrome116", "chrome131", "edge101", "safari15_5"]
BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
}


def fetch_page(index_from: int = 1, page_size: int = PAGE_SIZE) -> dict:
    params = (f"?indexFrom={index_from}&pageSize={page_size}&dateFrom=&dateTo="
              f"&lang=id&keyword=&keyOpenInfo=&keynoPengumuman=")
    url = API_URL + params
    # 1) curl_cffi — rotate TLS-impersonation fingerprints. Cloudflare blocks SOME
    # fingerprints (e.g. the floating "chrome" alias) while allowing others, and the
    # blocked set shifts over time, so try several profiles over two passes.
    try:
        from curl_cffi import requests as creq
        for _pass in range(2):
            for imp in IMPERSONATE_PROFILES:
                try:
                    r = creq.get(url, impersonate=imp, headers=BROWSER_HEADERS, timeout=30)
                    if r.status_code == 200 and r.text.lstrip().startswith(("{", "[")):
                        return r.json()
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(2)
    except Exception as e:  # noqa: BLE001
        print(f"[fetch] curl_cffi layer failed: {e}", file=sys.stderr)
    # 2) cloudscraper
    try:
        import cloudscraper
        s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "linux", "mobile": False})
        r = s.get(url, headers=BROWSER_HEADERS, timeout=40)
        if r.status_code == 200 and r.text.lstrip().startswith(("{", "[")):
            return r.json()
    except Exception as e:  # noqa: BLE001
        print(f"[fetch] cloudscraper failed: {e}", file=sys.stderr)
    # 3) headless fallback (only if installed) — best effort
    try:
        return _fetch_headless(url)
    except Exception as e:  # noqa: BLE001
        print(f"[fetch] headless failed: {e}", file=sys.stderr)
    raise RuntimeError("all IDX fetch methods failed (Cloudflare?)")


def _fetch_headless(url: str) -> dict:
    # Requires a system chromium + playwright on the VPS; see DEPLOY.md.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(user_agent=_ua())
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            body = pg.inner_text("pre") if pg.query_selector("pre") else pg.content()
        finally:
            b.close()
    return json.loads(body)


def fetch_recent(state: dict) -> list[Disclosure]:
    seen = state.get("seen", {})
    cutoff = dt.datetime.now(WIB) - dt.timedelta(hours=LOOKBACK_HOURS)
    collected: list[Disclosure] = []
    index_from = 1
    while len(collected) < MAX_ROWS:
        payload = fetch_page(index_from, PAGE_SIZE)
        items = parse_announcements(payload)
        if not items:
            break
        for d in items:
            collected.append(d)
            t = _parse_ts(d.ts)
            if d.id2 in seen or (t is not None and t < cutoff):
                return collected  # reached known/old territory
        index_from += PAGE_SIZE
        if len(items) < PAGE_SIZE:
            break
    return collected


def fetch_pdf_text(url: str, max_pages: int = 8) -> str:
    if not url:
        return ""
    try:
        from curl_cffi import requests as creq
        r = None
        for imp in IMPERSONATE_PROFILES:
            try:
                rr = creq.get(url, impersonate=imp, headers=BROWSER_HEADERS, timeout=40)
                if rr.status_code == 200 and rr.content:
                    r = rr
                    break
            except Exception:  # noqa: BLE001
                continue
        if r is None:
            return ""
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(r.content))
        parts = []
        for page in reader.pages[:max_pages]:
            parts.append(page.extract_text() or "")
        return "\n".join(parts).strip()
    except Exception as e:  # noqa: BLE001
        print(f"[pdf] extract failed for {url}: {e}", file=sys.stderr)
        return ""


def _report_query_order(now: dt.datetime) -> list:
    """(year, periode) pairs to try: this year's periods, then last year's."""
    y = now.year
    cur = [(y, p) for p in ["tw1", "tw2", "tw3", "audit"]]
    prev = [(y - 1, p) for p in ["audit", "tw3", "tw2", "tw1"]]
    return cur + prev


def _pick_report(results: list) -> str | None:
    for res in results or []:
        for att in res.get("Attachments", []) or []:
            name = (att.get("File_Name") or "")
            ftype = (att.get("File_Type") or "").lower()
            if name.lower().startswith("financialstatement") and ftype == ".pdf":
                path = att.get("File_Path") or ""
                if path:
                    return IDX_BASE + path
    return None


def fetch_financial_report_text(ticker: str, now: dt.datetime | None = None,
                                max_pages: int = 6, cap: int = 8000) -> str:
    """Best-effort: latest IDX financial-statement PDF text for the ticker. '' on any failure."""
    now = now or dt.datetime.now(WIB)
    try:
        from curl_cffi import requests as creq
        for year, periode in _report_query_order(now):
            params = (f"?indexFrom=1&pageSize=3&year={year}&reportType=rdf"
                      f"&periode={periode}&kodeEmiten={ticker}&SortColumn=KodeEmiten&SortOrder=asc")
            url = FIN_REPORT_URL + params
            for imp in IMPERSONATE_PROFILES[:3]:
                try:
                    r = creq.get(url, impersonate=imp, headers=BROWSER_HEADERS, timeout=30)
                    if r.status_code == 200 and r.text.lstrip().startswith("{"):
                        pdf_url = _pick_report(r.json().get("Results", []))
                        if pdf_url:
                            return fetch_pdf_text(pdf_url, max_pages=max_pages)[:cap]
                        break  # endpoint answered, no report for this period -> try next period
                except Exception:  # noqa: BLE001
                    continue
        return ""
    except Exception as e:  # noqa: BLE001
        print(f"[finreport] {ticker} failed: {e}", file=sys.stderr)
        return ""


def _assemble_pdf_text(chunks: list, cap: int) -> str:
    """chunks: list of (filename, text). Prepend [filename], drop empties, cap total."""
    blocks = [f"[{name}]\n{text}" for name, text in chunks if (text or "").strip()]
    joined = "\n\n".join(blocks)
    return joined[:cap]


def fetch_attachments_text(urls: list, filenames: list,
                           max_pages_each: int = 10, cap: int = 20000) -> str:
    """Extract text from ALL CA attachments (not just the cover), labelled by filename."""
    urls = urls or []
    filenames = filenames or []
    chunks = []
    for i, u in enumerate(urls):
        if not u:
            continue
        name = filenames[i] if i < len(filenames) and filenames[i] else f"attachment-{i+1}.pdf"
        chunks.append((name, fetch_pdf_text(u, max_pages=max_pages_each)))
    return _assemble_pdf_text(chunks, cap)


def financial_health(ticker: str) -> dict:
    """Compact fundamental snapshot from yfinance. Best-effort; {} on failure."""
    out = {"company_name": None, "market_cap": None, "total_revenue": None,
           "total_assets": None, "shares_outstanding": None,
           "roe": None, "net_margin": None, "net_cash": None, "current_ratio": None,
           "fcf_pos": None, "ni_ttm": None, "ni_yoy": None, "rev_yoy": None}
    try:
        import yfinance as yf
        t = yf.Ticker(f"{ticker}.JK")
        try:
            info = t.info or {}
        except Exception:  # noqa: BLE001
            info = {}
        out["company_name"] = info.get("longName") or info.get("shortName")
        out["market_cap"] = info.get("marketCap")
        out["total_revenue"] = info.get("totalRevenue")
        out["total_assets"] = info.get("totalAssets")
        out["shares_outstanding"] = info.get("sharesOutstanding")
        out["roe"] = info.get("returnOnEquity")
        out["net_margin"] = info.get("profitMargins")
        out["current_ratio"] = info.get("currentRatio")
        out["rev_yoy"] = info.get("revenueGrowth")
        out["ni_yoy"] = info.get("earningsGrowth")
        out["ni_ttm"] = info.get("netIncomeToCommon")
        fcf = info.get("freeCashflow")
        out["fcf_pos"] = (fcf is not None and fcf > 0) or None
        cash, debt = info.get("totalCash"), info.get("totalDebt")
        if cash is not None and debt is not None:
            out["net_cash"] = cash > debt
        # Fallback NI YoY from quarterly statements if info lacked earningsGrowth.
        if out["ni_yoy"] is None:
            try:
                qf = t.quarterly_financials
                if qf is not None and "Net Income" in qf.index:
                    out["ni_yoy"] = _ttm_yoy([float(v) for v in qf.loc["Net Income"].values])
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[health] {ticker} failed: {e}", file=sys.stderr)
        return {}


import subprocess  # noqa: E402


def render_chart(ticker: str) -> str | None:
    if not CHART_SCRIPT.exists():
        print(f"[chart] script missing: {CHART_SCRIPT}", file=sys.stderr)
        return None
    try:
        proc = subprocess.run(
            [str(CHART_SCRIPT), f"IDX:{ticker}", "1D", "6M", "Volume,RSI,EMA"],
            capture_output=True, text=True, timeout=60)
        path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        if proc.returncode == 0 and path and Path(path).exists():
            return path
        print(f"[chart] failed rc={proc.returncode}: {proc.stderr[:200]}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[chart] error: {e}", file=sys.stderr)
    return None


def _discord_token() -> str | None:
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if tok:
        return tok
    env = Path.home() / ".hermes" / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


def post_discord(channel: str, content: str, media_path: str | None = None,
                 dry_run: bool = False) -> bool:
    if dry_run or os.environ.get("IDX_CA_WATCH_NO_POST") == "1":
        print(f"[dry-run] would post to {channel}: {content}"
              + (f"  +MEDIA {media_path}" if media_path else ""))
        return True
    import requests
    tok = _discord_token()
    if not tok:
        print("[discord] DISCORD_BOT_TOKEN missing", file=sys.stderr)
        return False
    url = f"https://discord.com/api/v10/channels/{channel}/messages"
    headers = {"Authorization": f"Bot {tok}"}
    for attempt in range(4):
        try:
            if media_path and Path(media_path).exists():
                with open(media_path, "rb") as fh:
                    r = requests.post(url, headers=headers,
                                      data={"content": content},
                                      files={"file": fh}, timeout=30)
            else:
                r = requests.post(url, headers={**headers, "Content-Type": "application/json"},
                                  json={"content": content}, timeout=30)
            if r.status_code in (200, 201):
                return True
            if r.status_code == 429:
                retry = float(r.json().get("retry_after", 2))
                time.sleep(min(retry, 10))
                continue
            print(f"[discord] HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
            return False
        except Exception as e:  # noqa: BLE001
            print(f"[discord] attempt {attempt} error: {e}", file=sys.stderr)
            time.sleep(2)
    return False


def run(now: dt.datetime | None = None, *, dry_run: bool = False) -> dict:
    if os.environ.get("IDX_CA_WATCH_BOOTSTRAP_RESET") == "1":
        state_path().unlink(missing_ok=True)
    now = now or dt.datetime.now(WIB)
    state = prune_state(load_state(), now=now)
    bootstrap = is_bootstrap(state)
    state["stats"]["runs"] = state.get("stats", {}).get("runs", 0) + 1

    disclosures = fetch_recent(state)
    new = select_new(disclosures, state)

    classed = [(d, classify(d)) for d in new]
    interesting = [(d, c) for d, c in classed if c.interesting]

    if bootstrap:
        for d, c in classed:
            mark_seen(state, d, interesting=c.interesting, ca_type=c.ca_type)
        state["last_run"] = now.isoformat()
        save_state(state)
        post_discord(HEARTBEAT_CHANNEL,
                     f"🫀 idx-ca · {now.strftime('%H:%M')} WIB · bootstrapped — watching from now "
                     f"({now.strftime('%Y-%m-%d %H:%M')} WIB), {len(classed)} recent filings marked seen.",
                     dry_run=dry_run)
        return {"wakeAgent": False, "items": [], "heartbeat": "bootstrap"}

    # mark all NON-interesting new items seen immediately
    for d, c in classed:
        if not c.interesting:
            mark_seen(state, d, interesting=False, ca_type=c.ca_type)

    # Technical data is not part of candidate selection or scoring. Hard red flags
    # are suppressed deterministically, while corporate-action and fundamental
    # materiality are assessed by the scoring contract.
    items_payload: list[dict] = []
    for d, c in interesting:
        bad, why = disqualified(c.red_flags)
        if bad:
            mark_seen(state, d, interesting=True, scored=True, score=0, ca_type=c.ca_type)
            print(f"[skip] {d.ticker} disqualified: {why}", file=sys.stderr)
            continue
        health = financial_health(d.ticker)
        pdf_text = fetch_attachments_text(d.pdf_urls, d.filenames)
        fin_text = fetch_financial_report_text(d.ticker)
        chart = render_chart(d.ticker)
        items_payload.append(build_item_payload(d, c, health, pdf_text, fin_text, chart))

    # heartbeat counts (scoring of items happens in the agent turn; counts here are pre-score)
    hb = format_heartbeat(now, checked=len(disclosures), new_count=len(new),
                          interesting_count=len(items_payload))
    state["last_run"] = now.isoformat()

    if not items_payload:
        save_state(state)
        post_discord(HEARTBEAT_CHANNEL, hb, dry_run=dry_run)
        return {"wakeAgent": False, "items": [], "heartbeat": hb}

    # At-least-once delivery: do NOT mark to-be-scored items seen here. They are marked
    # seen only when record_score() is called after the alert is posted (by the agent in
    # Approach A, or by scan.py itself in Approach B). If the scoring turn never fires or
    # fails mid-way, the item re-escalates next hour instead of being silently dropped.
    save_state(state)
    post_discord(HEARTBEAT_CHANNEL, hb, dry_run=dry_run)  # heartbeat always lands
    return {"wakeAgent": True, "items": items_payload, "heartbeat": hb}


def main() -> int:
    dry = os.environ.get("IDX_CA_WATCH_NO_POST") == "1"
    try:
        result = run(dry_run=dry)
    except Exception as e:  # noqa: BLE001
        print(f"[fatal] {e}", file=sys.stderr)
        post_discord(HEARTBEAT_CHANNEL,
                     f"❌ idx-ca · {dt.datetime.now(WIB).strftime('%H:%M')} WIB · failed: {e}",
                     dry_run=dry)
        print(json.dumps({"wakeAgent": False, "error": str(e)}))
        # exit 0: error already reported to HEARTBEAT_CHANNEL (+ watchdog covers sustained
        # failure). A non-zero exit would make the scheduler wake the agent to "report the
        # error", delivering it to the ALERT channel — which we don't want.
        return 0
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "post-alert":
        raise SystemExit(cli_post_alert(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "record-score":
        import argparse
        ap = argparse.ArgumentParser(prog="scan.py record-score")
        ap.add_argument("id2")
        ap.add_argument("score", type=int)
        ap.add_argument("--ticker", default="")
        ap.add_argument("--ts", default="")
        ap.add_argument("--type", dest="ca_type", default=None)
        a = ap.parse_args(sys.argv[2:])
        record_score(a.id2, a.score, ticker=a.ticker, ts=a.ts, ca_type=a.ca_type)
        print(f"recorded {a.id2} = {a.score}")
        raise SystemExit(0)
    raise SystemExit(main())
