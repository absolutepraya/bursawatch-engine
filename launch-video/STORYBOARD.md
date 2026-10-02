---
format: 1920x1080
fps: 60
duration: 60s
message: "Info saham yang cepat dan bisa dipercaya, semuanya langsung di Discord kamu, dan kamu yang atur."
arc: Pain (4 bad sources) → Everywhere → Doubt → Bursawatch → Proof (channels, swing board, morning brief) → Control → Logo
audience: Indonesian retail stock investors and traders (IHSG)
mode: collaborative
version: v3-build
---

# Bursawatch launch film, storyboard v2

## Locked

Layout confirmed by the user on 2026-10-01 (storyboard v2). Built in compositions/ from scenes-src/ via tools/build_scenes.py.

## Changes from feedback round 2 (wall and logo)

- Wall: 11 cards from 11 different accounts, no repeats; IHSG Journal removed. Real posts from the user's screenshots: Milo (@eskepalmilosatu, $ESSA dump screener), SIVENNN (@SIVENNN5s, $DEWI chart with quote), Samuel Sekuritas (WIFI, classic WhatsApp), BRI Danareksa (Daily Trade, classic WhatsApp), Phintraco Sekuritas Official (Telegram desktop with pinned bar). Plus DokterMarket, The Kobeissi Letter, Tuntun, Kelas Investasi, Stockbit Snips, and one IG feed post.
- Logo: the mark replaces the B ([B]ursawatch), "ursawatch" sized to the mark's cap height, lockup centred on the frame; on the drop three glowing sonar pings, range rings, and one radar sweep (visual only; sound stays the existing impact). Same lockup and sonar in the closing scene.

## Changes from v2 (feedback round 1, pain points)

- Pains run 2.0s each (2.23 to 10.23); hook, wall, doubt, and absorb tightened so the drop stays at 16.22 and the film stays 60s.
- Centred two-column layout; three-level copy per pain (setup, hero, tail) using the user's lines: "Beritanya telat... sahamnya keburu terbang duluan", "Boncos bro, balik modal? Boro-boro...", "Udah mehong, pas praktik ga sesuai yg dipelajari", "Adoh rungkaaddd!! Ga lagi coba-coba".
- IG: real KETR chip (+11,0%, 15 to 28 Sep 2026) with the KETR logo. Telegram: genuine logo and dark mobile UI. Kelas: recreated pricing page (brand and mentor names removed) in a browser window with a pan to Diamond. X: fictional blurred post on $TRUE with real TRUE.JK candles; the post-peak crash (530 to 193) draws on the hero beat.
- New motion: 3D card entrance, depth-of-field stack, hero camera hit, progress bar, scatter exit.

## Changes from v1

- 02 uses the user's real IG posts.
- 05 is our own fictional pump-style X post (style reference: a real tweet, not shown).
- 06 and 07: realistic native-UI posts around the edges, like ref 1.
- 19 to 22: one four-quadrant page; the active quadrant is lit, the rest muted.
- All film text uses Hanken Grotesk, matching web-config.

## Decisions

