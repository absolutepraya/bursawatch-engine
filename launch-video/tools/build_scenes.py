#!/usr/bin/env python3
"""Build compositions/*.html from scenes-src/*.html.

Sources hold the scene markup, CSS, and GSAP timeline by hand. Placeholders
pull shared, data-driven fragments from the storyboard generator so the film
and the sketch sheet use the same real content:

  {{SOCIAL_CSS}}  realistic post styles (tools/social.py) + sheet primitives
  {{WALL}}        the everywhere wall, each card with an id and its own
                  directional-blur filter (s2-card-N / s2-fN)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import storyboard_sheet as SB  # noqa: E402
import social as S  # noqa: E402

BASE_CSS = """
.av { position: relative; display: inline-block; flex: none; }
.av img { width: 100%; height: 100%; object-fit: cover; display: block; }
.av .badge { position: absolute; right: -6%; bottom: -6%; border-radius: 22%; outline: .15cqw solid #000; }
"""


def sheet_css(*names):
    """Pull named sections (by their /* name */ header) out of the sheet CSS."""
    css = (ROOT / "tools/storyboard_sheet.css").read_text()
    blocks = re.split(r"\n(?=/\* )", css)
    keep = [b for b in blocks if any(b.startswith(f"/* {n}") for n in names)]
    return "\n".join(keep)


def proof():
    """Scene 3: the real #id-stocks-news channel, messages tagged s3-m0..2."""
    E, MEDIA = SB.E, SB.MEDIA
    msgs = [
        SB.TRUK,
        SB.dmsg("bridanareksa", "HRTA: Perkuat Pasokan Emas Domestik lewat Kerja Sama dengan Freeport Indonesia", "",
                "Hartadinata Abadi memperkuat bisnis bullion melalui kerja sama dengan PT Freeport Indonesia.",
                "Today at 18:02", f'<img class="dimg" src="assets/product/hrta-freeport.jpg">'),
        SB.dmsg("twitter", "IHSG Masih Lemah, Belum Ada Sinyal Pembalikan",
                f'{SB.avatar(f"{E}/aldotjahjadi.png", 30)} IHSG Journal',
                "Level 6.071 hingga 6.257 jadi area penting untuk menjaga pantulan; gagal bertahan membuka ruang ke 5.825.",
                "Today at 07:10"),
    ]
    out = []
    for i, m in enumerate(msgs):
        out.append(m.replace('<div class="dmsg">', f'<div class="dmsg" id="s3-m{i}">', 1))
    return '<div class="dch" data-layout-allow-overlap data-layout-allow-occlusion># id-stocks-news</div><div id="s3-feed">' + "".join(out) + "</div>"


TAG_ICON = {
    "primary": '<svg viewBox="0 0 20 20"><path d="M6 1h8l-2 6H8z" fill="#3B82F6"/><circle cx="10" cy="13" r="6" fill="#F5B32F"/></svg>',
    "support": '<svg viewBox="0 0 20 20"><path d="M6 1h8l-2 6H8z" fill="#3B82F6"/><circle cx="10" cy="13" r="6" fill="#B8C0CC"/></svg>',
    "below": '<svg viewBox="0 0 20 20"><path d="M3 5h14L10 17z" fill="#F23F43"/></svg>',
    "above": '<svg viewBox="0 0 20 20"><path d="M10 3l7 12H3z" fill="#2EE65F"/></svg>',
    "zone": '<svg viewBox="0 0 20 20"><rect x="4" y="4" width="12" height="12" fill="#F5D90A"/></svg>',
    "resolved": '<svg viewBox="0 0 20 20"><path d="M3 10l4.5 4.5L17 5" fill="none" stroke="#4A9BF5" stroke-width="2.6"/></svg>',
    "stop": '<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="6" fill="#F23F43"/></svg>',
    "support2": '<svg viewBox="0 0 20 20"><rect x="4" y="4" width="12" height="12" fill="#F5D90A"/></svg>',
}
TAG_LABEL = {"primary": "Primary plan", "support": "Supporting setup", "below": "Below entry", "above": "Above entry",
             "zone": "Entry zone", "resolved": "Resolved", "stop": "Stop-loss breached", "support2": "On support"}

FORUM = [
    ("PACK", "Thu, 1 Oct 2026", ("stop", "resolved"), "phintraco", "swing-PACK.jpg", "0", "7h ago"),
    ("BIPI", "Thu, 1 Oct 2026", ("primary", "below"), "phintraco", "swing-BIPI.jpg", "0", "7h ago"),
    ("HRTA", "Thu, 1 Oct 2026", ("primary", "below"), "phintraco", "swing-HRTA.jpg", "0", "7h ago"),
    ("BBNI", "Mon, 28 Sep 2026", ("primary", "support2"), "phintraco", "swing-BBNI.jpg", "2", "3d ago"),
    ("INDF", "Mon, 28 Sep 2026", ("primary", "zone"), "phintraco", "swing-INDF.jpg", "1", "3d ago"),
    ("JARR", "Fri, 25 Sep 2026", ("primary", "above"), "phintraco", "swing-JARR.jpg", "2", "6d ago"),
    ("AMMN", "Wed, 23 Sep 2026", ("support", "zone"), "bridanareksa", "swing-AMMN.jpg", "3", "8d ago"),
]
UNTR_POST = ("UNTR", "Wed, 30 Sep 2026", ("support", "above"), "twitter", "untr-triple-bottom.jpg", "3", "1d ago")


def forum_post(p, pid):
    tick, date, tags, src, img, replies, ago = p
    tag_html = "".join(f'<span class="ftag2">{TAG_ICON[t]}{TAG_LABEL[t]}</span>' for t in tags)
    return (f'<div class="fpost" id="{pid}"><div class="fl">{tag_html}<div class="ft">{tick} - {date}</div>'
            f'<div class="fby"><span class="bw">Bursawatch</span>: <img src="assets/sources/emoji/{src}.png"> {tick}:</div>'
            f'<div class="fmeta">&#128172; {replies} &middot; {ago}</div></div>'
            f'<img class="fthumb" src="assets/product/{img}"></div>')


def forum():
    filters = "".join(f'<span class="fchip">{TAG_ICON[t]}{TAG_LABEL[t]}</span>' for t in ("support", "primary", "resolved", "below"))
    posts = "".join(forum_post(p, f"s4-p{i}") for i, p in enumerate(FORUM * 2))
    return (f'<div class="fhead"><div class="fsearch" id="s4-search"><span class="mag">&#9906;</span><span id="s4-q" class="fq"></span>'
            f'<span id="s4-ph" class="fph">Search or create a post...</span><span id="s4-caret" class="fcaret"></span></div>'
            f'<span class="fnew">New Post</span></div><div class="frow"><span class="fchip">Sort &amp; View</span>{filters}</div>'
            f'<div class="flist"><div id="s4-list">{posts}</div><div id="s4-only">{forum_post(UNTR_POST, "s4-untr")}</div></div>')


def thread():
    E = SB.E
    x = (f'<div class="dmsg" id="s4-t0">{SB.bot_header("", "Yesterday at 16:31")}<div class="dbody">'
         f'<div class="dtitle"><img src="{E}/twitter.png">UNTR: Pola Triple Bottom Beri Peluang Penguatan</div>'
         f'<div class="dauth">{SB.avatar(f"{E}/doktermarket.png", 30)} DokterMarket</div>'
         f'<div class="dtext"><i>(Ringkasan)</i> UNTR berpeluang membentuk pola bullish triple bottom. Anotasi chart menunjukkan potensi ke 30.000, lalu 32.000.</div>'
         f'<img class="dimg" id="s4-chart" src="assets/product/untr-triple-bottom.jpg"></div></div>')
    b = SB.dmsg("bridanareksa", "UNTR: Dividen Interim, Buyback, dan Kenaikan RKAB Jadi Katalis", "",
                "Kuota batu bara naik ke 12,4 juta ton, dividen interim Rp430 per saham, buyback hingga Rp2 triliun.", "9/29/26, 14:31")
    t = SB.dmsg("tuntun", "UNTR: RKAB batu bara 2026 direvisi naik menjadi 12,4 juta ton", "",
                "RKAB batu bara UNTR untuk 2026 direvisi naik dari 7,4 juta ton.", "9/24/26, 13:07",
                SB.price_block("24.450", [("1D", "+50 (+0.20%)", "green"), ("1W", "-1.250 (-4.86%)", "red"),
                                          ("1M", "+325 (+1.35%)", "green"), ("3M", "+1.950 (+8.67%)", "green")]))
    b = b.replace('<div class="dmsg">', '<div class="dmsg" id="s4-t1">', 1)
    t = t.replace('<div class="dmsg">', '<div class="dmsg" id="s4-t2">', 1)
    return f'<div class="dch">&#128172; UNTR - Wed, 30 Sep 2026</div>{x}{b}{t}'


def candles():
    """Real ^JKSE daily candles to 30 Sep 2026 with IHSG Journal's levels (scene 5)."""
    import json
    d = json.load(open(ROOT / "research/jkse.json"))
    d = [r for r in d if r["date"] <= "2026-09-30"][-44:]
    lo, hi = 5720, 7250
    W, H = 900, 420
    step = W / len(d)

    def yy(v):
        return H - (v - lo) / (hi - lo) * H

    out = []
    for i, r in enumerate(d):
        x = i * step + step / 2
        col = "#2EE65F" if r["c"] >= r["o"] else "#F23F43"
        top, bot = yy(max(r["o"], r["c"])), yy(min(r["o"], r["c"]))
        out.append(f'<g class="cdl"><line x1="{x:.1f}" x2="{x:.1f}" y1="{yy(r["h"]):.1f}" y2="{yy(r["l"]):.1f}" stroke="{col}" stroke-width="2"/>'
                   f'<rect x="{x - step * .32:.1f}" y="{top:.1f}" width="{step * .64:.1f}" height="{max(2, bot - top):.1f}" fill="{col}"/></g>')
    lv = ""
    for k, (lvl, lab, col, op) in enumerate([(6257, "Resistance 6.257", "#DEA777", 1), (6071, "Support 6.071", "#DEA777", 1), (5825, "5.825", "#9C978E", .7)]):
        y = yy(lvl)
        lv += (f'<g class="lvl" id="s5-lv{k}" opacity="{op}"><line x1="0" x2="{W}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="3" stroke-dasharray="14 10" pathLength="1000"/>'
               f'<text x="{W + 14}" y="{y + 8:.1f}" text-anchor="start" fill="{col}" font-family="Hanken Grotesk" font-weight="700" font-size="24">{lab}</text></g>')
    return f'<svg viewBox="0 0 {W + 200} {H}" class="s5chart" overflow="visible">{"".join(out)}{lv}</svg>'


def true_chart():
    """TRUE.JK real daily candles, Nov 2025 to 6 Feb 2026 (scene 1, X pain).

    Candles up to the post date (13 Jan) are visible first; the rest sit
    behind a clip rect (#s1-trueclip) that the timeline widens on the hero beat.
    """
    import json
    d = [r for r in json.load(open(ROOT / "research/true.json")) if "2025-11-10" <= r["date"] <= "2026-02-06"]
    W, H, VH = 600, 250, 46
    lo, hi = 150, 560
    step = W / len(d)

    def yy(v):
        return H - (v - lo) / (hi - lo) * H

    vmax = max(r["v"] for r in d) or 1
    out, cut = [], 0
    for i, r in enumerate(d):
        x = i * step + step / 2
        col = "#00C176" if r["c"] >= r["o"] else "#F23F43"
        top, bot = yy(max(r["o"], r["c"])), yy(min(r["o"], r["c"]))
        vh = r["v"] / vmax * VH
        out.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{yy(r["h"]):.1f}" y2="{yy(r["l"]):.1f}" stroke="{col}" stroke-width="1.6"/>'
                   f'<rect x="{x - step * .34:.1f}" y="{top:.1f}" width="{step * .68:.1f}" height="{max(1.6, bot - top):.1f}" fill="{col}"/>'
                   f'<rect x="{x - step * .34:.1f}" y="{H + 14 + VH - vh:.1f}" width="{step * .68:.1f}" height="{vh:.1f}" fill="{col}" opacity=".45"/>')
        if r["date"] <= "2026-01-13":
            cut = x + step / 2
    base = yy(210)
    grid = "".join(f'<text x="{W + 10}" y="{yy(v) + 6:.1f}" fill="#8A8F98" font-size="17" font-family="Figtree">{v}</text>' for v in (200, 300, 400, 500))
    return (f'<svg viewBox="0 0 {W + 60} {H + 14 + VH}" class="truechart">'
            f'<defs><clipPath id="s1-trueclip"><rect id="s1-trueclipr" x="0" y="0" width="{cut:.1f}" height="{H + 14 + VH}"/></clipPath></defs>'
            f'<line x1="0" x2="{W}" y1="{base:.1f}" y2="{base:.1f}" stroke="#5b6068" stroke-width="1.5" stroke-dasharray="6 6"/>{grid}'
            f'<g clip-path="url(#s1-trueclip)">{"".join(out)}</g></svg>'), round(cut, 1), W


