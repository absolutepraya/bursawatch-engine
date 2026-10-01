"""Realistic dark-mode social post components for the storyboard sheet.

Built from the user's X screenshot (current X dark UI) and the platforms'
own dark themes. Sizes take a px() function so they scale with the frame.
Engagement counts are illustrative; post text comes from the real Bursawatch
source messages unless a component is marked fictional.
"""

E = "assets/sources/emoji"

ICON = {
    "reply": '<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/>',
    "repost": '<path d="M7 7h10l-2-2M17 17H7l2 2M5 9v6M19 9v6"/>',
    "like": '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
    "views": '<path d="M5 20V12M10 20V6M15 20v-9M20 20V9"/>',
    "share": '<path d="M12 4v11M7 9l5-5 5 5M5 20h14"/>',
    "eye": '<path d="M2 12s4-6 10-6 10 6 10 6-4 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/>',
    "up": '<path d="M12 5l6 8h-4v6h-4v-6H6z"/>',
    "comment": '<path d="M4 5h16v11H9l-5 4z"/>',
    "more": '<circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/>',
}


def icon(name, px, size=18, fill=False):
    style = "fill:currentColor;stroke:none" if fill or name == "more" else "fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round"
    return (f'<svg viewBox="0 0 24 24" style="width:{px(size)};height:{px(size)};{style}">{ICON[name]}</svg>')


def av(src, size, px, badge=None, blur=False):
    b = (f'<img class="badge" src="{E}/{badge}.png" style="width:{px(size * .42)};height:{px(size * .42)}">'
         if badge else "")
    f = "filter:blur(.35cqw);" if blur else ""
    return (f'<span class="av" style="width:{px(size)};height:{px(size)}">'
            f'<img src="{src}" style="border-radius:50%;{f}">{b}</span>')


def hl(text, words):
    for w in words:
        text = text.replace(w, f'<mark>{w}</mark>', 1)
    return text


def x_post(px, name, handle, when, text, counts, media=None, w=520, marks=(), blur_id=False, badge="twitter", avatar=None):
    blur = ' class="blurid"' if blur_id else ""
    media_html = f'<div class="xmedia">{media}</div>' if media else ""
    r, rp, lk, vw = counts
    return (f'<div class="sp x" style="width:{px(w)}">'
            f'<div class="xh">{av(avatar, 44, px, badge, blur_id)}<div class="xid"><b{blur}>{name}</b>'
            f'<span{blur}>{handle}</span><span>· {when}</span></div>'
            f'<span class="xlogo"><img src="{E}/twitter.png"></span></div>'
            f'<div class="xt">{hl(text, marks)}</div>{media_html}'
            f'<div class="xa"><span>{icon("reply", px)}{r}</span><span>{icon("repost", px)}{rp}</span>'
            f'<span>{icon("like", px)}{lk}</span><span>{icon("views", px)}{vw}</span><span>{icon("share", px)}</span></div></div>')


def tg_post(px, channel, avatar, text, views, when, w=500, marks=(), sub="channel"):
    return (f'<div class="sp tg" style="width:{px(w)}">'
            f'<div class="tgh">{av(avatar, 40, px)}<div><b>{channel}</b><span>{sub}</span></div>'
            f'<span class="tglogo"><img src="{E}/telegram.png"></span></div>'
            f'<div class="tgb"><div class="tgn">{channel}</div><div class="tgt">{hl(text, marks)}</div>'
            f'<div class="tgm">{icon("eye", px, 15)} {views} &nbsp;{when}</div></div></div>')


def wa_post(px, channel, avatar, text, when, reacts, w=500, marks=()):
    return (f'<div class="sp wa" style="width:{px(w)}">'
            f'<div class="wah">{av(avatar, 40, px)}<div><b>{channel}</b><span>Saluran</span></div>'
            f'<span class="walogo">WA</span></div>'
            f'<div class="wab"><div class="wat">{hl(text, marks)}</div><div class="wam">{when}</div></div>'
            f'<div class="war">👍 🔥 {reacts}</div></div>')


