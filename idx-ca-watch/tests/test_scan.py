import json
from pathlib import Path
import pytest

import scan


def _payload():
    p = Path(__file__).parent / "fixtures" / "sample_announcement.json"
    return json.loads(p.read_text())


def _mk(title="", subject="", filename="", form_id="0", ticker="ABCD"):
    return scan.Disclosure(id2="x", no="x", ts="2026-06-19T10:00:00",
                           ticker=ticker, title=title, subject=subject, form_id=form_id,
                           is_saham=True, pdf_urls=[], filenames=[filename])


# --- Task 1: normalize_ticker ---
def test_normalize_ticker_strips_padding_and_uppercases():
    assert scan.normalize_ticker("GTBO                 ") == "GTBO"
    assert scan.normalize_ticker(" bren ") == "BREN"
    assert scan.normalize_ticker(None) == ""


# --- Task 2: parse_announcements ---
def test_parse_announcements_extracts_fields():
    items = scan.parse_announcements(_payload())
    assert len(items) == 2
    d = items[0]
    assert d.id2 == "20260619190138-017PenyampaianTanggapanSDA_id-id"
    assert d.ticker == "GTBO"
    assert d.is_saham is True
    assert d.pdf_urls == ["https://www.idx.co.id/StaticData/.../a.pdf"]
    assert "Fakta Material" in d.filenames[0]
    assert items[1].ticker == "BREN"


# --- Task 3: classify ---
def test_classify_rights_issue_interesting():
    c = scan.classify(_mk(title="Keterbukaan Informasi Penambahan Modal Dengan HMETD"))
    assert c.interesting and c.ca_type == "rights_issue"


def test_classify_material_fact_interesting():
    c = scan.classify(_mk(filename="..._Laporan Informasi dan Fakta Material_...pdf"))
    assert c.interesting and c.ca_type == "material_fact"


def test_classify_financial_report_skipped():
    c = scan.classify(_mk(title="Laporan Keuangan Interim 31 Maret 2026"))
    assert not c.interesting


def test_classify_uma_is_red_flag_and_interesting():
    c = scan.classify(_mk(title="Pengumuman Unusual Market Activity (UMA)"))
    assert "uma" in c.red_flags and c.interesting


def test_classify_specific_ca_overrides_skip():
    c = scan.classify(_mk(title="Pembelian Kembali Saham (Buyback) dan Laporan Tahunan"))
    assert c.interesting and c.ca_type == "buyback"


# --- Task 4: state ---
def test_bootstrap_when_seen_empty(tmp_state):
    st = scan.load_state()
    assert scan.is_bootstrap(st) is True


def test_mark_seen_and_roundtrip(tmp_state):
    st = scan.load_state()
    d = _mk(ticker="BREN")
    d.id2 = "id-1"
    scan.mark_seen(st, d, interesting=True, scored=True, score=7, ca_type="rights_issue")
    scan.save_state(st)
    st2 = scan.load_state()
    assert st2["seen"]["id-1"]["ticker"] == "BREN"
    assert st2["seen"]["id-1"]["score"] == 7
    assert st2["seen"]["id-1"]["type"] == "rights_issue"
    assert scan.is_bootstrap(st2) is False


def test_prune_drops_old(tmp_state):
    st = {"seen": {
        "old": {"ts": "2020-01-01T00:00:00", "ticker": "X", "interesting": False, "scored": False, "score": None},
        "new": {"ts": "2026-06-19T00:00:00", "ticker": "Y", "interesting": False, "scored": False, "score": None},
    }}
    now = scan.dt.datetime(2026, 6, 19, tzinfo=scan.WIB)
    pruned = scan.prune_state(st, now=now)
    assert "old" not in pruned["seen"] and "new" in pruned["seen"]


def test_corrupt_state_backs_up_not_wipes(tmp_state):
    tmp_state.write_text("{ this is not json ")
    st = scan.load_state()
    assert st["seen"] == {}
    backups = list(tmp_state.parent.glob("state.corrupt-*.json"))
    assert len(backups) == 1


# --- Task 5: select_new ---
def test_select_new_filters_seen():
    a = _mk(ticker="A")
    a.id2 = "a"
    b = _mk(ticker="B")
    b.id2 = "b"
    state = {"seen": {"a": {"ts": "2026-06-19T00:00:00"}}}
    new = scan.select_new([a, b], state)
    assert [d.id2 for d in new] == ["b"]


