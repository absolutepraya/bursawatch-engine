#!/usr/bin/env python3
"""Generate storyboard.html, the static sketch sheet for review.

Every cell is a 16:9 frame drawn in cqw units (1920px frame = 100cqw, so
1px = 0.05208cqw) with the frame.md fonts and colours. No scripts in the
output; it opens from file://.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import social as S  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
E = "assets/sources/emoji"
MEDIA = "assets/discord-media"
VERSION = "v2"


def px(v):
    return f"{v / 19.2:.3f}cqw"


# ---------- shared pieces ----------

def avatar(src, size, badge=None, rounded=True):
    b = ""
    if badge:
        b = (f'<img class="badge" src="{E}/{badge}.png" '
             f'style="width:{px(size * .42)};height:{px(size * .42)}">')
    r = "50%" if rounded else px(size * .22)
    return (f'<span class="av" style="width:{px(size)};height:{px(size)}">'
            f'<img src="{src}" style="border-radius:{r}">{b}</span>')


def bot_header(t, time):
    return (f'<div class="dhead">{avatar("assets/brand/cropped_circle.png", 64)}'
            f'<div><span class="botname">Bursawatch</span><span class="app">APP</span>'
            f'<span class="dtime">{time}</span></div></div>')


def price_block(last, rows):
    cells = []
    for lab, val, kind in rows:
        cells.append(f'<span class="pr"><img src="{E}/{kind}.png">{lab}: <b>{val}</b></span>')
    return (f'<div class="price">Harga terakhir (IDR): <b>{last}</b><div class="prow">'
            + "".join(cells) + "</div></div>")


def dmsg(src_emoji, title, author, body, time, extra="", badge_note=""):
    a = f'<div class="dauth">{author}</div>' if author else ""
    return (f'<div class="dmsg">{bot_header(title, time)}<div class="dbody">'
            f'<div class="dtitle"><img src="{E}/{src_emoji}.png">{title}</div>{a}'
            f'<div class="dtext"><i>(Ringkasan)</i> {body}</div>{extra}</div></div>')


def caption(first, rest, second=""):
    s = f'<div class="cap2">{second}</div>' if second else ""
    return (f'<div class="cap"><span class="c1">{first}</span> {rest}'
            f'<span class="caret"></span>{s}</div>')


def mini_card(emoji, name, title, x, y, w=300, opacity=1, badge=None, tilt=0):
    return (f'<div class="mc" style="left:{px(x)};top:{px(y)};width:{px(w)};opacity:{opacity};'
            f'transform:rotate({tilt}deg)">'
            f'<div class="mch">{avatar(f"{E}/{emoji}.png", 34, badge)}<span>{name}</span></div>'
            f'<div class="mct">{title}</div><div class="bar"></div><div class="bar s"></div></div>')


WALL = [
    ("tuntun", "Tuntun Sekuritas", "TRUK: VTO maksimal 65,25 juta saham", None),
    ("phintraco", "Phintraco Sekuritas", "PACK: Buy, entry 498 to 510", None),
    ("bridanareksa", "BRI Danareksa", "Harga Brent tembus US$106", None),
    ("doktermarket", "DokterMarket", "UNTR: pola triple bottom", "twitter"),
    ("stockbit", "Stockbit", "MGLV: pinjaman Rp10,7 triliun", None),
    ("aldotjahjadi", "IHSG Journal", "IHSG masih lemah", "twitter"),
    ("kelasinvestasi", "Kelas Investasi", "PWON: uji area konsolidasi", None),
    ("kobeissiletter", "The Kobeissi Letter", "Yield US 10Y tembus 5,30%", "twitter"),
    ("SAMUEL", "Samuel Sekuritas", "Morning research, 1 Okt", None),
    ("rickyho1989", "Ricky Ho", "MEDC: menguji resistensi", "twitter"),
    ("IG", "akun IG", "Reels: saham pilihan minggu ini", "instagram"),
    ("tuntun", "Tuntun Sekuritas", "UNTR: RKAB naik ke 12,4 juta ton", None),
    ("bridanareksa", "BRI Danareksa", "BI tahan suku bunga", None),
    ("writingtorch", "Writing Torch", "TPIA: ekspansi mobilitas", "twitter"),
    ("phintraco", "Phintraco Sekuritas", "BBNI: On support", None),
    ("arvinhonami", "Arvin Honami", "AKRA: beli jika break", "twitter"),
]


def wall(opacity=1.0, blur=0):
    out = []
    # two bands like ref 1: top band rows at y 56 and 214, bottom band at 760 and 918,
    # columns every 330px with alternating offsets so cards overlap slightly
    slots = []
    for row, (y, off) in enumerate(((56, 0), (214, 165), (760, 80), (918, 245))):
        for c in range(6):
            slots.append((off + c * 330 - 60, y))
    for i, (x, y) in enumerate(slots[:len(WALL) + 8]):
        emo, name, title, badge = WALL[i % len(WALL)]
        src_emo = {"SAMUEL": "../web/samuel-icon", "IG": "instagram"}.get(emo, emo)
        out.append(mini_card(src_emo, name, title, x, y, 300, opacity, badge))
    style = f"filter:blur({px(blur)})" if blur else ""
    return f'<div class="wall" style="{style}">' + "".join(out) + "</div>"


GREY = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'%3E%3Crect width='10' height='10' fill='%2355585c'/%3E%3C/svg%3E"
UNTR_CHART = f'<img src="{MEDIA}/id-stocks-swing-1554787757468033167-0.jpg">'


def place(html, x, y, dim=False):
    cls = ' dim' if dim else ''
    return html.replace('class="sp ', f'class="sp{cls} ', 1).replace(
        'style="width:', f'style="left:{px(x)};top:{px(y)};width:', 1)


def wall_real(opacity=1.0, blur=0):
    cards = [
        place(S.x_post(px, "DokterMarket", "@doktermarket", "1j",
                       "Bursa AS bervariasi. Dow -0,86%, S&P 500 -0,25%, Nasdaq +0,24%. IHSG turun 0,83% ke 6.071, rupiah menguat ke Rp17.877.",
                       ("24", "61", "412", "18 rb"), w=470, marks=["IHSG turun 0,83%"], avatar=f"{E}/doktermarket.png"), 22, 22),
        place(S.tg_post(px, "Tuntun Sekuritas", f"{E}/tuntun.png",
                        "TRUK: PT Pukul Rata Kanan mengajukan VTO maksimal 65,25 juta saham di harga Rp740 per saham.",
                        "3,1 rb", "18.00", w=450), 512, 30, dim=True),
        place(S.wa_post(px, "BRI Danareksa Sekuritas", f"{E}/bridanareksa.png",
                        "Harga Brent tembus US$106 akibat ketegangan Selat Hormuz.", "08.43", "214", w=440), 990, 26, dim=True),
        place(S.x_post(px, "The Kobeissi Letter", "@KobeissiLetter", "2j",
                       "BREAKING: The 10-year note yield hits 5.30%, its highest level since 2002.",
                       ("1,2 rb", "3,4 rb", "19 rb", "2,1 jt"), w=448, marks=["5.30%"], avatar=f"{E}/kobeissiletter.png"), 1452, 22),
        place(S.ig_post(px, "assets/pain/ig-3-ahap.jpg", "Anthoni Salim siap tebus rights issue $AHAP", "5j", w=250), 30, 330),
        place(S.tg_post(px, "Phintraco Sekuritas", f"{E}/phintraco.png",
                        "PACK: Trading Buy\nEntry 498 to 510\nStop-loss &lt;480\nTarget 560 / 600",
                        "5,8 rb", "05.43", w=300, marks=["Trading Buy"]), 300, 470),
        place(S.sb_post(px, "MGLV", "Dua anak usaha dapat pinjaman hingga Rp10,7 triliun untuk data center.",
                        "24 Sep", w=400, marks=["Rp10,7 triliun"]), 1492, 340),
        place(S.x_post(px, "IHSG Journal", "@aldotjahjadi8", "7j",
                       "Teknikal IHSG masih lemah. 6.071 sampai 6.257 jadi area penting buat jaga pantulan.",
                       ("9", "27", "188", "6 rb"), w=400, avatar=f"{E}/aldotjahjadi.png"), 1492, 610),
        place(S.tg_post(px, "Kelas Investasi", f"{E}/kelasinvestasi.png",
                        "PWON mulai menguat, lagi uji area atas konsolidasi.", "1,4 rb", "02.04", w=440), 22, 850),
        place(S.x_post(px, "DokterMarket", "@doktermarket", "1h",
                       "UNTR berpeluang bentuk bullish triple bottom. Target 30.000, lalu 32.000.",
                       ("41", "96", "803", "31 rb"), media=UNTR_CHART, w=470, avatar=f"{E}/doktermarket.png"), 500, 860, dim=True),
        place(S.wa_post(px, "BRI Danareksa Sekuritas", f"{E}/bridanareksa.png",
                        "BI tahan suku bunga, aktivitas ekonomi Indonesia tetap solid.", "09.06", "167", w=440), 1000, 880, dim=True),
        place(S.x_post(px, "IHSG Journal", "@aldotjahjadi8", "3j",
                       "Larangan afiliasi ESDM bakal alihkan pangsa pasar ke kontraktor independen. UNTR dan DOID diuntungkan.",
                       ("12", "40", "256", "9 rb"), w=448, marks=["UNTR dan DOID"], avatar=f"{E}/aldotjahjadi.png"), 1452, 850),
    ]
    style = f"opacity:{opacity};" + (f"filter:blur({px(blur)})" if blur else "")
    return f'<div class="wall wallbg" style="{style}">' + "".join(cards) + "</div>"


B_MARK = ('<svg viewBox="0 0 96 96" class="bmark"><g fill="#DEA777" transform="translate(-2 -2)">'
          '<path d="M14 10H46C66 10 79 20 79 35C79 44 74 50 65 54L51 46C60 43 65 40 65 35C65 28 58 24 46 24H14V10Z"/>'
          '<path d="M14 33H35L74 56C82 61 86 67 86 74C86 84 73 90 51 90H14V76H50C64 76 71 74 71 70C71 67 66 64 60 60L14 33Z"/>'
          '<path d="M14 54H31L53 67H14V54Z"/></g></svg>')


def candles():
    d = json.load(open(ROOT / "research/jkse.json"))
    d = [r for r in d if r["date"] <= "2026-09-30"][-48:]
    lo, hi = 5750, 7350
    W, H = 1100, 520
    step = W / len(d)

    def yy(v):
        return H - (v - lo) / (hi - lo) * H

    parts = []
    for i, r in enumerate(d):
        x = i * step + step / 2
        up = r["c"] >= r["o"]
        col = "#2EE65F" if up else "#F23F43"
        top, bot = yy(max(r["o"], r["c"])), yy(min(r["o"], r["c"]))
        parts.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{yy(r["h"]):.1f}" y2="{yy(r["l"]):.1f}" stroke="{col}" stroke-width="2"/>')
        parts.append(f'<rect x="{x - step * .32:.1f}" y="{top:.1f}" width="{step * .64:.1f}" height="{max(2, bot - top):.1f}" fill="{col}"/>')
    lines = ""
    for lvl, lab, col, op in [(6257, "Resistance 6.257", "#DEA777", 1), (6071, "Support 6.071", "#DEA777", 1), (5825, "5.825", "#9C978E", .6)]:
        y = yy(lvl)
        lines += (f'<line x1="0" x2="{W}" y1="{y:.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="3" stroke-dasharray="14 10" opacity="{op}"/>'
                  f'<text x="{W - 8}" y="{y - 10:.1f}" text-anchor="end" fill="{col}" opacity="{op}" font-family="Hanken Grotesk" font-size="26">{lab}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="chart">' + "".join(parts) + lines + "</svg>")


# ---------- frames ----------

F = {}

F[1] = f'''<div class="glow" style="left:50%;top:48%"></div>
<div class="center voice lg">Nyari info saham yang <span class="cu">cepet</span> dan <span class="cu">bener</span>,<br>di mana sih?</div>'''


def pain(n, total, card, q, a, stack, staged=True):
    behind = "".join(
        f'<div class="pcard ghost" style="transform:translate({px(-40 * (k + 1))},0) scale({1 - .06 * (k + 1)});opacity:{.5 - .15 * k}"></div>'
        for k in range(stack))
    return (f'<div class="kicker">Nyari info saham yang cepet dan bener, di mana sih?</div>'
            f'<div class="count">{n:02d} / {total:02d}</div>'
            + (f'<div class="pstage">{behind}{card}</div>' if staged else card) +
            f'<div class="pq voice">{q}</div><div class="pa">{a}</div>')


def ig_card():
    # real IG news posts supplied by the user, account branding already whited out
    back = "".join(
        f'<div class="igpost back" style="transform:rotate({r}deg) translateX({px(dx)})">'
        f'<img class="igimg" src="assets/pain/{f}"></div>'
        for f, r, dx in (("ig-4-ultj.jpg", -9, -120), ("ig-1-byan.jpg", 7, 130)))
    front = (f'<div class="igpost"><div class="igh">{avatar(f"{E}/instagram.png", 40)}'
             f'<span class="bars"><b></b></span><span class="stamp">3 jam lalu</span></div>'
             f'<img class="igimg" src="assets/pain/ig-2-ketr.jpg"></div>')
    return f'<div class="igstack">{back}{front}</div>'


def tg_card():
    return (f'<div class="pcard"><div class="ph">{avatar(f"{E}/telegram.png", 56)}<span class="bars"><b></b><i></i></span></div>'
            f'<div class="pbig">VIP INSIDER A1</div><div class="psub">Rp1,5 jt / bulan. Slot terbatas!</div>'
            f'<div class="pbtn">Gabung sekarang</div></div>')


def kelas_card():
    return (f'<div class="pcard"><div class="ph"><span class="sq"></span><span class="bars"><b></b><i></i></span></div>'
            f'<div class="pbig">Kelas Saham<br>Pasti Cuan</div><div class="psub">Modul 1 sampai 12, sertifikat</div>'
            f'<div class="pbtn">Daftar</div></div>')


def x_card():
    # fictional post written in the usual "sirkel" pump style; identity blurred
    chart = ('<svg viewBox="0 0 600 220" style="background:#0b0c0d"><polyline points="0,190 90,186 180,180 250,178 300,120 350,104 400,70 460,62 520,40 600,18" '
             'fill="none" stroke="#2EE65F" stroke-width="6"/><line x1="0" x2="600" y1="150" y2="150" stroke="#555" stroke-dasharray="10 8"/></svg>')
    post = S.x_post(px, "Sahabat Cuan", "@sahabatcuan", "28 Jun",
                    "Artinya harga $XXXX udah masuk area spekulasi buat jualan di 300 sampai 400. Target akhirnya 610 &#128640;\n\nKo bisa? Jawabannya ada di Sirkel VIP &#128521;",
                    ("86", "143", "1,1 rb", "48 rb"), media=chart, w=690, avatar=GREY, blur_id=True)
    return post.replace('class="sp x"', 'class="sp x" style="left:0;top:-2cqw"', 1)


F[2] = pain(1, 4, ig_card(), "Berita IG?", "Udah telat.", 0, staged=False)
F[3] = pain(2, 4, tg_card(), "Grup &lsquo;insider A1&rsquo;?", "Boncos.", 1)
F[4] = pain(3, 4, kelas_card(), "Kelas sana-sini?", "Teori sama market-nya beda.", 2)
F[5] = pain(4, 4, x_card(), "Stockpick di X?", "Rungkad.", 3)

F[6] = wall_real() + '<div class="headline-xl">Infonya ada<br><span class="mark">di mana-mana.</span></div>'
F[7] = wall_real(.15, 6) + '<div class="headline-xl">Tapi mana<br>yang bener?</div>'

F[8] = (wall(.0) + '<div class="label" style="left:50%;top:22%">Kenalin,</div>'
        + "".join(f'<div class="inlet" style="top:{px(y)};"></div>' for y in (430, 540, 650))
        + mini_card("tuntun", "Tuntun", "TRUK: VTO", 200, 380, 220, .9)
        + mini_card("doktermarket", "DokterMarket", "UNTR", 420, 500, 220, .7, "twitter")
        + mini_card("bridanareksa", "BRI Danareksa", "Brent", 120, 610, 220, .8)
        + f'<div class="bwrap" style="left:{px(860)};top:{px(330)};width:{px(420)}">{B_MARK}</div>')

F[9] = (''.join(f'<div class="ring" style="width:{px(s)};height:{px(s)};opacity:{o}"></div>' for s, o in ((700, .5), (1200, .3), (1800, .15)))
        + '<div class="label" style="left:50%;top:20%">Kenalin,</div>'
        + f'<div class="lock"><span class="lb">{B_MARK}</span><span class="wm">Bursawatch</span></div>'
        + '<div class="sub voice">Semua info saham penting, langsung ke Discord kamu.</div>')

CHIPS = [("Trading ideas", "phintraco", -7, 330, 150), ("Aksi korporasi", "tuntun", 6, 1250, 130),
         ("Makro", "bridanareksa", -5, 1340, 520), ("Komoditas", "kobeissiletter", 7, 300, 470),
         ("Industri &amp; regulasi", "stockbit", -3, 1060, 820)]
F[10] = (f'<div class="hub">{avatar("assets/brand/cropped_circle.png", 260)}</div>'
         + "".join(f'<div class="chip" style="left:{px(x)};top:{px(y)};transform:rotate({r}deg)">'
                   f'<img src="{E}/{e}.png"><span class="h">#</span>{t}</div>' for t, e, r, x, y in CHIPS)
         + caption("udah dipilah.", "dari sumber kredibel."))

TRUK = dmsg("tuntun", "TRUK: PT Pukul Rata Kanan mengajukan VTO maksimal 65,25 juta saham", "",
            "PT Pukul Rata Kanan mengajukan VTO maksimal 65,25 juta saham atau 15% saham TRUK pada harga Rp740 per saham.",
            "Today at 18:00",
            price_block("2.580", [("1D", "+510 (+24.64%)", "green"), ("1W", "+1.160 (+81.69%)", "green"),
                                   ("1M", "+1.815 (+237.25%)", "green"), ("3M", "+2.158 (+511.37%)", "green")]))
F[11] = (f'<div class="dframe" style="left:{px(760)};top:{px(70)};width:{px(1080)};height:{px(940)}">'
         f'<div class="dch"># id-stocks-news</div>{TRUK}'
         + dmsg("bridanareksa", "HRTA: Perkuat Pasokan Emas Domestik lewat Kerja Sama dengan Freeport Indonesia", "",
                "Hartadinata Abadi memperkuat bisnis bullion melalui kerja sama dengan PT Freeport Indonesia.",
                "Today at 18:02", f'<img class="dimg" src="{MEDIA}/id-stocks-news-1552589985792663595-0.jpg">')
         + '</div>' + caption("dipantau 24 jam.", "dirangkum AI."))

POSTS = [("Stop-loss breached", "Resolved", "PACK - Thu, 1 Oct 2026", "id-stocks-swing-1555043647110783058-0.jpg"),
         ("Primary plan", "Below entry", "BIPI - Thu, 1 Oct 2026", "id-stocks-swing-1555043161653641266-0.jpg"),
         ("Primary plan", "Below entry", "HRTA - Thu, 1 Oct 2026", "id-stocks-swing-1555043074772705330-0.jpg"),
         ("Primary plan", "Entry zone", "INDF - Mon, 28 Sep 2026", "id-stocks-swing-1554241677470998588-0.jpg"),
         ("Primary plan", "Above entry", "JARR - Fri, 25 Sep 2026", "id-stocks-swing-1552842701861298226-0.jpg")]


def forum(query="", posts=POSTS, search_active=False):
    q = (f'<span class="typed">{query}</span><span class="caret dark"></span>' if query
         else '<span class="ph2">Search or create a post...</span>')
    rows = "".join(
        f'<div class="post"><div><span class="ftag">{t1}</span><span class="ftag">{t2}</span>'
        f'<div class="ptitle2">{title}</div><div class="pby"><span class="bw">Bursawatch</span>: '
        f'<img src="{E}/phintraco.png"> {title.split(" ")[0]}:</div></div>'
        f'<img class="thumb" src="{MEDIA}/{img}"></div>' for t1, t2, title, img in posts)
    return (f'<div class="dframe" style="left:{px(760)};top:{px(60)};width:{px(1080)};height:{px(960)}">'
            f'<div class="search{" on" if search_active else ""}">{q}</div>{rows}</div>')


F[12] = forum() + caption("swing board.", "semua trading ideas, satu tempat.")
F[13] = forum("UNTR", [("Supporting setup", "Status date", "UNTR - Wed, 30 Sep 2026",
                        "id-stocks-swing-1554787757468033167-0.jpg")], True) + caption("cari", "saham incaranmu.")

UNTR_X = (f'<div class="dmsg">{bot_header("", "Yesterday at 16:31")}<div class="dbody">'
          f'<div class="dtitle"><img src="{E}/twitter.png">UNTR: Pola Triple Bottom Beri Peluang Penguatan</div>'
          f'<div class="dauth">{avatar(f"{E}/doktermarket.png", 30)} DokterMarket</div>'
          f'<img class="dimg" src="{MEDIA}/id-stocks-swing-1554787757468033167-0.jpg"></div></div>')
F[14] = (f'<div class="dframe" style="left:{px(760)};top:{px(60)};width:{px(1080)};height:{px(960)}">'
         f'<div class="dch">UNTR - Wed, 30 Sep 2026</div>{UNTR_X}'
         + dmsg("bridanareksa", "UNTR: Dividen Interim, Buyback, dan Kenaikan RKAB Jadi Katalis", "",
                "Kuota batu bara naik ke 12,4 juta ton, dividen interim Rp430 per saham.", "9/29/26, 14:31")
         + dmsg("tuntun", "UNTR: RKAB batu bara 2026 direvisi naik menjadi 12,4 juta ton", "",
                "RKAB batu bara UNTR untuk 2026 direvisi naik dari 7,4 juta ton.", "9/24/26, 13:07",
                price_block("24.450", [("1D", "+50 (+0.20%)", "green"), ("1W", "-1.250 (-4.86%)", "red"),
                                       ("1M", "+325 (+1.35%)", "green"), ("3M", "+1.950 (+8.67%)", "green")]))
         + '</div>' + caption("cek", "siapa aja yang udah bahas sahammu."))


def brief(inner):
    return (f'<div class="soon">segera hadir</div>'
            f'<div class="bcard">{bot_header("", "Kamis 1 Okt, 08.00 WIB")}<div class="btitle">Morning brief</div>{inner}</div>'
            + caption("08.00 WIB.", "morning brief."))


IDX = [("NASDAQ", "26.861", "+0,24%", "up"), ("NIKKEI", "66.754", "+1,94%", "up"), ("KOSPI", "6.838", "-0,48%", "down")]
F[15] = brief('<div class="tiles">' + "".join(
    f'<div class="tile"><div class="tn">{n}</div><div class="tv">{v}</div><div class="tc {k}">{c}</div></div>'
    for n, v, c, k in IDX) + '<div class="note">penutupan 30 Sep 2026</div></div>')
F[16] = brief('<div class="night"><div class="nl">Semalam</div>'
              '<div class="nh">Inflasi AS melandai, peluang The Fed naikin bunga turun ke 37%.</div>'
              '<div class="ns">Brent masih di atas US$100, Selat Hormuz masih panas.</div></div>')
F[17] = brief('<div class="nl" style="margin-left:{0}">Kata trader di X</div>'.format(px(40))
              + f'<div class="takes"><div class="take">{avatar(f"{E}/aldotjahjadi.png", 52, "twitter")}<div><b>IHSG Journal</b>'
              f'<p>IHSG masih lemah, belum ada sinyal pembalikan.</p><span class="pill warn">hati-hati</span></div></div>'
              f'<div class="take">{avatar(f"{E}/aldotjahjadi.png", 52, "twitter")}<div><b>IHSG Journal</b>'
              f'<p>IHSG dinilai mulai terbebas dari tekanan MSCI.</p><span class="pill ok">optimis</span></div></div></div>'
              '<div class="balance"><span>optimis</span><div class="track"><i style="width:36%"></i></div><span>hati-hati</span></div>')
F[18] = brief(f'<div class="chartwrap">{candles()}</div><div class="verdict">Sideways, rawan turun.</div>')


def toggle(label, on=True):
    return f'<div class="row"><span>{label}</span><span class="tog{" on" if on else ""}"><i></i></span></div>'


def sources(added):
    rows = [("tuntun", "Tuntun Sekuritas", None, "")]
    if added:
        rows.append(("rickyho1989", "+ analis pilihanmu", "twitter", " add"))
    else:
        rows.append((None, "Tambah sumber", None, " ghostrow"))
    out = ""
    for e, n, b, cls in rows:
        a = avatar(f"{E}/{e}.png", 38, b) if e else '<span class="plus">+</span>'
        ck = '<span class="ck">&#10003;</span>' if e else ""
        out += f'<div class="row src{cls}">{a}<span>{n}</span>{ck}</div>'
    return out


# (question, before state, after state)
QUADS = [
    ("Mau dirangkum tiap malem aja?",
     toggle("Morning brief, 08.00", True) + toggle("Ringkasan malam, 21.00", False),
     toggle("Morning brief, 08.00", True) + toggle("Ringkasan malam, 21.00", True)),
    ("Mau mantau analis favoritmu?", sources(False), sources(True)),
    ("Mau ganti jam kirimnya?",
     '<div class="time"><span class="new">08.00</span></div><div class="tl">jam kirim morning brief</div>',
     '<div class="time"><span class="old">08.00</span><span class="new">06.30</span></div><div class="tl">jam kirim morning brief</div>'),
    ("Males baca tiap hari?",
     '<div class="seg"><span class="sel">Harian</span><span>Mingguan</span></div><div class="tl">Tiap hari, jam 08.00.</div>',
     '<div class="seg"><span>Harian</span><span class="sel">Mingguan</span></div><div class="tl">Seminggu sekali aja.</div>'),
]


def quad_page(active):
    out = ['<div class="qline" style="left:50%;top:0;bottom:0;width:.1cqw"></div>',
           '<div class="qline" style="top:50%;left:0;right:0;height:.1cqw"></div>']
    for i, (q, before, after) in enumerate(QUADS):
        x, y = (i % 2) * 50, (i // 2) * 28.125
        body = after if i <= active else before
        cls = "" if i == active else " muted"
        stamp = '<div class="qbisa">BISA.</div>' if i <= active else ""
        out.append(f'<div class="quad{cls}" style="left:{x}cqw;top:{y}cqw"><div class="qq">{q}</div>'
                   f'<div class="qc">{body}</div>{stamp}</div>')
    return "".join(out)


F[19] = quad_page(0)
F[20] = quad_page(1)
F[21] = quad_page(2)
F[22] = quad_page(3)

F[23] = ('<div class="center voice lg" style="top:30%">Infonya, dan cara nyarinya,<br><span class="cu">kamu yang atur.</span></div>'
         f'<div class="lock small"><span class="lb">{B_MARK}</span><span class="wm">Bursawatch</span></div>'
         '<div class="url">bursawatch.abhipraya.dev</div>')

# ---------- metadata per frame ----------

META = [
    (1, "HOOK", "0.0–2.8", "<b>Words rise first.</b> Ref 1 mask rise, speech cadence; cepet and bener in copper. Seam: the line lifts into the top-left kicker.", "lift"),
    (2, "PAIN · IG", "2.8–4.3", "<b>Card slides in from the left</b> (12 frames, horizontal blur), then the answer drops in. Unbranded example.", "push"),
    (3, "PAIN · TELEGRAM", "4.3–5.8", "<b>New card pushes the old one back</b> (scale 0.94, dims). Answer lands on a beat.", "push"),
    (4, "PAIN · KELAS", "5.8–7.3", "<b>Stack grows</b>, three cards deep. Same stage, nothing resets.", "push"),
    (5, "PAIN · X", "7.3–8.8", "<b>Fictional pump-style X post</b> (identity blurred); the chart flips red, then Rungkad. Seam: cards fly out to join the wall.", "scatter"),
    (6, "EVERYWHERE", "8.8–12.0", "<b>Real posts in their native UI</b> (X, Telegram, WhatsApp, IG, Stockbit) slide in around the edges like ref 1; some sit dimmed for depth. Headline rises; copper marker sweeps behind di mana-mana.", "continuous"),
    (7, "DOUBT", "12.0–14.0", "<b>Wall ghosts to 15% and blurs.</b> Question rises word by word over the riser.", "continuous"),
    (8, "ABSORB", "14.0–16.2", "<b>Cards sharpen and stream right</b> along three copper lines into the B's inlets; the mark fills inlet by inlet.", "build"),
    (9, "LOCKUP", "16.2–19.5", "<b>Drop.</b> Mark lands, wordmark rises, rings ripple out. Held frame with a slow push.", "zoom-through"),
    (10, "CHANNELS", "19.5–23.0", "<b>Avatar pops with overshoot</b>, chips launch from behind it on the beat (ref 3) and park tilted.", "zoom-through"),
    (11, "PROOF", "23.0–26.0", "<b>Real messages stack in</b> with a ping each; caption types bottom-left (ref 4).", "line"),
    (12, "SWING · SCROLL", "26.0–29.0", "<b>Forum scrolls fast</b>, decelerating; tags and real chart thumbnails.", "continuous"),
    (13, "SWING · SEARCH", "29.0–30.7", "<b>Search types UNTR</b>, list filters to one post.", "continuous"),
    (14, "SWING · THREAD", "30.7–34.0", "<b>Thread opens as the kick returns</b> (music break 30.7 to 32.2); punch into the triple-bottom chart.", "line"),
    (15, "BRIEF · GLOBAL", "34.0–37.0", "<b>Tiles count up</b> to real 30 Sep closes. segera hadir chip.", "morph"),
    (16, "BRIEF · OVERNIGHT", "37.0–40.0", "<b>Card morphs</b> into the overnight story; one line at a time.", "morph"),
    (17, "BRIEF · SENTIMENT", "40.0–43.0", "<b>Two real X takes</b> drop in; the balance tips toward hati-hati.", "morph"),
    (18, "BRIEF · IHSG", "43.0–46.0", "<b>Real ^JKSE candles draw</b>, then support and resistance; verdict ticks and lands.", "morph"),
    (19, "MAU · MALEM", "46.0–48.5", "<b>One page, four quadrants.</b> Brief shrinks into the top-left quadrant; the other three stay muted. Cursor flips the night toggle; BISA stamps.", "morph"),
    (20, "MAU · SUMBER", "48.5–51.0", "<b>Top-right lights up</b>, top-left mutes but keeps its BISA. New source row drops in and checks.", "morph"),
    (21, "MAU · JAM", "51.0–53.5", "<b>Bottom-left lights up.</b> 08.00 rolls to 06.30. BISA.", "morph"),
    (22, "MAU · MINGGUAN", "53.5–56.0", "<b>Bottom-right lights up.</b> Segment slides to Mingguan. BISA. Seam: the page collapses into the copper line.", "line"),
    (23, "CLOSE", "56.0–60.0", "<b>Words rise</b>, the line folds into the B, lockup and URL. Held to the last frame.", "end"),
]

CSS = (ROOT / "tools/storyboard_sheet.css").read_text() + S.CSS


def build():
    cells = []
    for n, name, t, note, seam in META:
        cells.append(
            f'<section class="cell" id="frame-{n:02d}"><div class="f">{F[n]}</div>'
            f'<div class="lab"><span>{n:02d} · {name}</span><span>frame-{n:02d} · {t}s</span></div>'
            f'<p class="note">{note}</p><span class="seam">{seam}</span></section>')
    seams = "".join(f'<span class="s"><b>{n:02d}</b>{seam}</span>' for n, _, _, _, seam in META)
    cells.append(f'<section class="cell meta"><div class="f flat"><div class="seammap">{seams}</div></div>'
                 '<div class="lab"><span>SEAM MAP</span><span>copper line leads every seam</span></div></section>')
    cells.append('<section class="cell meta"><div class="f flat"><div class="tokens">'
                 '<div class="sw" style="background:#111311">ground #111311</div>'
                 '<div class="sw" style="background:#1C1F1D">raised #1C1F1D</div>'
                 '<div class="sw cu" style="background:#DEA777;color:#111311">copper #DEA777</div>'
                 '<div class="sw" style="background:#000">discord #000</div>'
                 '<p class="t1">Hanken Grotesk 900</p><p class="t2">Hanken Grotesk 500, the narrator</p>'
                 '<p class="t3">Figtree, Discord UI stand-in</p>'
                 '<p class="bans">No gradients across the ground · no glow on text · no particle bursts · no fake Bursawatch UI · one focal point</p>'
                 '</div></div><div class="lab"><span>TOKENS</span><span>frame.md</span></div></section>')
    html = f'''<!doctype html><html lang="id"><head><meta charset="utf-8">
<title>Bursawatch launch film, storyboard {VERSION}</title><style>{CSS}</style></head><body>
<header><h1>Bursawatch launch film <span class="ver">{VERSION}</span></h1>
<p class="dek">Info saham yang cepat dan bisa dipercaya, semuanya langsung di Discord kamu, dan kamu yang atur.</p>
<p class="spec">1920×1080 · 60fps · 60s · 23 frames · music: suno-v1, 120 BPM, drop 16.2s</p></header>
<main class="grid">{"".join(cells)}</main></body></html>'''
    (ROOT / "storyboard.html").write_text(html)
    print("wrote storyboard.html")


if __name__ == "__main__":
    build()


def single(n, out):
    """Write one frame at 1920 wide for close inspection."""
    html = (f'<!doctype html><html><head><meta charset="utf-8"><base href="file://{ROOT}/"><style>{CSS}'
            'body{padding:0;margin:0;background:#000}.cell .f{border-radius:0;outline:0}</style></head>'
            f'<body><section class="cell" style="width:1920px"><div class="f">{F[n]}</div></section></body></html>')
    Path(out).write_text(html)