def ketr_spark():
    import json
    d = [r for r in json.load(open(ROOT / "research/ketr.json")) if r["date"] <= "2026-09-28"]
    c = [r["c"] for r in d]
    lo, hi = min(c) - 10, max(c) + 10
    W, H = 200, 64
    pts = " ".join(f"{i / (len(c) - 1) * W:.1f},{H - (v - lo) / (hi - lo) * H:.1f}" for i, v in enumerate(c))
    return f'<svg viewBox="0 0 {W} {H}" class="spark"><polyline points="{pts}" fill="none" stroke="#2EE65F" stroke-width="3.2" stroke-linejoin="round"/></svg>'


def wall():
    html = SB.wall_real()
    n = 0

    def tag(m):
        nonlocal n
        out = f'<div id="s2-card-{n}" data-dim="{1 if "dim" in m.group(1) else 0}" class="sp{m.group(1)} " style="filter:url(#s2-f{n});'
        n += 1
        return out

    html = re.sub(r'<div class="sp((?: dim)?) ([a-z]+)" style="', lambda m: tag(m).replace('class="sp' + m.group(1) + ' "', 'class="sp' + m.group(1) + ' ' + m.group(2) + '"'), html)
    filters = "".join(
        f'<filter id="s2-f{i}" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur id="s2-b{i}" stdDeviation="0 0"/></filter>'
        for i in range(n))
    svg = f'<svg width="0" height="0" style="position:absolute" aria-hidden="true">{filters}</svg>'
    return svg + html.replace('class="wall wallbg"', 'id="s2-wall" class="wall wallbg"', 1), n