# --- Task 6: hard red flags ---
def test_disqualified_rejects_uma_without_market_metrics():
    assert scan.disqualified(["uma"]) == (True, "uma")


def test_disqualified_allows_no_red_flags_without_market_metrics():
    assert scan.disqualified([]) == (False, None)


# --- Task 7: formatting ---
def test_format_heartbeat():
    now = scan.dt.datetime(2026, 6, 19, 14, 0, tzinfo=scan.WIB)
    s = scan.format_heartbeat(now, checked=87, new_count=5, interesting_count=1)
    assert s == "🫀 idx-ca · 14:00 WIB · 87 checked · 5 new · 1 flagged"
    assert "🟢" not in s and "interesting" not in s
    assert scan.format_heartbeat(now, checked=87, new_count=5,
                                 interesting_count=1, degraded=True).endswith(" ⚠️")


def test_build_item_payload_shape():
    d = _mk(title="HMETD", ticker="BREN")
    d.id2 = "bren-1"
    d.pdf_urls = ["http://x/b.pdf"]
    c = scan.Classification(True, "rights_issue", [])
    health = {"company_name": "PT Baren Energi Tbk", "market_cap": 2e12,
              "total_revenue": 1e12, "total_assets": 3e12,
              "shares_outstanding": 1e9, "roe": 0.2, "net_cash": True}
    pl = scan.build_item_payload(d, c, health, pdf_text="ringkasan...",
                                 fin_report_text="laba bersih naik", chart_path="/tmp/c.png")
    assert pl["ticker"] == "BREN" and pl["ca_type"] == "rights_issue"
    assert pl["health"] == health and "laba bersih" in pl["fin_report_text"]
    assert pl["chart_path"] == "/tmp/c.png" and "ringkasan" in pl["pdf_text"]
    assert pl["company_name"] == "PT Baren Energi Tbk"
    assert pl["fundamental_context"]["market_cap"] == 2e12
    assert "metrics" not in pl


# --- Task 13: run() orchestration ---
def test_run_empty_hour_no_wake(tmp_state, monkeypatch):
    # seed one entry so run() takes the heartbeat path, not bootstrap
    seed = scan.load_state()
    seed["seen"]["sentinel"] = {"ts": "2026-06-19T00:00:00"}
    scan.save_state(seed)
    d = _mk(title="Laporan Keuangan Q1")
    d.id2 = "lk-1"
    monkeypatch.setattr(scan, "fetch_recent", lambda state: [d])
    posted = {}
    monkeypatch.setattr(scan, "post_discord",
                        lambda ch, content, media_path=None, dry_run=False: posted.update(c=content) or True)
    now = scan.dt.datetime(2026, 6, 19, 14, 0, tzinfo=scan.WIB)
    res = scan.run(now=now)
    assert res["wakeAgent"] is False
    assert "flagged" in posted["c"] and posted["c"].startswith("🫀 idx-ca · ")
    assert scan.load_state()["seen"]["lk-1"]["interesting"] is False


def test_run_bootstrap_marks_without_alert(tmp_state, monkeypatch):
    d = _mk(title="Rights Issue HMETD")
    d.id2 = "ri-1"
    monkeypatch.setattr(scan, "fetch_recent", lambda state: [d])
    monkeypatch.setattr(scan, "post_discord", lambda *a, **k: True)
    res = scan.run()
    assert res["wakeAgent"] is False
    assert scan.load_state()["seen"]["ri-1"]["scored"] is False


