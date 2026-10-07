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
                #s3-chan .dch { position: relative; z-index: 2; background: #1A1A1E; margin-top: -1.4cqw; padding-top: 1.4cqw; }
        #s3-feed { position: relative; z-index: 1; }
        /* pill enrichment: an "Enriched by Sectors" tab drops under each pill, sheens in the Sectors red-to-orange, and the pill rim glows once */
        .bchip { box-shadow: 0 0 0 0 rgba(247,100,0,0), 0 20px 44px rgba(0,0,0,.45); }
        .csheen { position: absolute; inset: -3px; border-radius: 99px; overflow: hidden; pointer-events: none; }
        .csheen i { position: absolute; top: -10%; bottom: -10%; left: 0; width: 34%; background: linear-gradient(100deg, rgba(224,0,60,0), rgba(236,50,52,.5) 38%, rgba(247,110,0,.8) 62%, rgba(247,100,0,0)); transform: skewX(-20deg); opacity: 0; }
        .senr { position: absolute; left: 0; right: 0; margin: 0 auto; top: calc(100% + 3px); width: max-content; display: flex; align-items: center; gap: 8px; padding: 7px 18px 7px 9px; border-radius: 0 0 18px 18px; overflow: hidden;
          background: linear-gradient(90deg, #E0003C, #F76400); color: #fff; font-weight: 800; font-size: 19px; line-height: 1; letter-spacing: 0; box-shadow: 0 12px 26px rgba(247,100,0,.32); opacity: 0; transform-origin: 50% 0; }
        .bchip .senr img { width: 24px; height: 24px; border-radius: 6px; background: #fff; display: block; }
        .senr i { position: absolute; top: 0; bottom: 0; left: 0; width: 38%; background: linear-gradient(100deg, rgba(255,255,255,0), rgba(255,255,255,.85) 50%, rgba(255,255,255,0)); transform: skewX(-20deg); opacity: 0; }
        /* Sectors card in the production message: sector and market cap from Sectors, sentiment read */
        #s3-chan .dvia { display: inline-flex; align-items: center; gap: .35cqw; margin-left: .5cqw; font-size: 1.05cqw; font-weight: 600; color: #949BA4; }
        #s3-chan .dvia img { width: 1.2cqw; height: 1.2cqw; border-radius: 50%; }
        #s3-chan .phd { display: flex; align-items: baseline; justify-content: space-between; }
        #s3-chan .dcap { font-size: 1.25cqw; }
        #s3-chan .prow4 { display: grid; grid-template-columns: repeat(4, auto); justify-content: space-between; margin-top: .3cqw; font-size: 1.15cqw; }
        #s3-chan .price { margin-top: .5cqw; font-size: 1.25cqw; }
        #s3-chan .dtext { font-size: 1.25cqw; line-height: 1.4; }
        #s3-chan .dtitle { font-size: 1.5cqw; }
        #s3-chan .dmsg { margin-bottom: 1cqw; }
        .dsec { position: relative; display: grid; margin-top: .8cqw; border-radius: .7cqw; background: #202026; border: .1cqw solid #34343b; overflow: hidden; opacity: 0; }
        .dsec::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: .35cqw; background: linear-gradient(180deg, #E0003C, #F76400); }
        .dsec > div { grid-area: 1 / 1; display: flex; align-items: center; gap: 1.1cqw; padding: .55cqw 1.1cqw .55cqw 1.2cqw; }
        .dsec img { width: 2.2cqw; height: 2.2cqw; border-radius: .5cqw; flex: none; }
        .dsec .sw { color: #949BA4; font-size: 1.15cqw; font-weight: 700; }
        .dsec .sd { opacity: 0; }
        .dsec .sd > span { display: flex; flex-direction: column; line-height: 1.2; }
        .dsec .k { font-size: .85cqw; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #949BA4; }
        .dsec .k em { font-style: normal; text-transform: none; letter-spacing: 0; color: #6f747b; margin-left: .2cqw; }
        .dsec .v, .dsec .k { white-space: nowrap; }
        .dsec .v { font-size: 1.15cqw; font-weight: 800; color: #EEEAE3; }
        .dsec .sv { margin-left: auto; }
        .dsec .v small { font-size: .95cqw; font-weight: 600; color: #949BA4; }
        .dsec .cv.up .v { color: #2EE65F; } .dsec .cv.flat .v { color: #C9CCD0; }
        .dsec .sv.up .v { color: #2EE65F; } .dsec .sv.down .v { color: #F23F43; } .dsec .sv.flat .v { color: #C9CCD0; }
        .dsec .scan { position: absolute; top: 0; bottom: 0; left: 0; width: 30%; background: linear-gradient(100deg, rgba(224,0,60,0), rgba(236,60,50,.35), rgba(247,100,0,.55), rgba(247,100,0,0)); transform: skewX(-20deg); opacity: 0; pointer-events: none; }
        #s3-line { position: absolute; left: 760px; top: 538px; width: 1080px; height: 4px; background: #DEA777; transform-origin: 50% 50%; opacity: 0; }
      </style>

      <div id="root" data-composition-id="s3-burst-proof" data-width="1920" data-height="1080" data-duration="6.51">
        <div id="s3-burst" data-layout-allow-occlusion>
          <div id="s3-glow"></div>
          <div class="bchip" id="s3-c0" style="left:300px;top:200px"><img src="assets/sources/emoji/phintraco.png"><span class="h">#</span>Trading ideas<span class="csheen"><i></i></span><span class="senr"><img src="assets/sources/emoji/sectors-mark.png">Enriched by Sectors<i></i></span></div>
          <div class="bchip" id="s3-c1" style="left:1150px;top:170px"><img src="assets/sources/emoji/tuntun.png"><span class="h">#</span>Aksi korporasi<span class="csheen"><i></i></span><span class="senr"><img src="assets/sources/emoji/sectors-mark.png">Enriched by Sectors<i></i></span></div>
          <div class="bchip" id="s3-c2" style="left:1340px;top:480px"><img src="assets/sources/emoji/bridanareksa.png"><span class="h">#</span>Makro<span class="csheen"><i></i></span><span class="senr"><img src="assets/sources/emoji/sectors-mark.png">Enriched by Sectors<i></i></span></div>
          <div class="bchip" id="s3-c3" style="left:220px;top:470px"><img src="assets/sources/emoji/kobeissiletter.png"><span class="h">#</span>Komoditas<span class="csheen"><i></i></span><span class="senr"><img src="assets/sources/emoji/sectors-mark.png">Enriched by Sectors<i></i></span></div>
          <div class="bchip" id="s3-c4" style="left:1060px;top:690px"><img src="assets/sources/emoji/stockbit.png"><span class="h">#</span>Industri &amp; regulasi<span class="csheen"><i></i></span><span class="senr"><img src="assets/sources/emoji/sectors-mark.png">Enriched by Sectors<i></i></span></div>
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
          // ---- Sectors enrichment: an "Enriched by Sectors" tab drops under each pill, a Sectors-coloured sheen crosses tab and pill, the rim glows once
          const SEC = 1.9;
          for (let i = 0; i < 5; i++) {
            const c = "#s3-c" + i, t = SEC + i * 0.17;
            tl.set(c + " .senr", { opacity: 0 }, 0);
            tl.fromTo(c + " .senr", { opacity: 0, y: -16, scaleY: 0.3 }, { opacity: 1, y: 0, scaleY: 1, duration: 0.34, ease: "back.out(2.2)", immediateRender: false }, t);
            tl.fromTo(c + " .senr img", { scale: 0, rotation: -90 }, { scale: 1, rotation: 0, duration: 0.3, ease: "back.out(3)", immediateRender: false }, t + 0.1);
            tl.fromTo(c + " .senr i", { xPercent: -200, opacity: 1 }, { xPercent: 420, duration: 0.7, ease: "power2.inOut", immediateRender: false }, t + 0.3);
            tl.fromTo(c + " .csheen i", { xPercent: -200, opacity: 1 }, { xPercent: 330, duration: 0.75, ease: "power2.inOut", immediateRender: false }, t + 0.12);
            tl.to(c, { borderColor: "#F0643C", boxShadow: "0 0 46px 6px rgba(247,100,0,.5), 0 20px 44px rgba(0,0,0,.45)", duration: 0.25, ease: "power2.out" }, t + 0.1);
            tl.to(c, { borderColor: "#34383a", boxShadow: "0 0 0 0 rgba(247,100,0,0), 0 20px 44px rgba(0,0,0,.45)", duration: 0.55, ease: "power2.inOut" }, t + 0.4);
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
          // Sectors card lands under each message: a Sectors-coloured scan, then sector, market cap and the sentiment read
          [0, 1, 2].forEach((i) => {
            const t = PROOF + 0.25 + i * 0.5 + 0.3;
            tl.fromTo("#s3-s" + i, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.22, ease: "expo.out", immediateRender: false }, t);
            tl.fromTo("#s3-s" + i + " .scan", { xPercent: -150, opacity: 1 }, { xPercent: 420, duration: 0.5, ease: "power1.inOut", immediateRender: false }, t + 0.08);
            tl.to("#s3-s" + i + " .sw", { opacity: 0, duration: 0.1 }, t + 0.4);
            tl.to("#s3-s" + i + " .sd", { opacity: 1, duration: 0.14 }, t + 0.42);
            tl.fromTo("#s3-s" + i + " .sv", { scale: 1.12 }, { scale: 1, duration: 0.3, ease: "back.out(3)", immediateRender: false, transformOrigin: "100% 50%" }, t + 0.45);
          });
          tl.to("#s3-feed", { y: -140, duration: 0.45, ease: "expo.out" }, PROOF + 1.22);
          tl.to("#s3-feed", { y: -380, duration: 0.45, ease: "expo.out" }, PROOF + 1.72);
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