- **Message:** Info saham yang cepat dan bisa dipercaya, semuanya langsung di Discord kamu, dan kamu yang atur.
- **Audience and arc:** Indonesian retail investors. Pain → everywhere → doubt → Bursawatch → proof → control → logo.
- **Format:** 1920x1080, 60fps, 60s, no voiceover. Music: assets/music/bgm-60.m4a (suno-v1, ~119.7 BPM, two outro bars removed at 54.30s so the natural ending lands at 60s). Every scene start sits on the beat grid; the logo lockup lands on the drop downbeat (16.22s) and the closing mark on the last kick (57.29s). SFX from the HyperFrames bundled Pixabay library, placed by measured peak offset (tools/sfx_plan.py).
- **Spine:** the copper signal line. The B mark's horizontal inlets become a thin copper line that leads every seam (ref 4's collapse-to-line transition): sources flow in along it, scenes collapse into it and expand out of it.
- **Brand:** frame.md (ground #111311, copper #DEA777, Hanken Grotesk for all our text, as web-config; Figtree only inside Discord frames).
- **Bans:** no gradients across the ground, no glow on text, no particle bursts, no everything-fades-in, no fake Bursawatch UI, one focal point per frame. Motion failures to avoid: the slideshow (every beat a fresh card; we keep one continuous stage per scene) and the screensaver (ambient motion that says nothing).
- **Held frame:** 09 lockup holds still (only a slow push) for ~1.5s after the drop.
- **Truthfulness:** Discord messages, source names, logos, prices, charts, and macro numbers are real (#id-stocks-news, #macro-news, #id-industry-news, #id-stocks-swing, 16 Sep to 1 Oct 2026). Pain-point cards (02 to 05) are unbranded: 02 uses user-supplied IG posts with branding removed; 03 to 05 are fictional, with any identity blurred. The morning brief (15 to 18) and customization (19 to 22) are upcoming features, shown as previews built from real data and labeled "segera hadir".

## Frame 1 — Hook

- scene: Ground, faint copper glow. Narrator line rises word by word: "Nyari info saham yang cepet dan bener," then "di mana sih?"
- duration: 2.23s
- start: 0.00
- transition_in: cut
- status: animated
- src: compositions/s1-pains.html
- poster: 2.4
- blueprint: kinetic-type-beats (Hook)
- rules: ref1 word mask rise (5 to 7 frames per word, speech cadence)
- audio: intro, hi-hat ticks; soft tick per word
- constraint: no logo, no product yet

The viewer's own question, in their own words. "cepet" and "bener" in copper.

## Frame 2 — Pain: IG

- scene: Real IG news posts (user-supplied, account branding already removed): KETR post in front with a "3 jam lalu" stamp, ULTJ and BYAN fanned behind. Right: "Berita IG?" then "Udah telat."
- duration: 2.00s
- start: 2.23
- transition_in: hook line lifts to top-left kicker
- status: animated
- src: compositions/s1-pains.html
- blueprint: kinetic-type-beats (Problem)
- rules: ref1 card entry (12 frames, horizontal motion blur), motion-blur-streak
- audio: whoosh peak on card travel, tick on answer

## Frame 3 — Pain: Telegram

- scene: Telegram channel card "VIP INSIDER A1, Rp1,5 jt/bulan" slides in, pushing the IG card back. Right: "Grup 'insider A1'?" then "Boncos."
- duration: 2.00s
- start: 4.23
- status: animated
- src: compositions/s1-pains.html
- rules: ref1 card entry, previous card scales to 0.92 and dims (accumulation)

## Frame 4 — Pain: Kelas

- scene: Class promo card "Kelas Saham Pasti Cuan" slides in. Right: "Kelas sana-sini?" then "Teori sama market-nya beda."
- duration: 2.00s
- start: 6.23
- status: animated
- src: compositions/s1-pains.html

## Frame 5 — Pain: X

- scene: Our own fictional X post in the usual "sirkel" pump style (name, handle, avatar blurred): "Artinya harga $XXXX udah masuk area spekulasi buat jualan di 300 sampai 400. Target akhirnya 610. Ko bisa? Jawabannya ada di Sirkel VIP." Its chart flips red. Right: "Stockpick di X?" then "Rungkad."
- duration: 2.00s
- start: 8.23
- status: animated
- src: compositions/s1-pains.html
- audio: low thud on "Rungkad."

## Frame 6 — Everywhere

- scene: Real source posts rebuilt in their native dark UIs (X, Telegram channel, WhatsApp channel, IG, Stockbit Snips) placed around the edges like ref 1: four across the top, two down each side, four across the bottom, some dimmed for depth. Centre: "Infonya ada / di mana-mana." in large Hanken Grotesk with a copper marker sweeping behind "di mana-mana." Engagement counts are illustrative.
- duration: 3.00s
- start: 10.23
- transition_in: pain cards join the wall (continuous stage)
- status: animated
- src: compositions/s2-wall-logo.html
- poster: 2.8
- blueprint: grid-card-assemble (Problem, logo-wall variant)
- rules: ref1 card entry, css-marker-patterns (ref1 sweep ~16 frames), motion-blur-streak
- audio: build section; whooshes thin out into a texture

## Frame 7 — Doubt

- scene: The same wall ghosts to ~15% and blurs. "Tapi mana / yang bener?" rises word by word, centred.
- duration: 1.50s
- start: 13.23
- status: animated
- src: compositions/s2-wall-logo.html
- rules: depth-of-field-blur (wall), ref1 word rise
- audio: riser into the drop

## Frame 8 — Absorb

- scene: Small label "Kenalin," above centre. Ghosted cards sharpen and stream right along three copper lines into the three inlets of the B; each inlet fills as cards arrive, building the mark.
- duration: 1.49s
- start: 14.73
- status: animated
- src: compositions/s2-wall-logo.html
- blueprint: logo-assemble-lockup (Product_Intro, built from parts)
- rules: svg-path-draw (mark fill), motion-blur-streak
- audio: riser peaks at the last inlet

## Frame 9 — Lockup

- scene: Drop. B mark + "Bursawatch" wordmark rise; subline "Semua info saham penting, langsung ke Discord kamu." Copper ripple rings expand from the mark. Held frame with slow push.
- duration: 3.51s
- start: 16.22
- status: animated
- src: compositions/s2-wall-logo.html
- poster: 2.0
- blueprint: logo-assemble-lockup + kinetic-type-beats (Product_Intro "Introducing")
- rules: ref1 lockup order (label, mark, words), center-outward-expansion (rings)
- audio: DROP on the mark; impact

## Frame 10 — Channels burst

- scene: Bursawatch circle avatar pops centre with overshoot; five category chips launch from behind it and park around it, each with a real source logo: "Trading ideas", "Aksi korporasi", "Makro", "Komoditas", "Industri & regulasi". Caption rail: "udah dipilah. dari sumber kredibel."
- duration: 3.50s
- start: 19.73
- transition_in: zoom-through from lockup
- status: animated
- src: compositions/s3-burst-proof.html
- poster: 3.0
- blueprint: constellation-hub (nodes spring around a center)
- rules: spring-pop-entrance, ref3 chip launch (rotation, ~13 frame stagger, center squash)
- audio: pop per chip on the beat

## Frame 11 — Proof

- scene: Zoom through the centre into a real Discord channel: Bursawatch bot messages stack in (Tuntun TRUK VTO with price block, BRI Danareksa HRTA with photo, IHSG Journal on X with X badge). Discord ping on each arrival. Caption: "dipantau 24 jam. dirangkum AI."
- duration: 3.01s
- start: 23.23
- status: animated
- src: compositions/s3-burst-proof.html
- blueprint: device-surface-showcase (cursorless stepwise flow)
- rules: waterfall-entry (messages), ref4 caption typing
- audio: Discord-style ping per message

## Frame 12 — Swing board scroll

- scene: Discord forum "#swing-board": posts with tags (Primary plan, Below entry, Resolved, Entry zone) scroll fast: PACK, BIPI, HRTA, INDF, JARR, with chart thumbnails. Caption: "swing board. semua trading ideas, satu tempat."
- duration: 2.50s
- start: 26.24
- transition_in: copper line wipe
- status: animated
- src: compositions/s4-swing.html
- blueprint: transcript-scroll-artifact-reveal
- rules: 3d-page-scroll (flat variant)

## Frame 13 — Swing board search

- scene: Scroll decelerates; search bar types "UNTR"; list filters to UNTR posts.
- duration: 2.00s
- start: 28.74
- status: animated
- src: compositions/s4-swing.html
- blueprint: prompt-type-submit-generate (query → instant result surface)
- rules: discrete-text-sequence (typing), context-sensitive-cursor
- audio: key ticks per character

## Frame 14 — Swing board thread

- scene: UNTR thread opens: DokterMarket (X badge) "UNTR: Pola Triple Bottom Beri Peluang Penguatan" with its real chart, then BRI Danareksa "UNTR: Dividen Interim, Buyback, dan Kenaikan RKAB Jadi Katalis", then Tuntun "UNTR: RKAB batu bara 2026 direvisi naik menjadi 12,4 juta ton" with price block. Caption: "cek siapa aja yang udah bahas sahammu."
- duration: 3.53s
- start: 30.74
- status: animated
- src: compositions/s4-swing.html
- poster: 2.0
- rules: waterfall-entry, coordinate-target-zoom (punch to chart)

## Frame 15 — Brief: global

- scene: Caption types "08.00 WIB. morning brief." with a "segera hadir" chip. Index tiles count up (real closes, 30 Sep 2026, Yahoo Finance): NASDAQ +0,24%, NIKKEI +1,94%, KOSPI -0,48%.
- duration: 3.00s
- start: 34.27
- transition_in: copper line collapse and expand
- status: animated
- src: compositions/s5-brief.html
- blueprint: dataviz-countup
- rules: counting-dynamic-scale, ref4 caption typing

## Frame 16 — Brief: overnight

- scene: "Semalam" card: "Inflasi AS melandai, peluang The Fed naikin bunga turun ke 37%." Second line: "Brent masih di atas US$100, Selat Hormuz masih panas."
- duration: 3.00s
- start: 37.27
- status: animated
- src: compositions/s5-brief.html
- rules: card-morph-anchor

## Frame 17 — Brief: sentiment

- scene: Two real X takes (with X badges): IHSG Journal "IHSG masih lemah, belum ada sinyal pembalikan" (hati-hati) and "IHSG dinilai mulai terbebas dari tekanan MSCI" (optimis). A balance bar tips toward hati-hati. Label "Kata trader di X".
- duration: 3.00s
- start: 40.27
- status: animated
- src: compositions/s5-brief.html
- rules: stat-bars-and-fills

## Frame 18 — Brief: IHSG

- scene: IHSG daily candles draw in (real ^JKSE history); dashed resistance 6.257 and support 6.071 draw across, downside 5.825 faint. Verdict chip cycles Hijau / Merah / Sideways and lands "Sideways, rawan turun."
- duration: 3.02s
- start: 43.27
- status: animated
- src: compositions/s5-brief.html
- poster: 2.5
- blueprint: dataviz-countup (chart hit)
- rules: svg-path-draw, vertical-spring-ticker (verdict)
- audio: soft hit when the verdict lands

## Frame 19 — Mau: malem

- scene: One page split into four quadrants (top-left to bottom-right), each with its question and card in its "before" state. The brief shrinks into the top-left quadrant; the other three stay muted. Top-left lights up: "Mau dirangkum tiap malem aja?", cursor flips "Ringkasan malam, 21.00" on, "BISA." stamps.
- duration: 2.01s
- start: 46.29
- transition_in: card-morph (brief chart shrinks into the card)
- status: animated
- src: compositions/s6-config.html
- blueprint: fixed-anchor-cycle (in-place morphs) + cursor-ui-demo
- rules: card-morph-anchor, press-release-spring, cursor-click-ripple
- audio: breakdown; click on toggle, stamp hit on BISA

## Frame 20 — Mau: sumber

- scene: Top-left mutes but keeps its BISA. Top-right lights up: "Mau mantau analis favoritmu?", a new source row "+ analis pilihanmu" (X badge) drops in and checks. "BISA."
- duration: 2.02s
- start: 48.30
- status: animated
- src: compositions/s6-config.html

## Frame 21 — Mau: jam

- scene: Bottom-left lights up: "Mau ganti jam kirimnya?", 08.00 rolls to 06.30. "BISA."
- duration: 2.00s
- start: 50.32
- status: animated
- src: compositions/s6-config.html
- rules: vertical-spring-ticker

## Frame 22 — Mau: mingguan

- scene: Bottom-right lights up: "Males baca tiap hari?", the segment slides from Harian to Mingguan, "Seminggu sekali aja." "BISA." All four now show BISA.
- duration: 2.01s
- start: 52.32
- status: animated
- src: compositions/s6-config.html

## Frame 23 — Close

- scene: Card collapses into the copper line. "Infonya, dan cara nyarinya," then "kamu yang atur." rise word by word; then the line folds into the B mark, wordmark lockup, URL "bursawatch.abhipraya.dev" below. Held to the last frame.
- duration: 5.67s
- start: 54.33
- status: animated
- src: compositions/s7-close.html
- poster: 3.5
- blueprint: kinetic-type-beats (CTA) → logo-assemble-lockup
- rules: ref1 word rise, center-outward-expansion (one ring)
- audio: final groove resolves; impact on the mark, tail out