def test_run_payload_has_no_technical_metrics(tmp_state, monkeypatch):
    seed = scan.load_state()
    seed["seen"]["old"] = {"ts": "2026-06-19T00:00:00"}
    scan.save_state(seed)
    d = _mk(title="Keterbukaan Informasi Rights Issue HMETD", ticker="BREN")
    d.id2 = "ri-2"
    d.pdf_urls = ["http://x/p.pdf"]
    monkeypatch.setattr(scan, "fetch_recent", lambda state: [d])
    monkeypatch.setattr(scan, "market_metrics",
                        lambda t: (_ for _ in ()).throw(AssertionError("technical fetch is forbidden")),
                        raising=False)
    monkeypatch.setattr(scan, "fetch_attachments_text", lambda urls, filenames, **k: "ringkasan rights issue untuk ekspansi")
    monkeypatch.setattr(scan, "financial_health", lambda t: {
        "company_name": "PT Baren Energi Tbk", "market_cap": 2e12,
        "total_revenue": 1e12, "total_assets": 3e12, "shares_outstanding": 1e9,
        "roe": 0.2, "net_cash": True, "ni_ttm": 1e9,
    })
    monkeypatch.setattr(scan, "fetch_financial_report_text", lambda t, **k: "laporan keuangan sehat")
    monkeypatch.setattr(scan, "render_chart", lambda t: "/tmp/x.png")
    monkeypatch.setattr(scan, "post_discord", lambda *a, **k: True)
    now = scan.dt.datetime(2026, 6, 19, 14, 0, tzinfo=scan.WIB)
    res = scan.run(now=now)
    assert res["wakeAgent"] is True
    assert len(res["items"]) == 1 and res["items"][0]["ticker"] == "BREN"
    assert res["items"][0]["company_name"] == "PT Baren Energi Tbk"
    assert res["items"][0]["chart_path"] == "/tmp/x.png"
    assert "metrics" not in res["items"][0]
    # at-least-once: NOT marked seen until record_score
    assert "ri-2" not in scan.load_state()["seen"]


# --- final fix pass: at-least-once delivery + record_score ---
def test_record_score(tmp_state):
    scan.record_score("id-x", 7, ticker="BREN", ca_type="rights_issue")
    seen = scan.load_state()["seen"]
    assert seen["id-x"]["score"] == 7
    assert seen["id-x"]["ticker"] == "BREN"
    assert seen["id-x"]["scored"] is True
    assert seen["id-x"]["type"] == "rights_issue"


def test_findings_reescalate_until_recorded(tmp_state, monkeypatch):
    seed = scan.load_state()
    seed["seen"]["old"] = {"ts": "2026-06-19T00:00:00"}
    scan.save_state(seed)
    d = _mk(title="Keterbukaan Informasi Rights Issue HMETD", ticker="BREN")
    d.id2 = "ri-3"
    d.pdf_urls = ["http://x/p.pdf"]
    monkeypatch.setattr(scan, "fetch_recent", lambda state: [d])
    monkeypatch.setattr(scan, "market_metrics",
                        lambda t: (_ for _ in ()).throw(AssertionError("technical fetch is forbidden")),
                        raising=False)
    monkeypatch.setattr(scan, "fetch_attachments_text", lambda urls, filenames, **k: "ringkasan")
    monkeypatch.setattr(scan, "financial_health", lambda t: {
        "company_name": "PT Baren Energi Tbk", "market_cap": 2e12,
        "total_revenue": 1e12, "total_assets": 3e12, "shares_outstanding": 1e9,
        "roe": 0.2, "net_cash": True, "ni_ttm": 1e9,
    })
    monkeypatch.setattr(scan, "fetch_financial_report_text", lambda t, **k: "laporan keuangan")
    monkeypatch.setattr(scan, "render_chart", lambda t: "/tmp/x.png")
    monkeypatch.setattr(scan, "post_discord", lambda *a, **k: True)
    now = scan.dt.datetime(2026, 6, 19, 14, 0, tzinfo=scan.WIB)
    r1 = scan.run(now=now)
    assert r1["wakeAgent"] is True and r1["items"][0]["id2"] == "ri-3"
    r2 = scan.run(now=now)  # still unrecorded -> re-escalates
    assert r2["wakeAgent"] is True and r2["items"][0]["id2"] == "ri-3"
    scan.record_score("ri-3", 6, ticker="BREN")
    r3 = scan.run(now=now)  # now recorded -> filtered out
    assert all(it["id2"] != "ri-3" for it in r3["items"])


def test_health_verdict_healthy():
    h = {"roe": 0.14, "net_margin": 0.21, "net_cash": True, "current_ratio": 2.5,
         "fcf_pos": True, "ni_ttm": 1e12, "ni_yoy": 0.05}
    assert scan.health_verdict(h) == ("healthy", False)


