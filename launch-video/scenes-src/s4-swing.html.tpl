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
        #s4-box { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; container-type: inline-size; }
        {{DISCORD_CSS}}
        #s4-cam { position: absolute; inset: 0; transform-origin: 1300px 540px; }
        .frame { position: absolute; left: 760px; top: 60px; width: 1080px; height: 960px; background: #1A1A1E; border: 2px solid #313137; border-radius: 16px; overflow: hidden; font-family: "Figtree"; color: #DBDEE1; box-shadow: 0 40px 80px rgba(0,0,0,.55); }
        #s4-forum { padding: 26px 28px; transform-origin: 50% 50%; }
        .fhead { display: flex; gap: 14px; align-items: center; }
        .fsearch { flex: 1; display: flex; align-items: center; gap: 14px; height: 74px; padding: 0 22px; border: 2px solid #3a3a41; border-radius: 14px; background: #242429; font-size: 32px; }
        .mag { color: #6d7178; font-size: 30px; transform: rotate(-45deg); display: inline-block; }
        .fph { color: #6d7178; font-weight: 600; }
        .fq { color: #fff; font-weight: 800; letter-spacing: .02em; }
        .fcaret { width: 3px; height: 38px; background: #DBDEE1; opacity: 0; }
        .fnew { background: #5865F2; color: #fff; font-weight: 800; font-size: 26px; border-radius: 12px; padding: 20px 26px; }
        .frow { display: flex; gap: 12px; margin: 18px 0 18px; white-space: nowrap; }
        .fchip { display: inline-flex; align-items: center; gap: 8px; border: 2px solid #3a3a41; border-radius: 99px; padding: 9px 18px; font-size: 21px; font-weight: 700; color: #c9ccd0; }
        .fchip svg, .ftag2 svg { width: 22px; height: 22px; }
        .flist { position: relative; height: 760px; overflow: hidden; }
        #s4-only { position: absolute; left: 0; right: 0; top: 0; opacity: 0; }
        .fpost { display: flex; justify-content: space-between; gap: 20px; border: 2px solid #313137; border-radius: 16px; padding: 20px 22px; margin-bottom: 14px; background: #242429; }
        .ftag2 { display: inline-flex; align-items: center; gap: 8px; border: 2px solid #3a3a41; border-radius: 99px; padding: 5px 14px; font-size: 19px; font-weight: 700; color: #DBDEE1; margin-right: 8px; }
        .ft { font-weight: 800; font-size: 38px; margin-top: 10px; letter-spacing: -0.01em; }
        .fby { display: flex; align-items: center; gap: 8px; font-size: 24px; font-weight: 700; margin-top: 4px; }
        .fby img { width: 26px; height: 26px; border-radius: 50%; }
        .bw { color: #E4892F; text-decoration: underline; }
        .fmeta { color: #949BA4; font-size: 20px; margin-top: 8px; }
        .fthumb { width: 150px; height: 150px; object-fit: cover; border-radius: 12px; flex: none; background: #fff; }
        #s4-thread { opacity: 0; padding: 26px 30px; }
        #s4-thread .dimg { width: 78%; }
        #s4-line { position: absolute; left: 760px; top: 538px; width: 1080px; height: 4px; background: #DEA777; transform-origin: 50% 50%; }
        .cap2 { position: absolute; left: 116px; top: 50%; transform: translateY(-50%); font-weight: 700; font-size: 64px; line-height: 1.22; letter-spacing: -0.02em; max-width: 590px; color: #EEEAE3; }
        .cap2 .c1 { color: #DEA777; }
        .crt { display: inline-block; width: 0.28em; height: 0.92em; background: #DEA777; vertical-align: -0.12em; margin-left: 0.1em; }
        #s4-cursor { position: absolute; left: 0; top: 0; width: 34px; height: 46px; opacity: 0; }
      </style>

      <div id="root" data-composition-id="s4-swing" data-width="1920" data-height="1080" data-duration="8.03">
        <div id="s4-cam">
          <div id="s4-box">
            <div class="frame" id="s4-forum">{{FORUM}}</div>
            <div class="frame" id="s4-thread" data-layout-allow-overlap>{{THREAD}}</div>
          </div>
          <svg id="s4-cursor" viewBox="0 0 34 46"><path d="M2 2v38l10-9 7 14 7-3-7-14h13z" fill="#fff" stroke="#000" stroke-width="2"/></svg>
        </div>
        <div id="s4-line"></div>
        <div class="cap2" id="s4-cap1"><span class="c1" data-t="swing board."></span> <span class="c2" data-t="semua trading ideas, satu tempat."></span><span class="crt" id="s4-crt1"></span></div>
        <div class="cap2" id="s4-cap2"><span class="c1" data-t="cari"></span> <span class="c2" data-t="saham incaranmu."></span><span class="crt" id="s4-crt2"></span></div>
        <div class="cap2" id="s4-cap3"><span class="c1" data-t="cek"></span> <span class="c2" data-t="siapa aja yang udah bahas sahammu."></span><span class="crt" id="s4-crt3"></span></div>
      </div>

      <script>
        (function () {
          const tl = gsap.timeline({ paused: true });
          const D = 8.03;
          const SEARCH = 2.5, OPEN = 4.5, PUNCH = 6.0; // 28.74 / 30.74 (beat break) / 32.24 (kick returns)

          function typeCaption(capSel, crtSel, t0, tEnd) {
            const parts = gsap.utils.toArray(capSel + " [data-t]");
            let t = t0;
            tl.set(crtSel, { opacity: 0 }, 0);
            tl.set(crtSel, { opacity: 1 }, t0 - 0.05);
            parts.forEach((el) => {
              const full = el.dataset.t;
              tl.set(el, { textContent: "" }, 0);
              for (let i = 1; i <= full.length; i++) { tl.set(el, { textContent: full.slice(0, i) }, t); t += 1 / 30; }
              t += 0.08;
            });
            for (let b = t + 0.1; b < tEnd - 0.2; b += 0.5) { tl.set(crtSel, { opacity: 0 }, b + 0.25); tl.set(crtSel, { opacity: 1 }, b + 0.5); }
          }

          // ---- open out of the copper line
          tl.fromTo("#s4-forum", { scaleY: 0.004 }, { scaleY: 1, duration: 0.3, ease: "expo.out" }, 0.02);
          tl.to("#s4-line", { scaleX: 1.06, opacity: 0, duration: 0.22, ease: "power2.out" }, 0.04);

          // ---- scroll the board fast, decelerating
          tl.fromTo("#s4-list", { y: 0 }, { y: -1580, duration: 2.1, ease: "expo.out" }, 0.2);
          typeCaption("#s4-cap1", "#s4-crt1", 0.4, SEARCH);

          // ---- search ENRG
          tl.to("#s4-cap1", { opacity: 0, duration: 0.12 }, SEARCH - 0.1);
          tl.to("#s4-search", { borderColor: "#DEA777", duration: 0.15 }, SEARCH);
          tl.set("#s4-ph", { display: "none" }, SEARCH + 0.08);
          tl.set("#s4-caret", { opacity: 1 }, SEARCH + 0.08);
          ["E", "EN", "ENR", "ENRG"].forEach((q, i) => tl.set("#s4-q", { textContent: q }, SEARCH + 0.12 + i * 0.12));
          tl.set("#s4-q", { textContent: "" }, 0);
          for (let b = SEARCH + 0.7; b < OPEN; b += 0.5) { tl.set("#s4-caret", { opacity: 0 }, b); tl.set("#s4-caret", { opacity: 1 }, b + 0.25); }
          tl.to("#s4-list", { opacity: 0, y: "-=40", duration: 0.2, ease: "power2.in" }, SEARCH + 0.62);
          tl.fromTo("#s4-only", { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.3, ease: "expo.out", immediateRender: false }, SEARCH + 0.78);
          typeCaption("#s4-cap2", "#s4-crt2", SEARCH + 0.2, OPEN);

          // ---- cursor picks the post, the thread opens in the beat break
          tl.fromTo("#s4-cursor", { x: 1500, y: 980, opacity: 0 }, { x: 1180, y: 330, opacity: 1, duration: 0.5, ease: "power3.out", immediateRender: false }, OPEN - 0.85);
          tl.to("#s4-cursor", { scale: 0.85, duration: 0.06, transformOrigin: "0 0" }, OPEN - 0.2);
          tl.to("#s4-cursor", { scale: 1, duration: 0.1 }, OPEN - 0.14);
          tl.to("#s4-hit", { backgroundColor: "#16181b", duration: 0.1 }, OPEN - 0.2);
          tl.to("#s4-cap2", { opacity: 0, duration: 0.12 }, OPEN - 0.05);
          tl.to("#s4-cursor", { opacity: 0, duration: 0.15 }, OPEN + 0.05);
          tl.to("#s4-forum", { x: -80, opacity: 0, duration: 0.3, ease: "power2.in" }, OPEN - 0.05);
          tl.fromTo("#s4-thread", { x: 300, opacity: 0 }, { x: 0, opacity: 1, duration: 0.36, ease: "expo.out", immediateRender: false }, OPEN);
          [0, 1, 2].forEach((i) => tl.fromTo("#s4-t" + i, { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.3, ease: "expo.out" }, OPEN + 0.12 + i * 0.22));
          typeCaption("#s4-cap3", "#s4-crt3", OPEN + 0.3, D - 0.2);

          // ---- the kick returns: punch into the analyst's chart
          tl.to("#s4-cam", { scale: 1.32, x: 70, y: 0, duration: 0.5, ease: "expo.out" }, PUNCH);
          tl.to("#s4-cam", { scale: 1.37, duration: D - PUNCH - 0.5, ease: "none" }, PUNCH + 0.5);

          // ---- exit into the copper line
          tl.to("#s4-cam", { scaleY: 0.004, duration: 0.2, ease: "power4.in" }, D - 0.24);
          tl.set("#s4-line", { opacity: 1, scaleX: 1 }, D - 0.06);
          tl.to("#s4-cap3", { opacity: 0, duration: 0.15 }, D - 0.22);

          window.__timelines["s4-swing"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
