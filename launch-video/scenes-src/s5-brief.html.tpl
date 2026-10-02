<!doctype html>
<html>
  <body>
    <template>
      <style>
        @font-face { font-family: "Hanken Grotesk"; src: url(assets/fonts/HankenGrotesk-900.woff2) format("woff2"); font-weight: 100 900; }
        @font-face { font-family: "Figtree"; src: url(assets/fonts/Figtree-700.woff2) format("woff2"); font-weight: 300 900; }
        #root { position: absolute; inset: 0; background: #111311; overflow: hidden; font-family: "Hanken Grotesk", sans-serif; color: #EEEAE3;
          --ground:#111311; --raised:#1C1F1D; --hair:#2A2E2B; --text:#EEEAE3; --muted:#9C978E; --hint:#5F5B55; --cu:#DEA777; --cu2:#F0BE91;
          --dbg:#000; --dcard:#121316; --dtext:#DBDEE1; --dmuted:#949BA4; --dlink:#4A9BF5; --blurple:#5865F2; --up:#2EE65F; --down:#F23F43; }
        #s5-box { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; container-type: inline-size; }
        {{DISCORD_CSS}}
        #s5-glow { position: absolute; left: 1300px; top: 540px; width: 1400px; height: 1100px; margin: -550px 0 0 -700px; border-radius: 50%; background: radial-gradient(closest-side, rgba(222,167,119,.12), rgba(222,167,119,0)); }
        #s5-card { position: absolute; left: 780px; top: 100px; width: 1040px; height: 880px; background: #000; border: 2px solid #1e2023; border-radius: 18px; padding: 30px 34px; font-family: "Figtree"; color: #DBDEE1; box-shadow: 0 40px 90px rgba(0,0,0,.6); transform-origin: 50% 50%; overflow: hidden; }
        #s5-title { font-weight: 800; font-size: 46px; margin: 18px 0 0; letter-spacing: -0.01em; }
        .ph { position: absolute; left: 34px; right: 34px; top: 230px; bottom: 34px; }
        .lab { font-family: "Hanken Grotesk"; font-weight: 700; font-size: 24px; letter-spacing: .1em; color: #DEA777; text-transform: uppercase; }
        .tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 22px; }
        .tile { background: #121316; border-radius: 16px; padding: 30px 28px; }
        .tn { font-family: "Hanken Grotesk"; font-weight: 700; font-size: 26px; letter-spacing: .08em; color: #949BA4; }
        .tv { font-family: "Hanken Grotesk"; font-weight: 800; font-size: 60px; letter-spacing: -0.03em; margin-top: 10px; font-feature-settings: "tnum"; }
        .tc { font-family: "Hanken Grotesk"; font-weight: 800; font-size: 48px; margin-top: 4px; font-feature-settings: "tnum"; }
        .up { color: #2EE65F; } .down { color: #F23F43; }
        .note { margin-top: 22px; font-size: 24px; color: #949BA4; }
        .night { margin-top: 22px; background: #121316; border-radius: 18px; padding: 40px 40px; }
        .nh { font-weight: 800; font-size: 54px; line-height: 1.16; letter-spacing: -0.01em; }
        .ns { margin-top: 26px; font-size: 34px; color: #b8bbc0; line-height: 1.3; }
        .take { display: flex; gap: 22px; align-items: flex-start; background: #121316; border-radius: 16px; padding: 26px 28px; margin-top: 18px; }
        .take img.a { width: 70px; height: 70px; border-radius: 50%; }
        .take .who { font-weight: 800; font-size: 26px; color: #EEEAE3; }
        .take .who span { color: #949BA4; font-weight: 600; }
        .take p { font-size: 36px; font-weight: 600; margin-top: 6px; color: #EEEAE3; }
        .pill { display: inline-block; margin-top: 12px; font-family: "Hanken Grotesk"; font-weight: 700; font-size: 22px; border-radius: 99px; padding: 4px 16px; }
        .pill.warn { color: #DEA777; border: 2px solid #DEA777; } .pill.ok { color: #2EE65F; border: 2px solid #2EE65F; }
        .avb { position: relative; flex: none; }
        .avb img.b { position: absolute; right: -4px; bottom: -4px; width: 28px; height: 28px; border-radius: 6px; outline: 3px solid #121316; }
        .bal { display: flex; align-items: center; gap: 20px; margin-top: 30px; font-family: "Hanken Grotesk"; font-weight: 700; font-size: 26px; color: #949BA4; }
        .track { position: relative; flex: 1; height: 18px; background: #2a2c30; border-radius: 99px; overflow: hidden; }
        #s5-ok { position: absolute; left: 0; top: 0; bottom: 0; width: 36%; background: #2EE65F; transform-origin: 0 50%; }
        #s5-warn { position: absolute; right: 0; top: 0; bottom: 0; width: 64%; background: #DEA777; transform-origin: 100% 50%; }
        .chartbox { margin-top: 18px; background: #121316; border-radius: 16px; padding: 26px 30px 20px; }
        .s5chart { width: 100%; height: auto; display: block; }
        #s5-verdict { position: relative; margin-top: 24px; height: 84px; overflow: hidden; display: inline-block; border-radius: 14px; background: #DEA777; padding: 0 28px; min-width: 520px; }
        .vt { position: absolute; left: 28px; top: 0; height: 84px; line-height: 84px; font-family: "Hanken Grotesk"; font-weight: 900; font-size: 48px; letter-spacing: -0.03em; color: #111311; white-space: nowrap; }
        .cap2 { position: absolute; left: 116px; top: 830px; font-weight: 700; font-size: 40px; line-height: 1.35; max-width: 600px; color: #EEEAE3; }
        .cap2 .c1 { color: #DEA777; }
        .crt { display: inline-block; width: 18px; height: 40px; background: #DEA777; vertical-align: -6px; margin-left: 6px; }
        #s5-soon { position: absolute; left: 116px; top: 760px; font-weight: 700; font-size: 24px; letter-spacing: .08em; color: #DEA777; border: 2px solid #DEA777; border-radius: 99px; padding: 6px 18px; }
        #s5-line { position: absolute; left: 760px; top: 538px; width: 1080px; height: 4px; background: #DEA777; transform-origin: 50% 50%; }
      </style>

      <div id="root" data-composition-id="s5-brief" data-width="1920" data-height="1080" data-duration="12.02">
        <div id="s5-glow"></div>
        <div id="s5-box">
          <div id="s5-card">
            {{BOTHEAD}}
            <div id="s5-title">Morning brief</div>
            <div class="ph" id="s5-p0">
              <div class="lab">Indeks global semalam</div>
              <div class="tiles">
                <div class="tile"><div class="tn">NASDAQ</div><div class="tv" id="s5-v0">0</div><div class="tc up">+0,24%</div></div>
                <div class="tile"><div class="tn">NIKKEI</div><div class="tv" id="s5-v1">0</div><div class="tc up">+1,94%</div></div>
                <div class="tile"><div class="tn">KOSPI</div><div class="tv" id="s5-v2">0</div><div class="tc down">-0,48%</div></div>
              </div>
              <div class="note">Penutupan 30 Sep 2026</div>
            </div>
            <div class="ph" id="s5-p1">
              <div class="lab">Semalam</div>
              <div class="night">
                <div class="nh">Inflasi AS melandai, peluang The Fed naikin bunga turun ke 37%.</div>
                <div class="ns">Brent masih di atas US$100, Selat Hormuz masih panas.</div>
              </div>
            </div>
            <div class="ph" id="s5-p2">
              <div class="lab">Kata trader di X</div>
              <div class="take" id="s5-k0"><span class="avb"><img class="a" src="assets/sources/emoji/aldotjahjadi.png"><img class="b" src="assets/sources/emoji/twitter.png"></span><div><div class="who">IHSG Journal <span>@aldotjahjadi8</span></div><p>IHSG masih lemah, belum ada sinyal pembalikan.</p><span class="pill warn">hati-hati</span></div></div>
              <div class="take" id="s5-k1"><span class="avb"><img class="a" src="assets/sources/emoji/aldotjahjadi.png"><img class="b" src="assets/sources/emoji/twitter.png"></span><div><div class="who">IHSG Journal <span>@aldotjahjadi8</span></div><p>IHSG dinilai mulai terbebas dari tekanan MSCI.</p><span class="pill ok">optimis</span></div></div>
              <div class="bal"><span>optimis</span><div class="track"><i id="s5-ok"></i><i id="s5-warn"></i></div><span>hati-hati</span></div>
            </div>
            <div class="ph" id="s5-p3">
              <div class="lab">IHSG hari ini</div>
              <div class="chartbox">{{CANDLES}}</div>
              <div id="s5-verdict"><span class="vt" id="s5-vt0">Hijau</span><span class="vt" id="s5-vt1">Merah</span><span class="vt" id="s5-vt2">Sideways, rawan turun.</span></div>
            </div>
          </div>
        </div>
        <div id="s5-line"></div>
        <div id="s5-soon">SEGERA HADIR</div>
        <div class="cap2" id="s5-cap"><span class="c1" data-t="08.00 WIB."></span> <span class="c2" data-t="morning brief."></span><span class="crt" id="s5-crt"></span></div>
      </div>

      <script>
        (function () {
          const tl = gsap.timeline({ paused: true });
          const D = 12.02;
          const P = [0, 3.0, 6.0, 9.0]; // 34.27 / 37.27 / 40.27 / 43.27, on the beat

          // ---- open out of the copper line
          tl.fromTo("#s5-card", { scaleY: 0.004 }, { scaleY: 1, duration: 0.34, ease: "expo.out" }, 0.02);
          tl.to("#s5-line", { scaleX: 1.05, opacity: 0, duration: 0.22 }, 0.05);
          tl.fromTo("#s5-glow", { opacity: 0 }, { opacity: 1, duration: 0.8 }, 0.1);
          tl.fromTo("#s5-box", { scale: 1 }, { scale: 1.03, duration: D, ease: "none" }, 0);

          // caption + "segera hadir"
          const parts = gsap.utils.toArray("#s5-cap [data-t]");
          let t = 0.4;
          tl.set("#s5-crt", { opacity: 1 }, 0);
          parts.forEach((el) => { const f = el.dataset.t; tl.set(el, { textContent: "" }, 0); for (let i = 1; i <= f.length; i++) { tl.set(el, { textContent: f.slice(0, i) }, t); t += 1 / 30; } t += 0.08; });
          for (let b = t + 0.1; b < D - 0.4; b += 0.5) { tl.set("#s5-crt", { opacity: 0 }, b + 0.25); tl.set("#s5-crt", { opacity: 1 }, b + 0.5); }
          tl.fromTo("#s5-soon", { opacity: 0, y: 14 }, { opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }, 1.2);

          // phases morph in place (ref 2: blur-to-sharp, ~20 frames)
          [0, 1, 2, 3].forEach((i) => tl.set("#s5-p" + i, { opacity: 0 }, 0));
          P.forEach((p, i) => {
            if (i > 0) tl.to("#s5-p" + (i - 1), { opacity: 0, y: -20, filter: "blur(10px)", duration: 0.18, ease: "power2.in" }, p - 0.12);
            tl.fromTo("#s5-p" + i, { opacity: 0, y: 24, filter: "blur(12px)" }, { opacity: 1, y: 0, filter: "blur(0px)", duration: 0.34, ease: "expo.out", immediateRender: false }, p + (i === 0 ? 0.3 : 0.04));
          });

          // P1: index tiles count up to the real 30 Sep closes
          const vals = [26861, 66754, 6838];
          vals.forEach((v, i) => {
            const o = { n: 0 };
            const el = document.getElementById("s5-v" + i);
            const fmt = () => (el.textContent = String(Math.round(o.n)).replace(/\B(?=(\d{3})+(?!\d))/g, "."));
            tl.fromTo(o, { n: v * 0.9 }, { n: v, duration: 0.9, ease: "expo.out", onUpdate: fmt }, 0.45 + i * 0.12);
            tl.call(fmt, null, 0);
          });

          // P3: two takes, balance tips toward hati-hati
          tl.fromTo("#s5-k0", { x: 60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.3, ease: "expo.out", immediateRender: false }, P[2] + 0.15);
          tl.fromTo("#s5-k1", { x: 60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.3, ease: "expo.out", immediateRender: false }, P[2] + 0.45);
          tl.fromTo("#s5-ok", { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: "expo.out" }, P[2] + 0.9);
          tl.fromTo("#s5-warn", { scaleX: 0 }, { scaleX: 1, duration: 0.6, ease: "expo.out" }, P[2] + 0.9);

          // P4: candles draw left to right, levels draw, verdict ticks and lands on the beat
          gsap.utils.toArray("#s5-p3 .cdl").forEach((c, i) => tl.fromTo(c, { opacity: 0, scaleY: 0.2, transformOrigin: "50% 50%" }, { opacity: 1, scaleY: 1, duration: 0.18, ease: "expo.out" }, P[3] + 0.15 + i * 0.016));
          [0, 1, 2].forEach((k) => {
            tl.fromTo("#s5-lv" + k + " line", { strokeDashoffset: 1000, strokeDasharray: "1000 1000" }, { strokeDashoffset: 0, duration: 0.45, ease: "power2.out" }, P[3] + 1.0 + k * 0.15);
            tl.fromTo("#s5-lv" + k + " text", { opacity: 0 }, { opacity: 1, duration: 0.2 }, P[3] + 1.3 + k * 0.15);
            tl.set("#s5-lv" + k + " line", { strokeDasharray: "14 10" }, P[3] + 1.5 + k * 0.15);
          });
          tl.set(".vt", { yPercent: 100 }, 0);
          tl.fromTo("#s5-verdict", { opacity: 0, scale: 0.9 }, { opacity: 1, scale: 1, duration: 0.2, ease: "back.out(2)" }, P[3] + 1.45);
          tl.fromTo("#s5-vt0", { yPercent: 100 }, { yPercent: 0, duration: 0.12, ease: "expo.out", immediateRender: false }, P[3] + 1.5);
          tl.to("#s5-vt0", { yPercent: -100, duration: 0.12, ease: "expo.in" }, P[3] + 1.7);
          tl.fromTo("#s5-vt1", { yPercent: 100 }, { yPercent: 0, duration: 0.12, ease: "expo.out", immediateRender: false }, P[3] + 1.76);
          tl.to("#s5-vt1", { yPercent: -100, duration: 0.12, ease: "expo.in" }, P[3] + 1.88);
          tl.fromTo("#s5-vt2", { yPercent: 100 }, { yPercent: 0, duration: 0.22, ease: "back.out(1.6)", immediateRender: false }, P[3] + 2.0);

          // ---- exit: the brief shrinks into scene 6's top-left quadrant
          tl.to("#s5-card", { x: -580, y: -250, scale: 0.42, opacity: 0.0, duration: 0.3, ease: "power3.in" }, D - 0.3);
          tl.to("#s5-cap, #s5-soon, #s5-glow", { opacity: 0, duration: 0.2 }, D - 0.3);

          window.__timelines["s5-brief"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