def test_health_verdict_distress_on_loss():
    assert scan.health_verdict({"ni_ttm": -5e11}) == ("weak", True)


def test_health_verdict_distress_on_ni_collapse():
    assert scan.health_verdict({"ni_ttm": 1e9, "ni_yoy": -0.7}) == ("weak", True)


def test_health_verdict_na_when_empty():
    assert scan.health_verdict({}) == ("n/a", False)


def test_ttm_yoy():
    # latest 4 sum = 10+11+12+13=46 ; prior 4 = 8+9+9+10=36 ; (46-36)/36
    vals = [13, 12, 11, 10, 10, 9, 9, 8]
    assert round(scan._ttm_yoy(vals), 4) == round((46 - 36) / 36, 4)
    assert scan._ttm_yoy([1, 2, 3]) is None


# --- Notif upgrade Task 2: render_alert + post-alert ---
def _high_conviction_fields():
    return {
        "ticker": "ANTM",
        "company_name": "PT Aneka Tambang Tbk",
        "ca_label": "Pembelian saham oleh pengendali",
        "summary": (
            "Pengendali membeli saham dalam nilai yang material. "
            "Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali."
        ),
        "score_components": {
            "materiality": 2,
            "fundamental_impact": 2,
            "structure_alignment": 2,
            "execution_certainty": 1,
        },
        "score": 7,
        "red_flags": [],
        "health": {"ni_ttm": 1_000_000_000, "current_ratio": 2.0, "net_cash": True},
        "fundamental_context": {
            "market_cap": 2_000_000_000_000,
            "total_revenue": 1_000_000_000_000,
            "total_assets": 3_000_000_000_000,
            "shares_outstanding": 1_000_000_000,
        },
        "pdf_url": "https://www.idx.co.id/StaticData/x/y.pdf",
        "chart_path": "/tmp/c.png",
    }


def test_validate_publication_fields_accepts_exact_score_seven():
    scan.validate_publication_fields(_high_conviction_fields())


def test_validate_publication_fields_rejects_score_six_even_when_components_match():
    fields = _high_conviction_fields()
    fields["score_components"] = {
        "materiality": 1,
        "fundamental_impact": 2,
        "structure_alignment": 2,
        "execution_certainty": 1,
    }
    fields["score"] = 6
    with pytest.raises(ValueError, match="published score"):
        scan.validate_publication_fields(fields)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"score": 6}, "must equal component total"),
        ({"score_components": {"materiality": 1, "fundamental_impact": 3, "structure_alignment": 2, "execution_certainty": 1}, "score": 7}, "materiality"),
        ({"score_components": {"materiality": 2, "fundamental_impact": 1, "structure_alignment": 2, "execution_certainty": 2}, "score": 7}, "fundamental impact"),
        ({"score_components": {"materiality": 2, "fundamental_impact": 3, "structure_alignment": 2, "execution_certainty": 0}, "score": 7}, "execution certainty"),
        ({"red_flags": ["uma"]}, "red flag"),
        ({"health": {"ni_ttm": -1, "current_ratio": 0.8, "net_cash": False}}, "financial distress"),
    ],
)
def test_validate_publication_fields_rejects_failed_gate(changes, message):
    fields = _high_conviction_fields()
    fields.update(changes)
    with pytest.raises(ValueError, match=message):
        scan.validate_publication_fields(fields)


def test_validate_publication_fields_rejects_material_score_without_denominator():
    fields = _high_conviction_fields()
    fields["fundamental_context"] = {
        "market_cap": None,
        "total_revenue": None,
        "total_assets": None,
        "shares_outstanding": None,
    }
    with pytest.raises(ValueError, match="denominator"):
        scan.validate_publication_fields(fields)


