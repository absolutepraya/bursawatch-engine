<!doctype html>
<html>
  <body>
    <template>
      <style>
        @font-face { font-family: "Hanken Grotesk"; src: url(assets/fonts/HankenGrotesk-900.woff2) format("woff2"); font-weight: 100 900; }
        @font-face { font-family: "Figtree"; src: url(assets/fonts/Figtree-700.woff2) format("woff2"); font-weight: 300 900; }
        #root { position: absolute; inset: 0; background: #111311; overflow: hidden; font-family: "Hanken Grotesk", sans-serif; color: #EEEAE3;
          --ground:#111311; --raised:#1C1F1D; --hair:#2A2E2B; --text:#EEEAE3; --muted:#9C978E; --hint:#5F5B55; --cu:#DEA777; --cu2:#F0BE91; }
        #s2-cam { position: absolute; inset: 0; transform-origin: 50% 50%; }
        #s2-wallbox { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; container-type: inline-size; }
        {{SOCIAL_CSS}}
        .w { display: inline-block; overflow: hidden; vertical-align: bottom; padding: 0 .02em .14em; margin-bottom: -.14em; }
        .wi { display: inline-block; }
        .hl { position: absolute; left: 0; right: 0; text-align: center; font-weight: 600; font-size: 112px; line-height: 1.12; letter-spacing: -0.035em; }
        #s2-h1 { top: 392px; }
        #s2-h2 { top: 392px; }
        .line2 { position: relative; display: inline-block; }
        #s2-mk { position: absolute; left: -14px; right: -14px; top: 6px; bottom: -6px; background: rgba(222,167,119,.30); border-radius: 10px; transform-origin: 0% 50%; }
        .cuw { color: #F0BE91; position: relative; }
        #s2-kenalin { position: absolute; left: 0; right: 0; top: 318px; text-align: center; font-weight: 500; font-size: 40px; letter-spacing: .06em; color: #9C978E; }
        .inlet { position: absolute; left: 0; height: 4px; width: 825px; transform-origin: 0% 50%; background: linear-gradient(90deg, rgba(222,167,119,0), rgba(222,167,119,.9) 70%, #DEA777); }
        .chip { position: absolute; left: 0; display: flex; align-items: center; gap: 14px; padding: 9px 24px 9px 9px; margin-top: -10px; border-radius: 99px; background: #1C1F1D; border: 2px solid #34383a; font-family: "Figtree"; font-weight: 700; font-size: 30px; color: #EEEAE3; white-space: nowrap; transform-origin: 100% 50%; }
        .chip img { width: 52px; height: 52px; border-radius: 50%; }
        #s2-bwrap { position: absolute; left: 780px; top: 380px; width: 360px; height: 360px; transform-origin: 50% 50%; }
        #s2-bwrap svg { width: 100%; height: 100%; display: block; overflow: visible; }
        .ring { position: absolute; left: 560px; top: 560px; width: 400px; height: 400px; margin: -200px 0 0 -200px; border: 3px solid #DEA777; border-radius: 50%; opacity: 0; }
        #s2-wm { position: absolute; left: 688px; top: 470px; font-weight: 700; font-size: 150px; line-height: 1; letter-spacing: -0.04em; }
        #s2-sub { position: absolute; left: 0; right: 0; top: 700px; text-align: center; font-weight: 500; font-size: 44px; color: #9C978E; letter-spacing: -0.01em; }
      </style>

      <div id="root" data-composition-id="s2-wall-logo" data-width="1920" data-height="1080" data-duration="9.5">
        <div id="s2-cam">
          <div id="s2-wallbox" data-layout-allow-overlap data-layout-allow-overflow>{{WALL}}</div>
          <div class="hl" id="s2-h1" data-layout-allow-overlap><span class="w"><span class="wi">Infonya</span></span> <span class="w"><span class="wi">ada</span></span><br><span class="line2"><span id="s2-mk"></span><span class="w"><span class="wi cuw">di</span></span> <span class="w"><span class="wi cuw">mana-mana.</span></span></span></div>
          <div class="hl" id="s2-h2" data-layout-allow-overlap><span class="w"><span class="wi">Tapi</span></span> <span class="w"><span class="wi">mana</span></span><br><span class="w"><span class="wi">yang</span></span> <span class="w"><span class="wi">bener?</span></span></div>
        </div>

        <div id="s2-logo">
          <div id="s2-kenalin"><span class="w"><span class="wi">Kenalin,</span></span></div>
          <div class="inlet" id="s2-l0" style="top:434px"></div>
          <div class="inlet" id="s2-l1" style="top:494px"></div>
          <div class="inlet" id="s2-l2" style="top:597px"></div>
          <div class="chip" id="s2-k0" style="top:410px"><img src="assets/sources/emoji/tuntun.png">Tuntun Sekuritas</div>
          <div class="chip" id="s2-k1" style="top:410px"><img src="assets/sources/emoji/phintraco.png">Phintraco Sekuritas</div>
          <div class="chip" id="s2-k2" style="top:410px"><img src="assets/sources/web/samuel-icon.png" style="background:#fff;object-fit:contain">Samuel Sekuritas</div>
          <div class="chip" id="s2-k3" style="top:470px"><img src="assets/sources/emoji/doktermarket.png">DokterMarket</div>
          <div class="chip" id="s2-k4" style="top:470px"><img src="assets/sources/emoji/aldotjahjadi.png">IHSG Journal</div>
          <div class="chip" id="s2-k5" style="top:470px"><img src="assets/sources/emoji/kobeissiletter.png">The Kobeissi Letter</div>
          <div class="chip" id="s2-k6" style="top:573px"><img src="assets/sources/emoji/bridanareksa.png">BRI Danareksa</div>
          <div class="chip" id="s2-k7" style="top:573px"><img src="assets/sources/emoji/stockbit.png">Stockbit</div>
          <div class="chip" id="s2-k8" style="top:573px"><img src="assets/sources/emoji/kelasinvestasi.png" style="background:#fff">Kelas Investasi</div>
          <div class="ring" id="s2-r0"></div><div class="ring" id="s2-r1"></div><div class="ring" id="s2-r2"></div>
          <div id="s2-bwrap">
            <svg viewBox="0 0 96 96">
              <defs>
                <clipPath id="s2-cp0"><rect id="s2-cr0" x="0" y="0" width="0" height="96"/></clipPath>
                <clipPath id="s2-cp1"><rect id="s2-cr1" x="0" y="0" width="0" height="96"/></clipPath>
                <clipPath id="s2-cp2"><rect id="s2-cr2" x="0" y="0" width="0" height="96"/></clipPath>
              </defs>
              <g fill="#DEA777" transform="translate(-2 -2)">
                <path clip-path="url(#s2-cp0)" d="M14 10H46C66 10 79 20 79 35C79 44 74 50 65 54L51 46C60 43 65 40 65 35C65 28 58 24 46 24H14V10Z"/>
                <path clip-path="url(#s2-cp1)" d="M14 33H35L74 56C82 61 86 67 86 74C86 84 73 90 51 90H14V76H50C64 76 71 74 71 70C71 67 66 64 60 60L14 33Z"/>
                <path clip-path="url(#s2-cp2)" d="M14 54H31L53 67H14V54Z"/>
              </g>
            </svg>
          </div>
          <div id="s2-wm" data-layout-allow-overlap data-layout-allow-overflow><span class="w"><span class="wi">Bursawatch</span></span></div>
          <div id="s2-sub" data-layout-allow-overlap><span class="w"><span class="wi">Semua</span></span> <span class="w"><span class="wi">info</span></span> <span class="w"><span class="wi">saham</span></span> <span class="w"><span class="wi">penting,</span></span> <span class="w"><span class="wi">langsung</span></span> <span class="w"><span class="wi">ke</span></span> <span class="w"><span class="wi">Discord</span></span> <span class="w"><span class="wi">kamu.</span></span></div>
        </div>
      </div>

      <script>
        (function () {
          const tl = gsap.timeline({ paused: true });
          const N = {{WALL_N}};
          const DROP = 5.99; // 16.22s in the film: the music drop (scene starts at 10.23)
          const rise = (sel, t, step) => gsap.utils.toArray(sel).forEach((w, i) => {
            tl.fromTo(w, { yPercent: 108 }, { yPercent: 0, duration: 0.16, ease: "expo.out" }, Array.isArray(t) ? t[i] : t + i * (step || 0.07));
          });

          // ---- wall: real posts arrive from the left (ref 1: 12 frames, horizontal streak)
          const order = [0, 4, 8, 3, 7, 11, 1, 5, 9, 2, 6, 10];
          order.forEach((idx, k) => {
            const el = document.getElementById("s2-card-" + idx);
            const node = document.getElementById("s2-b" + idx);
            const p = { v: 20 };
            const write = () => node.setAttribute("stdDeviation", p.v + " 0");
            write();
            const t = 0.02 + k * 0.085;
            const target = el.dataset.dim === "1" ? 0.34 : 1;
            tl.fromTo(el, { x: -300, opacity: 0 }, { x: 0, opacity: target, duration: 0.22, ease: "expo.out" }, t);
            tl.fromTo(p, { v: 20 }, { v: 0, duration: 0.22, ease: "expo.out", onUpdate: write }, t);
          });
          tl.fromTo("#s2-cam", { scale: 1 }, { scale: 1.045, duration: 4.4, ease: "none" }, 0);

          // ---- headline + copper marker (ref 1 sweep ~16 frames)
          rise("#s2-h1 .wi", [0.28, 0.44, 0.98, 1.12]);
          tl.fromTo("#s2-mk", { scaleX: 0 }, { scaleX: 1, duration: 0.28, ease: "power2.out" }, 1.48);

          // ---- doubt: wall ghosts, question rises
          tl.to("#s2-h1", { opacity: 0, filter: "blur(10px)", duration: 0.14, ease: "power2.in" }, 2.92);
          tl.to("#s2-wall", { opacity: 0.15, filter: "blur(6px)", duration: 0.36, ease: "power2.out" }, 3.0);
          tl.set("#s2-h2", { opacity: 0 }, 0);
          tl.set("#s2-h2", { opacity: 1 }, 3.05);
          gsap.utils.toArray("#s2-h2 .wi").forEach((w) => tl.set(w, { yPercent: 108 }, 0));
          rise("#s2-h2 .wi", [3.1, 3.22, 3.44, 3.56]);

          // ---- absorb: sources stream along the B's inlets
          tl.to("#s2-h2", { opacity: 0, filter: "blur(10px)", duration: 0.16, ease: "power2.in" }, 4.36);
          tl.to("#s2-wall", { opacity: 0, duration: 0.36, ease: "power1.in" }, 4.4);
          rise("#s2-kenalin .wi", 4.52);
          [0, 1, 2].forEach((l) => tl.fromTo("#s2-l" + l, { scaleX: 0, opacity: 1 }, { scaleX: 1, duration: 0.36, ease: "expo.out", immediateRender: false }, 4.54 + l * 0.08));
          for (let i = 0; i < 9; i++) {
            const line = Math.floor(i / 3), slot = i % 3;
            const t = 4.6 + line * 0.14 + slot * 0.14;
            tl.fromTo("#s2-k" + i, { x: -420, opacity: 0, scale: 1 }, { x: 520, opacity: 1, scale: 0.55, duration: 0.5, ease: "power2.in" }, t);
            tl.to("#s2-k" + i, { opacity: 0, duration: 0.08 }, t + 0.45);
          }
          // the mark fills inlet by inlet as each line's last source lands
          const fill = [5.1, 5.38, 5.66];
          ["#s2-cr0", "#s2-cr1", "#s2-cr2"].forEach((r, i) => {
            tl.fromTo(r, { attr: { width: 0 } }, { attr: { width: 96 }, duration: 0.42, ease: "expo.out" }, fill[i]);
          });
          tl.set("#s2-bwrap", { opacity: 0 }, 0);
          tl.to("#s2-bwrap", { opacity: 1, duration: 0.1 }, 5.08);

          // ---- DROP: mark punches, slides into the lockup, rings ripple
          tl.to(".inlet", { opacity: 0, duration: 0.18, ease: "power2.in" }, DROP - 0.06);
          tl.to("#s2-bwrap", { scale: 1.1, duration: 0.07, ease: "power2.out" }, DROP - 0.02);
          tl.to("#s2-bwrap", { x: -400, scale: 190 / 360, duration: 0.55, ease: "expo.inOut" }, DROP + 0.08);
          tl.to("#s2-kenalin", { y: 40, duration: 0.55, ease: "expo.inOut" }, DROP + 0.08);
          rise("#s2-wm .wi", DROP + 0.42);
          [0, 1, 2].forEach((r) => tl.fromTo("#s2-r" + r, { scale: 0.35, opacity: 0.6 }, { scale: 3.4, opacity: 0, duration: 1.3, ease: "power2.out", immediateRender: false }, DROP + 0.5 + r * 0.34));
          rise("#s2-sub .wi", DROP + 0.85, 0.05);
          tl.fromTo("#s2-logo", { scale: 1 }, { scale: 1.03, duration: 9.5 - DROP, ease: "none" }, DROP);

          // ---- exit: dive into the mark (zoom-through into scene 3's hub)
          tl.to("#s2-kenalin, #s2-wm, #s2-sub", { opacity: 0, duration: 0.18, ease: "power2.in" }, 9.22);
          tl.to("#s2-bwrap", { x: -400 + 400, scale: 4.5, opacity: 0, filter: "blur(12px)", duration: 0.28, ease: "power3.in" }, 9.22);

          // seed hidden states for later beats
          tl.set("#s2-kenalin .wi, #s2-wm .wi, #s2-sub .wi", { yPercent: 108 }, 0);
          tl.set(".inlet", { scaleX: 0 }, 0);
          tl.set(".chip", { opacity: 0 }, 0);
          tl.set("#s2-kenalin", { opacity: 0 }, 0); tl.set("#s2-kenalin", { opacity: 1 }, 4.48);
          tl.set("#s2-wm, #s2-sub", { opacity: 0 }, 0); tl.set("#s2-wm", { opacity: 1 }, DROP + 0.4); tl.set("#s2-sub", { opacity: 1 }, DROP + 0.8);

          window.__timelines["s2-wall-logo"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
