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
        #s3-box { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; container-type: inline-size; }
        {{DISCORD_CSS}}
        #s3-glow { position: absolute; left: 960px; top: 470px; width: 1300px; height: 1300px; margin: -650px 0 0 -650px; border-radius: 50%; background: radial-gradient(closest-side, rgba(222,167,119,.16), rgba(222,167,119,0)); }
        #s3-hub { position: absolute; left: 820px; top: 330px; width: 280px; height: 280px; }
        #s3-hub img { width: 100%; height: 100%; border-radius: 50%; display: block; box-shadow: 0 30px 80px rgba(0,0,0,.6); }
        .bchip { position: absolute; display: flex; align-items: center; gap: 16px; padding: 14px 34px 14px 14px; border-radius: 99px; background: #1C1F1D; border: 3px solid #34383a;
          font-weight: 700; font-size: 46px; letter-spacing: -0.02em; white-space: nowrap; box-shadow: 0 20px 44px rgba(0,0,0,.45); }
        .bchip img { width: 62px; height: 62px; border-radius: 50%; background: #fff; object-fit: cover; }
        .bchip .h { color: #DEA777; margin-right: -8px; }
        .cap2 { position: absolute; left: 116px; top: 50%; transform: translateY(-50%); font-weight: 700; font-size: 64px; line-height: 1.22; letter-spacing: -0.02em; max-width: 600px; color: #EEEAE3; }
        #s3-cap1 { left: 0; right: 0; top: 850px; transform: none; max-width: none; text-align: center; font-size: 80px; letter-spacing: -0.03em; }
        .cap2 .c1 { color: #DEA777; }
        .crt { display: inline-block; width: 0.28em; height: 0.92em; background: #DEA777; vertical-align: -0.12em; margin-left: 0.1em; }
        #s3-chan { opacity: 0; transform-origin: 50% 50%; }
        #s3-chan .dimg { width: 40%; }
        #s3-chan .dch { position: relative; z-index: 2; background: #1A1A1E; margin-top: -1.4cqw; padding-top: 1.4cqw; }
        #s3-feed { position: relative; z-index: 1; }
        #s3-line { position: absolute; left: 760px; top: 538px; width: 1080px; height: 4px; background: #DEA777; transform-origin: 50% 50%; opacity: 0; }
      </style>

      <div id="root" data-composition-id="s3-burst-proof" data-width="1920" data-height="1080" data-duration="6.51">
        <div id="s3-burst" data-layout-allow-occlusion>
          <div id="s3-glow"></div>
          <div class="bchip" id="s3-c0" style="left:300px;top:200px"><img src="assets/sources/emoji/phintraco.png"><span class="h">#</span>Trading ideas</div>
          <div class="bchip" id="s3-c1" style="left:1150px;top:170px"><img src="assets/sources/emoji/tuntun.png"><span class="h">#</span>Aksi korporasi</div>
          <div class="bchip" id="s3-c2" style="left:1340px;top:480px"><img src="assets/sources/emoji/bridanareksa.png"><span class="h">#</span>Makro</div>
          <div class="bchip" id="s3-c3" style="left:220px;top:470px"><img src="assets/sources/emoji/kobeissiletter.png"><span class="h">#</span>Komoditas</div>
          <div class="bchip" id="s3-c4" style="left:1060px;top:690px"><img src="assets/sources/emoji/stockbit.png"><span class="h">#</span>Industri &amp; regulasi</div>
          <div id="s3-hub"><img src="assets/brand/cropped_circle.png"></div>
        </div>
        <div class="cap2" id="s3-cap1"><span class="c1" data-t="udah dipilah."></span> <span class="c2" data-t="dari sumber kredibel."></span><span class="crt" id="s3-crt1"></span></div>

        <div id="s3-box">
          <div id="s3-chan" class="dframe" style="left:39.583cqw;top:3.4cqw;width:56.25cqw;height:49.5cqw">{{PROOF}}</div>
        </div>
        <div id="s3-line"></div>
        <div class="cap2" id="s3-cap2"><span class="c1" data-t="dipantau 24 jam."></span> <span class="c2" data-t="dirangkum AI."></span><span class="crt" id="s3-crt2"></span></div>
      </div>

      <script>
        (function () {
          const tl = gsap.timeline({ paused: true });
          const D = 6.51;
          const PROOF = 3.5; // 23.23s: on the beat

          // typed caption (ref 4): ~30 chars/s, copper block caret blinks on hold
          function typeCaption(capSel, crtSel, t0, tEnd) {
            const parts = gsap.utils.toArray(capSel + " [data-t]");
            let t = t0;
            parts.forEach((el) => {
              const full = el.dataset.t;
              tl.set(el, { textContent: "" }, 0);
              for (let i = 1; i <= full.length; i++) {
                tl.set(el, { textContent: full.slice(0, i) }, t);
                t += 1 / 30;
              }
              t += 0.08;
            });
            const blinkFrom = t + 0.1;
            for (let b = blinkFrom; b < tEnd - 0.2; b += 0.5) {
              tl.set(crtSel, { opacity: 0 }, b + 0.25);
              tl.set(crtSel, { opacity: 1 }, b + 0.5);
            }
            return t;
          }

          // ---- burst (ref 3): hub pops with overshoot, chips launch from behind it on the half beats
          tl.fromTo("#s3-hub", { scale: 0.3, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3, ease: "back.out(2.2)" }, 0.02);
          tl.fromTo("#s3-glow", { scale: 0.6, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.6, ease: "expo.out" }, 0);
          const hubC = { x: 960, y: 470 };
          const tilts = [-7, 6, -5, 7, -3];
          for (let i = 0; i < 5; i++) {
            const el = document.getElementById("s3-c" + i);
            const t = 0.5 + i * 0.25;
            const left = parseFloat(el.style.left), top = parseFloat(el.style.top);
            const dx = hubC.x - (left + 200), dy = hubC.y - (top + 45);
            tl.fromTo(el, { x: dx, y: dy, scale: 0.15, rotation: tilts[i] * -3, opacity: 0 },
              { x: 0, y: 0, scale: 1, rotation: tilts[i], opacity: 1, duration: 0.26, ease: "back.out(1.5)" }, t);
            // hub reacts to every launch
            tl.fromTo("#s3-hub", { scaleX: 1.06, scaleY: 0.92 }, { scaleX: 1, scaleY: 1, duration: 0.2, ease: "back.out(3)", immediateRender: false }, t);
            // parked drift so nothing freezes
            tl.to(el, { y: (i % 2 ? -10 : 10), duration: 1.4, ease: "sine.inOut" }, t + 0.3);
          }
          typeCaption("#s3-cap1", "#s3-crt1", 1.85, PROOF);
          tl.set("#s3-crt1", { opacity: 0 }, 0);
          tl.set("#s3-crt1", { opacity: 1 }, 1.8);

          // ---- proof: dive through the hub into the real channel
          tl.to("#s3-hub", { scale: 9, opacity: 0, filter: "blur(14px)", duration: 0.32, ease: "power3.in" }, PROOF - 0.18);
          for (let i = 0; i < 5; i++) {
            tl.to("#s3-c" + i, { scale: 1.6, opacity: 0, filter: "blur(10px)", duration: 0.26, ease: "power3.in" }, PROOF - 0.14);
          }
          tl.to("#s3-glow", { opacity: 0, duration: 0.3 }, PROOF - 0.1);
          tl.to("#s3-cap1", { opacity: 0, duration: 0.12 }, PROOF - 0.14);
          tl.fromTo("#s3-chan", { opacity: 0, scale: 0.86, filter: "blur(12px)" }, { opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.34, ease: "expo.out", immediateRender: false }, PROOF + 0.05);
          [0, 1, 2].forEach((i) => {
            tl.fromTo("#s3-m" + i, { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.3, ease: "expo.out" }, PROOF + 0.25 + i * 0.5);
          });
          tl.to("#s3-feed", { y: -190, duration: 0.45, ease: "expo.out" }, PROOF + 1.22);
          tl.fromTo("#s3-box", { scale: 1 }, { scale: 1.035, duration: D - PROOF, ease: "none" }, PROOF);
          tl.set("#s3-crt2", { opacity: 0 }, 0);
          tl.set("#s3-crt2", { opacity: 1 }, PROOF + 0.35);
          typeCaption("#s3-cap2", "#s3-crt2", PROOF + 0.4, D - 0.3);

          // ---- exit: the channel collapses into the copper line (the spine)
          tl.to("#s3-chan", { scaleY: 0.004, duration: 0.2, ease: "power4.in" }, D - 0.26);
          tl.fromTo("#s3-line", { opacity: 0 }, { opacity: 1, duration: 0.06, immediateRender: false }, D - 0.1);
          tl.to("#s3-cap2", { opacity: 0, duration: 0.15 }, D - 0.22);

          window.__timelines["s3-burst-proof"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
