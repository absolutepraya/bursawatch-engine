---
format: 1920x1080
fps: 60
duration: 60s
message: "Info saham yang cepat dan bisa dipercaya, semuanya langsung di Discord kamu, dan kamu yang atur."
arc: Pain (4 bad sources) → Everywhere → Doubt → Bursawatch → Proof (channels, swing board, morning brief) → Control → Logo
audience: Indonesian retail stock investors and traders (IHSG)
mode: collaborative
version: v1
---

# Bursawatch launch film, storyboard v1

## Decisions

- **Message:** Info saham yang cepat dan bisa dipercaya, semuanya langsung di Discord kamu, dan kamu yang atur.
- **Audience and arc:** Indonesian retail investors. Pain → everywhere → doubt → Bursawatch → proof → control → logo.
- **Format:** 1920x1080, 60fps, 60s, no voiceover, music bed (user's Suno track, ~118 BPM) plus SFX. Times below are provisional until the beat grid is measured; the logo lockup lands on the drop.
- **Spine:** the copper signal line. The B mark's horizontal inlets become a thin copper line that leads every seam (ref 4's collapse-to-line transition): sources flow in along it, scenes collapse into it and expand out of it.
- **Brand:** frame.md (ground #111311, copper #DEA777, Hanken Grotesk / Geist Mono / Figtree for Discord).
- **Bans:** no gradients across the ground, no glow on text, no particle bursts, no everything-fades-in, no fake Bursawatch UI, one focal point per frame. Motion failures to avoid: the slideshow (every beat a fresh card; we keep one continuous stage per scene) and the screensaver (ambient motion that says nothing).
- **Held frame:** 09 lockup holds still (only a slow push) for ~1.5s after the drop.
- **Truthfulness:** Discord messages, source names, logos, prices, charts, and macro numbers are real (#id-stocks-news, #macro-news, #id-industry-news, #id-stocks-swing, 16 Sep to 1 Oct 2026). Pain-point cards (02 to 05) are fictional, unbranded examples. The morning brief (15 to 18) and customization (19 to 22) are upcoming features, shown as previews built from real data and labeled "segera hadir".

## Frame 1 — Hook

- scene: Ground, faint copper glow. Mono line rises word by word: "Nyari info saham yang cepet dan bener," then "di mana sih?"
- duration: 2.8s
- start: 0.00
- transition_in: cut
- status: outline
- src: compositions/s1-pains.html
- poster: 2.4
- blueprint: kinetic-type-beats (Hook)
- rules: ref1 word mask rise (5 to 7 frames per word, speech cadence)
- audio: intro, hi-hat ticks; soft tick per word
- constraint: no logo, no product yet

The viewer's own question, in their own words. "cepet" and "bener" in copper.

## Frame 2 — Pain: IG

- scene: Fictional IG post card slides in from left (avatar dummy face + IG badge, "BREAKING: saham XXXX terbang!", stamp "3 jam lalu", mini chart already +25%). Right: "Berita IG?" then "Udah telat."
- duration: 1.5s
- start: 2.80
- transition_in: hook line lifts to top-left kicker
- status: outline
- src: compositions/s1-pains.html
- blueprint: kinetic-type-beats (Problem)
- rules: ref1 card entry (12 frames, horizontal motion blur), motion-blur-streak
- audio: whoosh peak on card travel, tick on answer

## Frame 3 — Pain: Telegram

- scene: Telegram channel card "VIP INSIDER A1, Rp1,5 jt/bulan" slides in, pushing the IG card back. Right: "Grup 'insider A1'?" then "Boncos."
- duration: 1.5s
- start: 4.30
- status: outline
- src: compositions/s1-pains.html
- rules: ref1 card entry, previous card scales to 0.92 and dims (accumulation)

## Frame 4 — Pain: Kelas

- scene: Class promo card "Kelas Saham Pasti Cuan" slides in. Right: "Kelas sana-sini?" then "Teori sama market-nya beda."
- duration: 1.5s
- start: 5.80
- status: outline
- src: compositions/s1-pains.html

## Frame 5 — Pain: X

- scene: X stockpick card (dummy account, X badge, "Target 2x minggu ini") slides in; its chart flips red. Right: "Stockpick di X?" then "Rungkad."
- duration: 1.5s
- start: 7.30
- status: outline
- src: compositions/s1-pains.html
- audio: low thud on "Rungkad."

## Frame 6 — Everywhere

- scene: Real Bursawatch source cards (Tuntun, Phintraco, BRI Danareksa, Samuel, Stockbit, X analysts with X badge, IG with IG badge, WhatsApp channel) pour in from the left in two bands; centre band holds the mono headline "Infonya ada di mana-mana." with a copper marker sweeping behind "di mana-mana".
- duration: 3.2s
- start: 8.80
- transition_in: pain cards join the wall (continuous stage)
- status: outline
- src: compositions/s2-wall-logo.html
- poster: 2.8
- blueprint: grid-card-assemble (Problem, logo-wall variant)
- rules: ref1 card entry, css-marker-patterns (ref1 sweep ~16 frames), motion-blur-streak
- audio: build section; whooshes thin out into a texture

## Frame 7 — Doubt

- scene: Wall ghosts to ~15% and blurs. "Tapi mana yang bener?" rises word by word, centred.
- duration: 2.0s
- start: 12.00
- status: outline
- src: compositions/s2-wall-logo.html
- rules: depth-of-field-blur (wall), ref1 word rise
- audio: riser into the drop

## Frame 8 — Absorb

- scene: Small mono label "Kenalin," above centre. Ghosted cards sharpen and stream right along three copper lines into the three inlets of the B; each inlet fills as cards arrive, building the mark.
- duration: 2.0s
- start: 14.00
- status: outline
- src: compositions/s2-wall-logo.html
- blueprint: logo-assemble-lockup (Product_Intro, built from parts)
- rules: svg-path-draw (mark fill), motion-blur-streak
- audio: riser peaks at the last inlet

## Frame 9 — Lockup

- scene: Drop. B mark + "Bursawatch" wordmark rise; subline (mono) "Semua info saham penting, langsung ke Discord kamu." Copper ripple rings expand from the mark. Held frame with slow push.
- duration: 3.5s
- start: 16.00
- status: outline
- src: compositions/s2-wall-logo.html
- poster: 2.0
- blueprint: logo-assemble-lockup + kinetic-type-beats (Product_Intro "Introducing")
- rules: ref1 lockup order (label, mark, words), center-outward-expansion (rings)
- audio: DROP on the mark; impact

## Frame 10 — Channels burst

- scene: Bursawatch circle avatar pops centre with overshoot; five category chips launch from behind it and park around it, each with a real source logo: "Trading ideas", "Aksi korporasi", "Makro", "Komoditas", "Industri & regulasi". Caption rail: "udah dipilah. dari sumber kredibel."
- duration: 3.5s
- start: 19.50
- transition_in: zoom-through from lockup
- status: outline
- src: compositions/s3-burst-proof.html
- poster: 3.0
- blueprint: constellation-hub (nodes spring around a center)
- rules: spring-pop-entrance, ref3 chip launch (rotation, ~13 frame stagger, center squash)
- audio: pop per chip on the beat

## Frame 11 — Proof

- scene: Zoom through the centre into a real Discord channel: Bursawatch bot messages stack in (Tuntun TRUK VTO with price block, BRI Danareksa HRTA with photo, IHSG Journal on X with X badge). Discord ping on each arrival. Caption: "dipantau 24 jam. dirangkum AI."
- duration: 3.0s
- start: 23.00
- status: outline
- src: compositions/s3-burst-proof.html
- blueprint: device-surface-showcase (cursorless stepwise flow)
- rules: waterfall-entry (messages), ref4 caption typing
- audio: Discord-style ping per message

## Frame 12 — Swing board scroll

- scene: Discord forum "#swing-board": posts with tags (Primary plan, Below entry, Resolved, Entry zone) scroll fast: PACK, BIPI, HRTA, INDF, JARR, with chart thumbnails. Caption: "swing board. semua trading ideas, satu tempat."
- duration: 3.0s
- start: 26.00
- transition_in: copper line wipe
- status: outline
- src: compositions/s4-swing.html
- blueprint: transcript-scroll-artifact-reveal
- rules: 3d-page-scroll (flat variant)

## Frame 13 — Swing board search

- scene: Scroll decelerates; search bar types "UNTR"; list filters to UNTR posts.
- duration: 2.5s
- start: 29.00
- status: outline
- src: compositions/s4-swing.html
- blueprint: prompt-type-submit-generate (query → instant result surface)
- rules: discrete-text-sequence (typing), context-sensitive-cursor
- audio: key ticks per character

## Frame 14 — Swing board thread

- scene: UNTR thread opens: DokterMarket (X badge) "UNTR: Pola Triple Bottom Beri Peluang Penguatan" with its real chart, then BRI Danareksa "UNTR: Dividen Interim, Buyback, dan Kenaikan RKAB Jadi Katalis", then Tuntun "UNTR: RKAB batu bara 2026 direvisi naik menjadi 12,4 juta ton" with price block. Caption: "cek siapa aja yang udah bahas sahammu."
- duration: 2.5s
- start: 31.50
- status: outline
- src: compositions/s4-swing.html
- poster: 2.0
- rules: waterfall-entry, coordinate-target-zoom (punch to chart)

## Frame 15 — Brief: global

- scene: Caption types "08.00 WIB. morning brief." with a "segera hadir" chip. Index tiles count up (real closes, 30 Sep 2026, Yahoo Finance): NASDAQ +0,24%, NIKKEI +1,94%, KOSPI -0,48%.
- duration: 3.0s
- start: 34.00
- transition_in: copper line collapse and expand
- status: outline
- src: compositions/s5-brief.html
- blueprint: dataviz-countup
- rules: counting-dynamic-scale, ref4 caption typing

## Frame 16 — Brief: overnight

- scene: "Semalam" card: "Inflasi AS melandai, peluang The Fed naikin bunga turun ke 37%." Second line: "Brent masih di atas US$100, Selat Hormuz masih panas."
- duration: 3.0s
- start: 37.00
- status: outline
- src: compositions/s5-brief.html
- rules: card-morph-anchor

## Frame 17 — Brief: sentiment

- scene: Two real X takes (with X badges): IHSG Journal "IHSG masih lemah, belum ada sinyal pembalikan" (hati-hati) and "IHSG dinilai mulai terbebas dari tekanan MSCI" (optimis). A balance bar tips toward hati-hati. Label "Kata trader di X".
- duration: 3.0s
- start: 40.00
- status: outline
- src: compositions/s5-brief.html
- rules: stat-bars-and-fills

## Frame 18 — Brief: IHSG

- scene: IHSG daily candles draw in (real ^JKSE history); dashed resistance 6.257 and support 6.071 draw across, downside 5.825 faint. Verdict chip cycles Hijau / Merah / Sideways and lands "Sideways, rawan turun."
- duration: 3.0s
- start: 43.00
- status: outline
- src: compositions/s5-brief.html
- poster: 2.5
- blueprint: dataviz-countup (chart hit)
- rules: svg-path-draw, vertical-spring-ticker (verdict)
- audio: soft hit when the verdict lands

## Frame 19 — Mau: malem

- scene: Ref 2 stage. Headline "Mau dirangkum tiap malem aja?" Card morphs from the brief into a schedule card; cursor flips "Ringkasan malam, 21.00" on. "BISA." stamps in copper.
- duration: 2.5s
- start: 46.00
- transition_in: card-morph (brief chart shrinks into the card)
- status: outline
- src: compositions/s6-config.html
- blueprint: fixed-anchor-cycle (in-place morphs) + cursor-ui-demo
- rules: card-morph-anchor, press-release-spring, cursor-click-ripple
- audio: breakdown; click on toggle, stamp hit on BISA

## Frame 20 — Mau: sumber

- scene: "Mau mantau analis favoritmu sendiri?" Card morphs into a source list; a new row "+ @analis_pilihanmu" (dummy face, X badge) drops in and checks. "BISA."
- duration: 2.5s
- start: 48.50
- status: outline
- src: compositions/s6-config.html

## Frame 21 — Mau: jam

- scene: "Mau ganti jam kirimnya?" Card morphs into a time picker; 08.00 rolls to 06.30. "BISA."
- duration: 2.5s
- start: 51.00
- status: outline
- src: compositions/s6-config.html
- rules: vertical-spring-ticker

## Frame 22 — Mau: mingguan

- scene: "Males baca tiap hari?" Segmented control Harian / Mingguan slides to Mingguan; subline "Seminggu sekali aja." "BISA."
- duration: 2.5s
- start: 53.50
- status: outline
- src: compositions/s6-config.html

## Frame 23 — Close

- scene: Card collapses into the copper line. "Infonya, dan cara nyarinya," then "kamu yang atur." rise word by word; then the line folds into the B mark, wordmark lockup, URL "bursawatch.abhipraya.dev" in mono below. Held to the last frame.
- duration: 4.0s
- start: 56.00
- status: outline
- src: compositions/s7-close.html
- poster: 3.5
- blueprint: kinetic-type-beats (CTA) → logo-assemble-lockup
- rules: ref1 word rise, center-outward-expansion (one ring)
- audio: final groove resolves; impact on the mark, tail out