def test_render_alert_uses_approved_idx_format():
    fields = _high_conviction_fields()
    fields["summary"] = (
        "Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.\n\n"
        "Struktur transaksi mendukung alignment pengendali dengan pemegang saham publik, tetapi realisasi dampaknya tetap bergantung pada eksekusi yang telah diungkapkan."
    )
    expected = (
        "### <:idx:1531974045266874499> ANTM (PT Aneka Tambang Tbk)\n"
        "Pengendali membeli saham dalam nilai yang material. Transaksi tidak menerbitkan saham baru dan meningkatkan kepemilikan pengendali.\n\n"
        "Struktur transaksi mendukung alignment pengendali dengan pemegang saham publik, tetapi realisasi dampaknya tetap bergantung pada eksekusi yang telah diungkapkan.\n"
        "┈┈┈┈┈┈┈┈┈┈┈┈┈\n"
        "*Jenis aksi:* Pembelian saham oleh pengendali\n"
        "*Skor katalis:* 7/10\n"
        "*Sumber:* [Keterbukaan Informasi BEI](<https://www.idx.co.id/StaticData/x/y.pdf>)"
    )
    output = scan.render_alert(fields)
    assert output == expected
    assert "RSI" not in output and "MA200" not in output and "ATR" not in output
    assert "**Fundamentals:**" not in output and "\u2014" not in output


def test_post_alert_rejects_before_discord(monkeypatch):
    fields = _high_conviction_fields()
    fields["score"] = 6
    monkeypatch.setattr(scan, "post_discord", lambda *args, **kwargs: pytest.fail("Discord must not be called"))
    with pytest.raises(ValueError, match="must equal component total"):
        scan.cli_post_alert(["--json", json.dumps(fields)])


def test_post_alert_dry_run(monkeypatch):
    captured = {}
    monkeypatch.setattr(scan, "post_discord",
                        lambda ch, content, media_path=None, dry_run=False:
                        captured.update(ch=ch, content=content, media=media_path) or True)
    rc = scan.cli_post_alert(["--json", json.dumps(_high_conviction_fields())])
    assert rc == 0
    assert captured["ch"] == scan.ALERT_CHANNEL
    assert captured["media"] == "/tmp/c.png"
    assert captured["content"].startswith("### <:idx:1531974045266874499> ANTM (PT Aneka Tambang Tbk)")


# --- Notif upgrade Task 4: attachment assembly ---
def test_assemble_pdf_text_labels_and_caps():
    chunks = [("cover.pdf", "AAA"), ("letter.pdf", "BBBB"), ("annex.pdf", "CCCCC")]
    out = scan._assemble_pdf_text(chunks, cap=1000)
    assert out == "[cover.pdf]\nAAA\n\n[letter.pdf]\nBBBB\n\n[annex.pdf]\nCCCCC"
    capped = scan._assemble_pdf_text(chunks, cap=12)
    assert len(capped) == 12 and capped.startswith("[cover.pdf]")


def test_assemble_pdf_text_skips_empty():
    out = scan._assemble_pdf_text([("a.pdf", ""), ("b.pdf", "X")], cap=1000)
    assert out == "[b.pdf]\nX"


# --- Notif upgrade Task 5: financial-report selection ---
def test_report_query_order_walks_back():
    now = scan.dt.datetime(2026, 6, 27, tzinfo=scan.WIB)
    order = scan._report_query_order(now)
    assert order[0] == (2026, "tw1")
    assert (2025, "audit") in order
    assert order[-1][0] == 2025


def test_pick_report_finds_financial_statement_pdf():
    # Real IDX naming: "FinancialStatement-<year>-<period>-<ticker>.pdf" (singular, plus an .xlsx twin).
    results = [{
        "KodeEmiten": "LSIP",
        "Attachments": [
            {"File_Name": "inlineXBRL.zip", "File_Type": ".zip",
             "File_Path": "/Portals/0/x/inlineXBRL.zip"},
            {"File_Name": "FinancialStatement-2026-I-LSIP.xlsx", "File_Type": ".xlsx",
             "File_Path": "/Portals/0/x/FinancialStatement-2026-I-LSIP.xlsx"},
            {"File_Name": "FinancialStatement-2026-I-LSIP.pdf", "File_Type": ".pdf",
             "File_Path": "/Portals/0/x/FinancialStatement-2026-I-LSIP.pdf"},
        ],
    }]
    url = scan._pick_report(results)
    assert url == "https://www.idx.co.id/Portals/0/x/FinancialStatement-2026-I-LSIP.pdf"


def test_pick_report_none_when_no_pdf():
    assert scan._pick_report([{"Attachments": [
        {"File_Name": "x.zip", "File_Type": ".zip", "File_Path": "/a.zip"}]}]) is None
    assert scan._pick_report([]) is None