def ig_post(px, img, caption, when, w=300):
    return (f'<div class="sp ig" style="width:{px(w)}">'
            f'<div class="igh2">{av(E + "/instagram.png", 32, px)}<span class="bar2"></span>'
            f'<span class="igw">{when}</span></div>'
            f'<img class="igp" src="{img}"><div class="igc">{caption}</div></div>')


def sb_post(px, title, text, when, w=500, marks=()):
    return (f'<div class="sp sb" style="width:{px(w)}">'
            f'<div class="sbh">{av(E + "/stockbit.png", 40, px)}<div><b>Stockbit Snips</b><span>{when}</span></div></div>'
            f'<div class="sbtitle">{title}</div><div class="sbt">{hl(text, marks)}</div>'
            f'<div class="xa"><span>{icon("like", px)}212</span><span>{icon("comment", px)}38</span>'
            f'<span>{icon("share", px)}</span></div></div>')


CSS = """
/* realistic social posts (dark themes) */
.sp { position: absolute; border-radius: .8cqw; font-family: "Figtree"; overflow: hidden; box-shadow: 0 1.2cqw 2.6cqw rgba(0,0,0,.5); }
.sp mark { background: rgba(222,167,119,.28); color: inherit; border-radius: .2cqw; padding: 0 .15cqw; }
.sp .av .badge { outline-color: #000; }
.x { background: #000; border: .1cqw solid #2F3336; padding: 1.1cqw 1.2cqw .9cqw; color: #E7E9EA; }
.xh { display: flex; align-items: center; gap: .7cqw; }
.xid { display: flex; flex-wrap: wrap; align-items: baseline; gap: .35cqw; font-size: 1.05cqw; color: #71767B; line-height: 1.2; }
.xid b { color: #E7E9EA; font-weight: 800; }
.blurid { filter: blur(.32cqw); }
.xlogo { margin-left: auto; opacity: .9; }
.xlogo img, .tglogo img { width: 1.4cqw; height: 1.4cqw; border-radius: .3cqw; }
.xt { font-size: 1.22cqw; line-height: 1.38; margin-top: .6cqw; white-space: pre-line; }
.xmedia { margin-top: .7cqw; border-radius: .7cqw; overflow: hidden; border: .1cqw solid #2F3336; }
.xmedia img, .xmedia svg { display: block; width: 100%; }
.xa { display: flex; justify-content: space-between; margin-top: .8cqw; color: #71767B; font-size: .9cqw; }
.xa span { display: flex; align-items: center; gap: .3cqw; }
.tg { background: #0E1621; border: .1cqw solid #1c2733; color: #F5F5F5; }
.tgh { display: flex; align-items: center; gap: .7cqw; padding: .8cqw 1cqw; background: #17212B; font-size: 1.05cqw; }
.tgh b { display: block; } .tgh span { color: #6D7F8F; font-size: .85cqw; }
.tglogo { margin-left: auto; }
.tgb { margin: .8cqw 1cqw 1cqw; background: #182533; border-radius: .8cqw; padding: .8cqw 1cqw; }
.tgn { color: #6AB2F2; font-weight: 700; font-size: .95cqw; }
.tgt { font-size: 1.1cqw; line-height: 1.4; margin-top: .3cqw; white-space: pre-line; }
.tgm { display: flex; align-items: center; justify-content: flex-end; gap: .3cqw; color: #6D7F8F; font-size: .8cqw; margin-top: .4cqw; }
.wa { background: #0B141A; border: .1cqw solid #1f2c33; color: #E9EDEF; }
.wah { display: flex; align-items: center; gap: .7cqw; padding: .8cqw 1cqw; background: #202C33; font-size: 1.05cqw; }
.wah b { display: block; } .wah span { color: #8696A0; font-size: .85cqw; }
.walogo { margin-left: auto; background: #25D366; color: #0B141A; font-weight: 800; font-size: .75cqw; border-radius: 99px; padding: .15cqw .5cqw; }
.wab { margin: .8cqw 1cqw .4cqw; background: #202C33; border-radius: .7cqw; padding: .8cqw 1cqw; }
.wat { font-size: 1.1cqw; line-height: 1.4; white-space: pre-line; }
.wam { text-align: right; color: #8696A0; font-size: .8cqw; margin-top: .3cqw; }
.war { margin: 0 1cqw .9cqw; font-size: .9cqw; color: #8696A0; }
.ig { background: #000; border: .1cqw solid #262626; color: #F5F5F5; }
.igh2 { display: flex; align-items: center; gap: .6cqw; padding: .6cqw .8cqw; }
.bar2 { display: block; width: 6cqw; height: .6cqw; border-radius: 99px; background: #363636; }
.igw { margin-left: auto; color: #A8A8A8; font-size: .8cqw; }
.igp { display: block; width: 100%; aspect-ratio: 4/5; object-fit: cover; }
.igc { font-size: .9cqw; padding: .6cqw .8cqw .8cqw; color: #DADADA; }
.sb { background: #121212; border: .1cqw solid #262626; padding: 1cqw 1.2cqw .9cqw; color: #EDEDED; }
.sbh { display: flex; align-items: center; gap: .7cqw; font-size: 1.05cqw; }
.sbh b { display: block; } .sbh span { color: #8A8A8A; font-size: .85cqw; }
.sbtitle { font-weight: 800; font-size: 1.25cqw; margin-top: .7cqw; }
.sbt { font-size: 1.05cqw; line-height: 1.4; color: #C8C8C8; margin-top: .3cqw; }
.wallbg .sp.dim { opacity: .32; }
.headline-xl { position: absolute; left: 50%; top: 50%; transform: translate(-50%,-50%); text-align: center; white-space: nowrap; font-family: "Hanken Grotesk"; font-weight: 600; font-size: 5.6cqw; line-height: 1.12; letter-spacing: -0.035em; color: var(--text); }
.headline-xl .mark { padding: 0 .6cqw; border-radius: .5cqw; }

/* config page: four quadrants, one active */
.quad { position: absolute; width: 50cqw; height: 28.125cqw; }
.quad.muted { opacity: .26; filter: saturate(.2); }
.qline { position: absolute; background: var(--hair); }
.quad .qq { position: absolute; left: 50%; top: 4.4cqw; transform: translateX(-50%); white-space: nowrap; font-family: "Hanken Grotesk"; font-weight: 600; font-size: 2.15cqw; letter-spacing: -0.02em; }
.quad .qc { position: absolute; left: 50%; top: 10cqw; transform: translateX(-50%); width: 32cqw; background: var(--raised); border: .12cqw solid #2c302d; border-radius: 1cqw; padding: 1.2cqw; font-family: "Figtree"; box-shadow: 0 1.4cqw 3cqw rgba(0,0,0,.45); }
.quad .row { font-size: 1.55cqw; padding: .9cqw .3cqw; }
.quad .tog { width: 3.6cqw; height: 2cqw; } .quad .tog i { width: 1.5cqw; height: 1.5cqw; top: .25cqw; left: .25cqw; } .quad .tog.on i { left: 1.85cqw; }
.quad .time .new { font-size: 4.6cqw; } .quad .time .old { font-size: 2.4cqw; }
.quad .seg { font-size: 1.8cqw; } .quad .tl { font-size: 1.25cqw; }
.quad .qbisa { position: absolute; right: 3.4cqw; bottom: 2.4cqw; font-family: "Hanken Grotesk"; font-weight: 900; font-size: 4.4cqw; letter-spacing: -0.04em; color: var(--cu); transform: rotate(-6deg); }
.ghostrow { color: var(--hint); } .plus { width: 2cqw; height: 2cqw; border-radius: 50%; border: .12cqw dashed var(--hint); display: inline-flex; align-items: center; justify-content: center; font-size: 1.3cqw; }
"""
