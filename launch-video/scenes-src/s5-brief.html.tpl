<!doctype html>
<html>
  <body>
    <template>
      <style>
        @font-face { font-family: "Hanken Grotesk"; src: url(assets/fonts/HankenGrotesk-900.woff2) format("woff2"); font-weight: 100 900; }
        @font-face { font-family: "Figtree"; src: url(assets/fonts/Figtree-700.woff2) format("woff2"); font-weight: 300 900; }
        #root { position: absolute; inset: 0; background: #111311; overflow: hidden; font-family: "Hanken Grotesk", sans-serif; color: #EEEAE3;
          --ground:#111311; --raised:#1C1F1D; --hair:#2A2E2B; --text:#EEEAE3; --muted:#9C978E; --hint:#5F5B55; --cu:#DEA777; --cu2:#F0BE91;
          --dbg:#1A1A1E; --dcard:#242429; --dtext:#DBDEE1; --dmuted:#949BA4; --dlink:#4A9BF5; --blurple:#5865F2; --up:#2EE65F; --down:#F23F43; }
        #s5-box { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; container-type: inline-size; }
        {{DISCORD_CSS}}
        #s5-glow { position: absolute; left: 1300px; top: 540px; width: 1400px; height: 1100px; margin: -550px 0 0 -700px; border-radius: 50%; background: radial-gradient(closest-side, rgba(222,167,119,.12), rgba(222,167,119,0)); }
        #s5-card { position: absolute; left: 780px; top: 100px; width: 1040px; height: 880px; background: #1A1A1E; border: 2px solid #313137; border-radius: 18px; padding: 30px 34px; font-family: "Figtree"; color: #DBDEE1; box-shadow: 0 40px 90px rgba(0,0,0,.6); transform-origin: 50% 50%; overflow: hidden; }
        #s5-title { font-weight: 800; font-size: 46px; margin: 18px 0 0; letter-spacing: -0.01em; }
        .ph { position: absolute; left: 34px; right: 34px; top: 200px; bottom: 34px; }
        .lab { font-family: "Hanken Grotesk"; font-weight: 700; font-size: 24px; letter-spacing: .1em; color: #DEA777; text-transform: uppercase; }
        .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-top: 16px; }
        .tile { background: #242429; border-radius: 16px; padding: 18px 22px 18px; }
        .tn { display: flex; align-items: center; gap: 12px; font-family: "Hanken Grotesk"; font-weight: 700; font-size: 24px; letter-spacing: .04em; color: #DBDEE1; }
        .tn img { width: 40px; height: 40px; border-radius: 50%; }
        .tv { font-family: "Hanken Grotesk"; font-weight: 800; font-size: 46px; letter-spacing: -0.03em; margin-top: 10px; font-feature-settings: "tnum"; white-space: nowrap; }
        .tv small { font-size: 20px; font-weight: 700; letter-spacing: 0; color: #949BA4; margin-left: 6px; }
        .tc { display: flex; align-items: center; gap: 10px; font-family: "Hanken Grotesk"; font-weight: 800; font-size: 28px; margin-top: 4px; font-feature-settings: "tnum"; }
        .tc img { width: 24px; height: 24px; }
        .up { color: #2EE65F; } .down { color: #F23F43; }
        .note { margin-top: 24px; font-size: 24px; color: #949BA4; }
        .rhead { margin-top: 12px; font-weight: 800; font-size: 34px; line-height: 1.2; letter-spacing: -0.01em; color: #EEEAE3; }
        .rot { display: flex; gap: 26px; margin-top: 18px; }
        .rimg { flex: none; width: 450px; height: 450px; border-radius: 12px; overflow: hidden; }
        .rimg img { width: 100%; height: 100%; display: block; transform-origin: 70% 40%; }
        .rrows { display: flex; flex-direction: column; gap: 14px; flex: 1; }
        .rr { background: #242429; border-radius: 14px; padding: 14px 20px; }
        .rr b { display: block; font-weight: 800; font-size: 30px; line-height: 1.2; color: #EEEAE3; }
        .rr i { font-style: normal; font-family: "Hanken Grotesk"; font-weight: 700; font-size: 22px; letter-spacing: .04em; }
        .rr span { display: block; margin-top: 4px; font-size: 22px; color: #b8bbc0; font-feature-settings: "tnum"; }
        .q-lead { color: #2EE65F; } .q-imp { color: #7AA7F5; } .q-weak { color: #F0BE91; } .q-lag { color: #F23F43; }
        .agenda { margin-top: 22px; }
        .lab { display: flex; align-items: center; }
        .sbadge { display: inline-flex; align-items: center; gap: 10px; margin-left: auto; padding: 5px 18px 5px 6px; border-radius: 99px; background: #242429; border: 2px solid #3a3a41; font-family: "Hanken Grotesk"; font-weight: 800; font-size: 24px; letter-spacing: .02em; text-transform: none; color: #EEEAE3; opacity: 0; }
        .sbadge img { width: 36px; height: 36px; border-radius: 10px; display: block; }
        .sbadge i { font-style: normal; font-weight: 700; color: #949BA4; }
        .bi-ico { width: 32px; height: 32px; border-radius: 50%; vertical-align: -9px; margin-right: 12px; }
        .ag { display: flex; gap: 18px; align-items: baseline; font-size: 30px; margin-top: 14px; color: #DBDEE1; }
        .ag b { min-width: 170px; }
        .ag b { font-family: "Hanken Grotesk"; font-weight: 800; color: #DEA777; min-width: 190px; font-feature-settings: "tnum"; }
        .ag span { color: #949BA4; font-size: 24px; }
        .ihsg { display: flex; gap: 30px; margin-top: 18px; }
        .ihsg > img { width: 520px; height: 377px; border-radius: 12px; display: block; }
        #s5-close { display: flex; align-items: baseline; gap: 14px; margin-top: 10px; font-size: 30px; color: #DBDEE1; }
        #s5-close b { font-family: "Hanken Grotesk"; font-weight: 800; font-size: 40px; letter-spacing: -0.02em; color: #EEEAE3; font-feature-settings: "tnum"; }
        #s5-close span { font-family: "Hanken Grotesk"; font-weight: 800; font-size: 30px; }
        .lvls { display: flex; flex-direction: column; gap: 14px; padding-top: 0; }
        .lv { background: #242429; border-radius: 14px; padding: 14px 22px; }
        .lv b { display: block; font-family: "Hanken Grotesk"; font-weight: 800; font-size: 40px; letter-spacing: -0.02em; font-feature-settings: "tnum"; }
        .lv span { font-size: 24px; color: #b8bbc0; }
        #s5-verdict { position: relative; margin-top: 20px; height: 84px; overflow: hidden; display: inline-block; border-radius: 14px; background: #DEA777; padding: 0 28px; min-width: 760px; }
        .vt { position: absolute; left: 28px; top: 0; height: 84px; line-height: 84px; font-family: "Hanken Grotesk"; font-weight: 900; font-size: 46px; letter-spacing: -0.03em; color: #111311; white-space: nowrap; }
        #s5-timing { margin-top: 10px; font-size: 24px; color: #949BA4; letter-spacing: .01em; }
        #s5-pre { position: absolute; right: 34px; top: 44px; padding: 5px 16px; border: 2px solid #DEA777; border-radius: 99px; font-family: "Hanken Grotesk"; font-weight: 700; font-size: 20px; letter-spacing: .06em; color: #F0BE91; text-transform: uppercase; }
        #s5-src { position: absolute; left: 34px; bottom: 14px; font-size: 22px; color: #949BA4; }
        #s5-src b { color: #DEA777; font-family: "Hanken Grotesk"; font-weight: 700; }
        .cap2 { position: absolute; left: 116px; top: 830px; font-weight: 700; font-size: 40px; line-height: 1.35; max-width: 600px; color: #EEEAE3; }
        .cap2 .c1 { color: #DEA777; }
        .crt { display: inline-block; width: 18px; height: 40px; background: #DEA777; vertical-align: -6px; margin-left: 6px; }
        #s5-list { position: absolute; left: 116px; top: 50%; transform: translateY(-50%); display: flex; flex-direction: column; gap: 30px; }
        .bi { display: flex; align-items: center; gap: 22px; font-weight: 700; font-size: 52px; letter-spacing: -0.02em; color: #6E6A63; }
        .bi .dot { display: block; width: 18px; height: 18px; border-radius: 50%; background: #3A3D3A; flex: none; }
        #s5-line { position: absolute; left: 760px; top: 538px; width: 1080px; height: 4px; background: #DEA777; transform-origin: 50% 50%; }
      </style>

      <div id="root" data-composition-id="s5-brief" data-width="1920" data-height="1080" data-duration="10.02">
        <div id="s5-glow"></div>
        <div id="s5-box">
          <div id="s5-card">
            {{BOTHEAD}}
            <div id="s5-title">&#127751; BURSAWATCH PAGI</div>
            <span id="s5-pre">pratinjau &middot; data 7 Okt</span>
            <div id="s5-src">Data harga dan kapitalisasi: <b>Sectors</b></div>
            <div class="ph" id="s5-p0">
              <div class="lab">Pasar global</div>
              <div class="tiles">
                <div class="tile"><div class="tn"><img src="assets/sources/emoji/kospi.png">KOSPI</div><div class="tv down" id="s5-v0">-0.00</div><div class="tc down">(-1.98%) <img src="assets/sources/emoji/red.png"></div></div>
                <div class="tile"><div class="tn"><img src="assets/sources/emoji/nikkei.png">Nikkei</div><div class="tv down" id="s5-v1">-0.00</div><div class="tc down">(-0.92%) <img src="assets/sources/emoji/red.png"></div></div>
                <div class="tile"><div class="tn"><img src="assets/sources/emoji/spy.png">SPY</div><div class="tv up" id="s5-v2">+0.00</div><div class="tc up">(+0.55%) <img src="assets/sources/emoji/green.png"></div></div>
                <div class="tile"><div class="tn"><img src="assets/sources/emoji/qqq.png">QQQ</div><div class="tv up" id="s5-v3">+0.00</div><div class="tc up">(+0.46%) <img src="assets/sources/emoji/green.png"></div></div>
                <div class="tile"><div class="tn"><img src="assets/sources/emoji/eido.png">EIDO</div><div class="tv up" id="s5-v4">+0.00</div><div class="tc up">(+0.08%) <img src="assets/sources/emoji/green.png"></div></div>
                <div class="tile"><div class="tn"><img src="assets/sources/emoji/usdidr.png">USD/IDR</div><div class="tv up" id="s5-v5">-0.00</div><div class="tc up">(-0.12%) <img src="assets/sources/emoji/green.png"></div></div>
              </div>
              <div class="agenda">
                <div class="lab">Agenda Ekonomi Indonesia &middot; BPS</div>
                <div class="ag" id="s5-a0"><b>Sen, 2 Nov</b>Perkembangan Indeks Harga Konsumen</div>
                <div class="ag" id="s5-a1"><b>Sen, 2 Nov</b>Perkembangan Ekspor dan Impor</div>
                <div class="ag" id="s5-a2"><b>Kam, 5 Nov</b>Pertumbuhan Ekonomi</div>
              </div>
            </div>
            <div class="ph" id="s5-p1">
              <div class="lab">&#127981; Rotasi sektor<span class="sbadge" id="s5-sb0"><img src="assets/sources/emoji/sectors-mark.png">Sectors <i>&middot; rotasi sektor</i></span></div>
              <div class="rhead">Energy dan Technology memimpin, Properties membaik.</div>
              <div class="rot"><div class="rimg"><img id="s5-r0" src="assets/brief/sector-chart.png"></div><div class="rrows"><div class="rr" id="s5-q00"><b>Energy <i class="q-lead">Leading</i></b><span>kekuatan +4.47 pp &middot; momentum +5.54 pp</span></div><div class="rr" id="s5-q01"><b>Technology <i class="q-lead">Leading</i></b><span>kekuatan +3.84 pp &middot; momentum +4.76 pp</span></div><div class="rr" id="s5-q02"><b>Properties &amp; Real Estate <i class="q-imp">Improving</i></b><span>kekuatan -3.79 pp &middot; momentum +5.95 pp</span></div></div></div>
            </div>
            <div class="ph" id="s5-p2">
              <div class="lab">&#128009; Rotasi konglo<span class="sbadge" id="s5-sb1"><img src="assets/sources/emoji/sectors-mark.png">Sectors <i>&middot; rotasi konglo</i></span></div>
              <div class="rhead">TNT-Saratoga-Adaro memimpin, Djarum tertinggal.</div>
              <div class="rot"><div class="rimg"><img id="s5-r1" src="assets/brief/konglo-chart.png"></div><div class="rrows"><div class="rr" id="s5-q10"><b>1 &middot; TNT-Saratoga-Adaro <i class="q-lead">Leading</i></b><span>kekuatan +4.58 pp &middot; momentum +6.92 pp</span></div><div class="rr" id="s5-q11"><b>7 &middot; Astra - Jardine Matheson <i class="q-imp">Improving</i></b><span>kekuatan -3.03 pp &middot; momentum +3.92 pp</span></div><div class="rr" id="s5-q12"><b>16 &middot; Djarum Group <i class="q-lag">Lagging</i></b><span>kekuatan -24.98 pp &middot; momentum -7.93 pp</span></div></div></div>
            </div>
            <div class="ph" id="s5-p3">
              <div class="lab">IHSG hari ini<span class="sbadge" id="s5-sb2"><img src="assets/sources/emoji/sectors-mark.png">Sectors <i>&middot; outlook IHSG</i></span></div>
              <div id="s5-close">Penutupan IHSG terakhir <b>6.193</b> <span class="up">&#9650; +74 (+1.21%)</span></div>
              <div class="ihsg">
                <img id="s5-chart" src="assets/brief/ihsg-real-yahoo.png">
                <div class="lvls">
                  <div class="lv" id="s5-lv0"><b class="up">&gt; 6.370</b><span>uji level atas jika beli menguat</span></div>
                  <div class="lv" id="s5-lv2"><b style="color:#DEA777">6.200 - 6.250</b><span>resistance terdekat</span></div>
                  <div class="lv" id="s5-lv1"><b class="down">&lt; 6.120</b><span>risiko koreksi meningkat</span></div>
                </div>
              </div>
              <div id="s5-verdict"><span class="vt" id="s5-vt0">Hijau</span><span class="vt" id="s5-vt1">Merah</span><span class="vt" id="s5-vt2">Kunci: break 6.250.</span></div>
            </div>
          </div>
        </div>
        <div id="s5-line"></div>
        <div id="s5-list">
          <div class="bi" id="s5-b0"><span class="dot"></span><span>Pasar global</span></div>
          <div class="bi" id="s5-b1"><span class="dot"></span><span>Rotasi sektor</span></div>
          <div class="bi" id="s5-b2"><span class="dot"></span><span>Rotasi konglo</span></div>
          <div class="bi" id="s5-b3"><span class="dot"></span><span>Proyeksi IHSG hari ini</span></div>
        </div>
      </div>

      <script>
        (function () {
          const tl = gsap.timeline({ paused: true });
          const D = 10.02;

          // ---- open out of the copper line
          tl.fromTo("#s5-card", { scaleY: 0.004 }, { scaleY: 1, duration: 0.34, ease: "expo.out" }, 0.02);
          tl.to("#s5-line", { scaleX: 1.05, opacity: 0, duration: 0.22 }, 0.05);
          tl.fromTo("#s5-glow", { opacity: 0 }, { opacity: 1, duration: 0.8 }, 0.1);
          tl.fromTo("#s5-box", { scale: 1 }, { scale: 1.03, duration: D, ease: "none" }, 0);

          // left bullets: everything the brief covers, the active part lights up
          const P = [0, 2.5, 4.5, 7.0]; // 34.27 / 36.77 / 38.77 / 41.27, on the beat
          [0, 1, 2, 3].forEach((i) => tl.fromTo("#s5-b" + i, { opacity: 0, x: -24 }, { opacity: 1, x: 0, duration: 0.3, ease: "expo.out" }, 0.15 + i * 0.07));
          P.forEach((p, i) => {
            if (i > 0) { tl.to("#s5-b" + (i - 1) + " > span:last-child", { color: "#6E6A63", duration: 0.2 }, p); tl.to("#s5-b" + (i - 1) + " .dot", { backgroundColor: "#3A3D3A", scale: 1, duration: 0.2 }, p); }
            tl.to("#s5-b" + i + " > span:last-child", { color: "#EEEAE3", duration: 0.2 }, p + 0.3);
            tl.fromTo("#s5-b" + i + " .dot", { backgroundColor: "#3A3D3A", scale: 1 }, { backgroundColor: "#DEA777", scale: 1.4, duration: 0.3, ease: "back.out(3)", immediateRender: false }, p + 0.3);
          });

          // phases morph in place (ref 2: blur-to-sharp, ~20 frames)
          [0, 1, 2, 3].forEach((i) => tl.set("#s5-p" + i, { opacity: 0 }, 0));
          P.forEach((p, i) => {
            if (i > 0) tl.to("#s5-p" + (i - 1), { opacity: 0, y: -20, filter: "blur(10px)", duration: 0.18, ease: "power2.in" }, p - 0.12);
            tl.fromTo("#s5-p" + i, { opacity: 0, y: 24, filter: "blur(12px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.34, ease: "expo.out", immediateRender: false }, p + (i === 0 ? 0.3 : 0.04));
          });

          // Pasar global: the overnight moves count up (7 Oct 2026 values from the Bursawatch Pagi preview run)
          const moves = [[137.49, "-", "", "poin"], [648.27, "-", "", "poin"], [4.26, "+", "", "USD"], [3.46, "+", "", "USD"], [0.01, "+", "", "USD"], [21.1, "-", "", "IDR"]];
          moves.forEach(([v, sign, cur, unit], i) => {
            const o = { n: 0 };
            const el = document.getElementById("s5-v" + i);
            const fmt = () => (el.innerHTML = sign + cur + o.n.toFixed(2) + "<small>" + unit + "</small>");
            tl.fromTo(o, { n: 0 }, { n: v, duration: 0.9, ease: "expo.out", onUpdate: fmt }, 0.45 + i * 0.1);
            tl.call(fmt, null, 0);
          });

          // real-format details: the "pratinjau" tag arrives with the card, the Sectors data line holds for both rotation parts
          tl.fromTo("#s5-pre", { opacity: 0 }, { opacity: 1, duration: 0.3 }, 0.5);
          tl.fromTo("#s5-src", { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }, P[1] + 0.3);
          tl.to("#s5-src", { opacity: 0, duration: 0.2 }, P[3] - 0.12);

          // Sectors badges: each analysis part is stamped as it lands (sector rotation, konglo rotation, IHSG outlook)
          [[0, P[1]], [1, P[2]], [2, P[3]]].forEach(([i, p]) => {
            tl.fromTo("#s5-sb" + i, { opacity: 0, scale: 0.5, x: 20 }, { opacity: 1, scale: 1, x: 0, duration: 0.3, ease: "back.out(2.4)", immediateRender: false }, p + 0.5);
            tl.fromTo("#s5-sb" + i + " img", { boxShadow: "0 0 0 0 rgba(247,100,0,.8)" }, { boxShadow: "0 0 0 14px rgba(247,100,0,0)", duration: 0.5, ease: "power2.out", immediateRender: false }, p + 0.62);
          });

          // rotations: a slow push into the quadrant chart while it holds
          tl.fromTo("#s5-r0", { scale: 1 }, { scale: 1.12, duration: 2.0, ease: "sine.inOut" }, P[1]);
          tl.fromTo("#s5-r1", { scale: 1 }, { scale: 1.12, duration: 2.5, ease: "sine.inOut" }, P[2]);
          [1, 2].forEach((ph) => [0, 1, 2].forEach((k) => tl.fromTo("#s5-q" + (ph - 1) + k, { x: 40, opacity: 0 }, { x: 0, opacity: 1, duration: 0.28, ease: "expo.out", immediateRender: false }, P[ph] + 0.35 + k * 0.16)));
          [0, 1, 2].forEach((k) => tl.fromTo("#s5-a" + k, { x: -24, opacity: 0 }, { x: 0, opacity: 1, duration: 0.26, ease: "expo.out", immediateRender: false }, 1.0 + k * 0.14));

          // IHSG: the chart settles, the two levels land, then the verdict ticks and lands on the beat
          tl.fromTo("#s5-chart", { scale: 1.06 }, { scale: 1, duration: 0.6, ease: "expo.out" }, P[3]);
          tl.fromTo("#s5-lv0", { x: 40, opacity: 0 }, { x: 0, opacity: 1, duration: 0.3, ease: "expo.out", immediateRender: false }, P[3] + 0.6);
          tl.fromTo("#s5-lv2", { x: 40, opacity: 0 }, { x: 0, opacity: 1, duration: 0.3, ease: "expo.out", immediateRender: false }, P[3] + 0.8);
          tl.fromTo("#s5-lv1", { x: 40, opacity: 0 }, { x: 0, opacity: 1, duration: 0.3, ease: "expo.out", immediateRender: false }, P[3] + 1.0);
          tl.fromTo("#s5-close", { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.3, ease: "expo.out", immediateRender: false }, P[3] + 0.3);
          tl.set(".vt", { yPercent: 100 }, 0);
          tl.fromTo("#s5-verdict", { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.2, ease: "back.out(2)" }, P[3] + 1.45);
          tl.fromTo("#s5-vt0", { yPercent: 100 }, { yPercent: 0, duration: 0.12, ease: "expo.out", immediateRender: false }, P[3] + 1.5);
          tl.to("#s5-vt0", { yPercent: -100, duration: 0.12, ease: "expo.in" }, P[3] + 1.7);
          tl.fromTo("#s5-vt1", { yPercent: 100 }, { yPercent: 0, duration: 0.12, ease: "expo.out", immediateRender: false }, P[3] + 1.76);
          tl.to("#s5-vt1", { yPercent: -100, duration: 0.12, ease: "expo.in" }, P[3] + 1.88);
          tl.fromTo("#s5-vt2", { yPercent: 100 }, { yPercent: 0, duration: 0.22, ease: "back.out(1.6)", immediateRender: false }, P[3] + 2.0);

          // ---- exit: the brief shrinks into scene 6's top-left quadrant
          tl.to("#s5-card", { x: -580, y: -250, scale: 0.42, opacity: 0.0, duration: 0.3, ease: "power3.in" }, D - 0.3);
          tl.to("#s5-list, #s5-glow", { opacity: 0, duration: 0.2 }, D - 0.3);

          window.__timelines["s5-brief"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