def main():
    wall_html, n = wall()
    parts = {
        "{{SOCIAL_CSS}}": BASE_CSS + S.CSS,
        "{{WALL}}": wall_html,
        "{{WALL_N}}": str(n),
        "{{DISCORD_CSS}}": sheet_css("avatars", "captions", "discord", "forum", "brief", "config"),
        "{{PROOF}}": proof(),
        "{{FORUM}}": forum(),
        "{{THREAD}}": thread(),
        "{{CANDLES}}": candles(),
        "{{TRUE_CHART}}": true_chart()[0],
        "{{TRUE_CUT}}": str(true_chart()[1]),
        "{{TRUE_W}}": str(true_chart()[2]),
        "{{KETR_SPARK}}": ketr_spark(),
        "{{BOTHEAD}}": SB.bot_header("", "Kamis, 1 Okt 2026 · 08.00 WIB"),
    }
    for src in sorted((ROOT / "scenes-src").glob("*.html.tpl")):
        text = src.read_text()
        for k, v in parts.items():
            text = text.replace(k, v)
        out = ROOT / "compositions" / src.name.removesuffix(".tpl")
        out.write_text(text.replace("<!doctype html>", "<!doctype html>\n<!-- generated by tools/build_scenes.py from scenes-src; edit the source -->", 1))
        print("built", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
