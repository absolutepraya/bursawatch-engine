<!doctype html>
<html>
  <body>
    <template>
      <style>
        @font-face { font-family: "Hanken Grotesk"; src: url(assets/fonts/HankenGrotesk-900.woff2) format("woff2"); font-weight: 100 900; }
        #root { position: absolute; inset: 0; background: #111311; overflow: hidden; font-family: "Hanken Grotesk", sans-serif; color: #EEEAE3; }
        #s7-cam { position: absolute; inset: 0; transform-origin: 50% 50%; }
        #s7-glow { position: absolute; left: 960px; top: 560px; width: 1500px; height: 1100px; margin: -550px 0 0 -750px; border-radius: 50%; background: radial-gradient(closest-side, rgba(222,167,119,.13), rgba(222,167,119,0)); opacity: 0; }
        #s7-line { position: absolute; left: 0; top: 538px; width: 1920px; height: 4px; background: #DEA777; transform-origin: 50% 50%; }
        .w { display: inline-block; overflow: hidden; vertical-align: bottom; padding: 0 .02em .14em; margin-bottom: -.14em; }
        .wi { display: inline-block; }
        #s7-gains { position: absolute; inset: 0; }
        #s7-kick { position: absolute; left: 0; right: 0; top: 118px; text-align: center; font-weight: 600; font-size: 40px; letter-spacing: -0.01em; color: #9C978E; }
        #s7-kick b { color: #DEA777; font-weight: 700; margin: 0 14px; }
        #s7-words { position: absolute; left: 0; right: 0; top: 178px; text-align: center; font-weight: 800; font-size: 118px; line-height: 1.05; letter-spacing: -0.04em; }
        .gc { position: absolute; left: 960px; top: 610px; width: 330px; height: 330px; margin: -165px 0 0 -165px; border-radius: 22px; overflow: hidden; border: 2px solid #2a2d2b; box-shadow: 0 30px 70px rgba(0,0,0,.65); }
        .gc img { width: 100%; height: 100%; display: block; }
        #s7-disc { position: absolute; left: 0; right: 0; bottom: 34px; text-align: center; font-weight: 500; font-size: 22px; color: #86827B; letter-spacing: .01em; }
        .cu { color: #DEA777; }
        #s7-lock { position: absolute; inset: 0; }
        #s7-b { position: absolute; left: 310px; top: 438px; width: 204px; height: 204px; transform-origin: 50% 50%; }
        #s7-b svg { width: 100%; height: 100%; display: block; }
        #s7-wm { position: absolute; left: 492px; top: 419px; font-weight: 700; font-size: 243px; line-height: 1; letter-spacing: -0.035em; white-space: nowrap; }
        #s7-url { position: absolute; left: 0; right: 0; top: 694px; text-align: center; font-weight: 600; font-size: 40px; letter-spacing: .01em; color: #DEA777; }
        .ring { position: absolute; left: 412px; top: 540px; width: 400px; height: 400px; margin: -200px 0 0 -200px; border-radius: 50%; opacity: 0;
          border: 4px solid #F0BE91; box-shadow: 0 0 34px 10px rgba(222,167,119,.5), inset 0 0 26px 4px rgba(222,167,119,.35); }
        #s7-sweep { position: absolute; left: 412px; top: 540px; width: 1700px; height: 1700px; margin: -850px 0 0 -850px; border-radius: 50%; opacity: 0;
          background: conic-gradient(from 0deg, rgba(222,167,119,0) 0deg, rgba(222,167,119,0) 290deg, rgba(222,167,119,.16) 345deg, rgba(240,190,145,.42) 359deg, rgba(240,190,145,0) 360deg);
          -webkit-mask-image: radial-gradient(circle, #000 0, #000 30%, transparent 62%); mask-image: radial-gradient(circle, #000 0, #000 30%, transparent 62%); }
      </style>

      <div id="root" data-composition-id="s7-close" data-width="1920" data-height="1080" data-duration="7.67">
        <div id="s7-cam">
          <div id="s7-glow"></div>
          <div id="s7-line"></div>
          <div id="s7-gains" data-layout-allow-overlap data-layout-allow-occlusion><div class="gc" id="s7-g0"><img src="assets/gains/jarr.jpg"></div><div class="gc" id="s7-g1"><img src="assets/gains/ptba.jpg"></div><div class="gc" id="s7-g2"><img src="assets/gains/bipi.jpg"></div><div class="gc" id="s7-g3"><img src="assets/gains/coco.jpg"></div><div class="gc" id="s7-g4"><img src="assets/gains/safe.jpg"></div><div class="gc" id="s7-g5"><img src="assets/gains/aadi.jpg"></div><div class="gc" id="s7-g6"><img src="assets/gains/bwpt.jpg"></div><div class="gc" id="s7-g7"><img src="assets/gains/bksl.jpg"></div><div class="gc" id="s7-g8"><img src="assets/gains/bull.jpg"></div></div>
          <div id="s7-kick" data-layout-allow-overlap><span class="w"><span class="wi">Berita</span></span><b>&middot;</b><span class="w"><span class="wi">Trading plan</span></span><b>&middot;</b><span class="w"><span class="wi">Anotasi chart</span></span></div>
          <div id="s7-words" data-layout-allow-overlap><span class="w"><span class="wi">Dapet</span></span> <span class="w"><span class="wi">duluan,</span></span> <span class="w"><span class="wi cu">cuan</span></span> <span class="w"><span class="wi cu">duluan.</span></span></div>
          <div id="s7-sweep"></div><div class="ring" id="s7-r0"></div><div class="ring" id="s7-r1"></div><div class="ring" id="s7-r2"></div>
          <div id="s7-lock" data-layout-allow-overlap>
            <div id="s7-b"><svg viewBox="0 0 96 96"><g fill="#DEA777" transform="translate(-2 -2)">
              <path id="s7-p0" d="M14 10H46C66 10 79 20 79 35C79 44 74 50 65 54L51 46C60 43 65 40 65 35C65 28 58 24 46 24H14V10Z"/>
              <path id="s7-p1" d="M14 33H35L74 56C82 61 86 67 86 74C86 84 73 90 51 90H14V76H50C64 76 71 74 71 70C71 67 66 64 60 60L14 33Z"/>
              <path id="s7-p2" d="M14 54H31L53 67H14V54Z"/></g></svg></div>
            <div id="s7-wm"><span class="w"><span class="wi">ursawatch</span></span></div>
          </div>
          <div id="s7-url"><span class="w"><span class="wi">bursawatch.abhipraya.dev</span></span></div>
        </div>
        <div id="s7-disc">Hasil pribadi, bukan jaminan. Bukan ajakan jual/beli saham.</div>
      </div>

      <script>
        (function () {
          const tl = gsap.timeline({ paused: true });
          const D = 7.67;
          const HIT = 4.96; // 57.29s: the track's last kick (scene starts 52.33)

          // the copper line gathers to the centre
          tl.fromTo("#s7-line", { scaleX: 1 }, { scaleX: 0.06, opacity: 0.0, duration: 0.42, ease: "expo.inOut" }, 0.02);
          tl.fromTo("#s7-glow", { opacity: 0 }, { opacity: 1, duration: 1.2 }, 0.2);
          tl.fromTo("#s7-cam", { scale: 1 }, { scale: 1.04, duration: D, ease: "none" }, 0);

          // the user's real Stockbit returns, dealt from depth into a fan; SAFE lands on top
          const N = 9, MID = 4;
          for (let i = 0; i < N; i++) {
            const k = i - MID;
            const x = k * 172, y = Math.abs(k) * Math.abs(k) * 9, rot = k * 6.2;
            const order = [4, 3, 5, 2, 6, 1, 7, 0, 8].indexOf(i);
            const t = 0.4 + order * 0.13;
            tl.set("#s7-g" + i, { zIndex: i === MID ? 20 : 10 - Math.abs(k) }, 0);
            tl.fromTo("#s7-g" + i, { x: x * 0.2, y: 260, scale: 2.4, rotation: rot * 3, opacity: 0, filter: "blur(16px)" },
              { x, y, scale: i === MID ? 1.18 : 1, rotation: rot, opacity: 1, filter: "blur(0px)", duration: 0.5, ease: "back.out(1.4)" }, t);
            tl.to("#s7-g" + i, { y: y - 10, duration: 1.8, ease: "sine.inOut" }, t + 0.5);
          }
          tl.fromTo("#s7-disc", { opacity: 0 }, { opacity: 1, duration: 0.4 }, 0.9);
          // kicker ticks through what you get, then the payoff line
          gsap.utils.toArray("#s7-kick .wi").forEach((w, i) => tl.fromTo(w, { yPercent: 108 }, { yPercent: 0, duration: 0.18, ease: "expo.out" }, 1.0 + i * 0.28));
          tl.fromTo("#s7-kick b", { opacity: 0 }, { opacity: 1, duration: 0.2, stagger: 0.28 }, 1.14);
          const times = [1.95, 2.1, 2.45, 2.6];
          gsap.utils.toArray("#s7-words .wi").forEach((w, i) => tl.fromTo(w, { yPercent: 108 }, { yPercent: 0, duration: 0.18, ease: "expo.out" }, times[i]));
          // everything gathers into the mark for the last kick
          for (let i = 0; i < N; i++) tl.to("#s7-g" + i, { x: -548, y: -70, scale: 0.12, rotation: 0, opacity: 0, filter: "blur(8px)", duration: 0.42, ease: "power3.in" }, HIT - 0.5 + Math.abs(i - MID) * 0.02);
          tl.to("#s7-words, #s7-kick", { y: -50, opacity: 0, filter: "blur(10px)", duration: 0.26, ease: "power2.in" }, HIT - 0.42);

          // the mark lands on the last kick, then the lockup and URL
          tl.set("#s7-lock, #s7-url", { opacity: 0 }, 0);
          tl.set("#s7-lock, #s7-url", { opacity: 1 }, HIT - 0.14);
          tl.set("#s7-words, #s7-kick", { opacity: 0 }, HIT - 0.05);
          tl.set("#s7-wm .wi, #s7-url .wi", { yPercent: 108 }, 0);
          ["#s7-p0", "#s7-p2", "#s7-p1"].forEach((p, i) => tl.fromTo(p, { x: -40, opacity: 0 }, { x: 0, opacity: 1, duration: 0.2, ease: "expo.out" }, HIT - 0.12 + i * 0.05));
          tl.fromTo("#s7-b", { scale: 1.12 }, { scale: 1, duration: 0.3, ease: "expo.out" }, HIT + 0.02);
          tl.fromTo("#s7-wm .wi", { yPercent: 108 }, { yPercent: 0, duration: 0.2, ease: "expo.out", immediateRender: false }, HIT + 0.16);
          tl.fromTo("#s7-url .wi", { yPercent: 108 }, { yPercent: 0, duration: 0.2, ease: "expo.out", immediateRender: false }, HIT + 0.46);
          [0, 1, 2].forEach((r) => tl.fromTo("#s7-r" + r, { scale: 0.32, opacity: 1 }, { scale: 4.4, opacity: 0, duration: 1.7, ease: "power2.out", immediateRender: false }, HIT + 0.05 + r * 0.5));
          tl.fromTo("#s7-sweep", { rotation: -40, opacity: 0 }, { rotation: 320, opacity: 1, duration: 2.4, ease: "none", immediateRender: false }, HIT + 0.05);
          tl.to("#s7-sweep", { opacity: 0.35, duration: 0.6, ease: "power1.inOut" }, HIT + 1.9);

          window.__timelines["s7-close"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
