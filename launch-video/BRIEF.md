---
workflow: general-video
flow: companion
storyboard: yes
message: "Info saham yang cepat dan bisa dipercaya, semuanya langsung di Discord kamu, dan kamu yang atur."
destination: youtube
aspect: 1920x1080
language: id
audience: Indonesian retail stock investors and traders (IHSG)
length: 60s
angle: problem-to-product launch, text-only kinetic typography over real product shots
narration: no
---

## Intent

A 60-second 16:9 launch film for Bursawatch, built from the user's script
(`/Users/absolutepraya/Downloads/demo-generation/1 MIN VIDEO SCRIPT.md`) and
condensed into on-screen text. No voiceover. All copy is casual, everyday
Indonesian (bahasa sehari-hari, not formal), natural and easy to read.

Story: finding fast and trustworthy stock info is painful (late IG news,
Telegram "insider" tickets, classes that don't match the market, X
stockpicks that go rungkad). The info is everywhere, but which is right?
Bursawatch watches the sources and delivers everything to Discord, split by
channel, plus a swing board, an upcoming morning brief, and full
customization. Close: "Infonya, dan cara nyarinya, kamu yang atur."

Dark mode throughout, on the approved Signal Fold identity (near-black with a
single copper accent). Music bed in the style of references 1, 2, and 4
(minimal, confident electronic, ~118 BPM), not reference 3's arcade feel.

## Beat sheet (agreed)

| Time | Beat | Reference |
|---|---|---|
| 0:00 to 0:08 | Hook "Nyari info saham yang cepet *dan* bener, di mana sih?" + 4 pain points (IG telat, Telegram tiket A1, kelas vs realita, X stockpick rungkad) | 1 / 2 |
| 0:08 to 0:14 | Wall of real source cards: "Infonya ada di mana-mana." then "Tapi mana yang bener?" | 1 |
| 0:14 to 0:20 | Cards stream into the B mark's three inlets, logo forms, "Kenalin," + Bursawatch + "dipantau 24 jam, disaring AI" | 1 |
| 0:20 to 0:26 | Channel chips burst from the bouncing center object, real messages behind | 3 |
| 0:26 to 0:34 | Swing board: forum scroll, search types `UNTR`, thread shows Phintraco plan, BRI Danareksa view, DokterMarket X chart | 4 |
| 0:34 to 0:46 | Morning brief (labeled "segera hadir"): global indices, overnight event (real Hormuz / Brent US$106 story), trader sentiment, IHSG chart with support and resistance, verdict | 4 |
| 0:46 to 0:56 | Customization, one morphing card, four "Mau ...? BISA." | 2 |
| 0:56 to 1:00 | "Infonya, dan cara nyarinya, kamu yang atur." + logo + bursawatch.abhipraya.dev | 1 |

Cut timing is final only after the music track's beat grid is measured; the
logo reveal lands on the drop.

## Assets

- assets/brand/bursawatch.svg — Signal Fold mark (vector), animate for the logo reveal.
- assets/brand/cropped_circle.png — circle avatar, the Discord bot avatar on message recreations.
- assets/brand/bot-avatar.png — live Discord bot avatar.
- assets/sources/emoji/ — real Discord custom emojis: source logos (tuntun, phintraco, bridanareksa, stockbit, kelasinvestasi), X account avatars, platform icons, price dots.
- assets/sources/web/samuel-icon.png — Samuel Sekuritas logo (from samuel.co.id; no Discord emoji exists).
- assets/discord-ref/ — user's Discord screenshots: swing board, Tuntun news with price, Phintraco trading buy, DokterMarket X chart, BBNI on support, BRI news with image, BRI chart sentiment.
- assets/discord-media/ — 104 real chart and news images pulled from the channels.
- research/h-*.json — raw message exports from #id-stocks-news, #macro-news, #id-industry-news, #id-stocks-swing.
- /Users/absolutepraya/Downloads/demo-generation/reference/reference-{1..4}.mp4 — motion references.
- /Users/absolutepraya/Downloads/demo-generation/guides/guide for main workflow.md — the user's motion workflow (reference frame study, locked visual rules, stills before render, fresh critic, sound sync, -14 LUFS).

## Customizations

- Reference remake: frame-study the used sections of refs 1 to 4 into research/SPEC.md before building; keep their timing, easing, and staging, change brand, copy, and product.
- Real Discord product shots rebuilt in HTML from the real message data (crisp at punch-in), real broker and analyst names and logos.
- X-sourced avatars get a small X badge bottom-right; Instagram sources use dummy AI faces with an IG badge bottom-right.
- Every news card shows the Tuntun-style price block: "Harga terakhir (IDR)" + 1D / 1W / 1M / 3M with green/red dots (even for sources where production lacks it).
- Music: user generates with Suno (instrumental, ~118 BPM, clear intro/build/drop/groove/breakdown/outro). Beat-grid analysis drives cuts; edits at bar lines if needed.
- SFX layer placed per frame (click on press, whoosh peak on fastest frame, impacts on logo and BISA stamps, ticks on typing). Master around -14 LUFS.
- Five key stills reviewed before the full build; a separate fresh critic pass after the build.

## Notes

- Banned: random gradients, everything fading in, fake-looking product UI, particle bursts, glow on text, more than one focal point per frame.
- Motion rules (from the user's guide): arrive fast and land soft (12 to 19% of remaining distance per frame), holds keep a slow push, moves at least 0.3s (big moves 0.5 to 0.75s), stagger groups 2 to 4 frames, motion blur follows direction, text holds 8+ frames before moving, cuts on the beat or 2 frames early.
- Long Discord paragraphs are texture and proof; only title, source, and price block need to be readable. Our headline copy carries the story.
- Morning brief is not built yet (hackathon design notes); show it as an upcoming feature. Drop sector rotation.
- web-config and web-landing are stale; do not treat their components as truth.
- No em dashes in any on-screen copy.
