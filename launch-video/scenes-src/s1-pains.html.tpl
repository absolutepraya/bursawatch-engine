<!doctype html>
<html>
  <body>
    <template>
      <style>
        @font-face { font-family: "Hanken Grotesk"; src: url(assets/fonts/HankenGrotesk-900.woff2) format("woff2"); font-weight: 100 900; }
        @font-face { font-family: "Figtree"; src: url(assets/fonts/Figtree-700.woff2) format("woff2"); font-weight: 300 900; }
        #root { position: absolute; inset: 0; background: #111311; overflow: hidden; font-family: "Hanken Grotesk", sans-serif; color: #EEEAE3; }
        #s1-cam { position: absolute; inset: 0; transform-origin: 50% 50%; }
        #s1-hit { position: absolute; inset: 0; transform-origin: 50% 50%; }
        #s1-glow { position: absolute; left: 960px; top: 540px; width: 1600px; height: 1000px; margin: -500px 0 0 -800px; background: radial-gradient(closest-side, rgba(222,167,119,.14), rgba(222,167,119,0)); }
        .w { display: inline-block; overflow: hidden; vertical-align: bottom; padding: 0 .02em .12em; margin-bottom: -.12em; }
        .wi { display: inline-block; }
        .cu { color: #DEA777; }
        #s1-hook { position: absolute; left: 0; right: 0; top: 404px; text-align: center; font-weight: 500; font-size: 70px; line-height: 1.26; letter-spacing: -0.025em; }
        #s1-kicker { position: absolute; left: 116px; top: 84px; font-weight: 500; font-size: 28px; color: #6E6A63; }
        #s1-prog { position: absolute; right: 116px; top: 96px; display: flex; gap: 10px; }
        #s1-prog span { position: relative; width: 64px; height: 6px; border-radius: 99px; background: #2A2E2B; overflow: hidden; }
        #s1-prog i { position: absolute; inset: 0; background: #DEA777; transform-origin: 0 50%; }

        /* card column centred at x 600, text column 1010 to 1770 */
        .slot { position: absolute; left: 600px; top: 540px; width: 0; height: 0; perspective: 1700px; }
        .card { position: absolute; transform-origin: 50% 50%; }
        .pf { position: absolute; right: -22px; top: -22px; width: 64px; height: 64px; border-radius: 16px; box-shadow: 0 10px 24px rgba(0,0,0,.5); z-index: 3; }
        .pane { position: absolute; left: 1010px; top: 0; width: 770px; height: 1080px; display: flex; flex-direction: column; justify-content: center; }
        .q { font-weight: 500; font-size: 52px; line-height: 1.2; color: #9C978E; letter-spacing: -0.02em; }
        .h { margin-top: 20px; font-weight: 900; font-size: 120px; line-height: .98; letter-spacing: -0.045em; color: #EEEAE3; transform-origin: 0% 70%; }
        .t { margin-top: 26px; font-weight: 600; font-size: 46px; line-height: 1.25; letter-spacing: -0.015em; color: #D9D4CB; }
        .emw { position: relative; display: inline-block; }
        .strike { position: absolute; left: -4px; right: -4px; top: 50%; height: 12px; margin-top: -2px; background: #F23F43; border-radius: 6px; transform-origin: 0 50%; }
        .ul { position: absolute; left: 0; right: 0; bottom: -4px; height: 14px; background: #DEA777; border-radius: 7px; transform-origin: 0 50%; }
        .money { margin-top: 18px; font-weight: 800; font-size: 50px; color: #F23F43; font-feature-settings: "tnum"; letter-spacing: -0.02em; }
        #s1-aa, #s1-dd { display: inline-block; } #s1-aa { transform-origin: 0 70%; }

        /* IG stack (user-supplied IG news posts, branding removed) */
        .igpost { position: absolute; width: 400px; background: #000; border: 2px solid #262626; border-radius: 18px; overflow: hidden; box-shadow: 0 30px 70px rgba(0,0,0,.55); font-family: "Figtree"; color: #f5f5f5; }
        .igpost img.p { display: block; width: 100%; aspect-ratio: 4/5; object-fit: cover; }
        .igh { display: flex; align-items: center; gap: 12px; padding: 12px 16px; }
        .igh .ic { width: 38px; height: 38px; border-radius: 50%; }
        .igh .bar { width: 130px; height: 13px; border-radius: 99px; background: #363636; }
        .stamp { margin-left: auto; color: #F23F43; font-weight: 800; font-size: 26px; }
        #s1-chip { position: absolute; left: 420px; top: 470px; width: 330px; display: grid; grid-template-columns: 64px 1fr; gap: 4px 14px; align-items: center; background: #121316; border: 2px solid #2b2e33; border-radius: 20px; padding: 16px 20px; font-family: "Figtree"; box-shadow: 0 24px 50px rgba(0,0,0,.6); z-index: 4; }
        #s1-chip img.lg { width: 64px; height: 64px; border-radius: 50%; grid-row: span 2; }
        #s1-chip .tk { font-weight: 800; font-size: 28px; color: #EEEAE3; }
        #s1-chip .tk span { color: #2EE65F; margin-left: 8px; }
        #s1-chip .nm { font-size: 17px; color: #8A8F98; }
        #s1-chip .spark { grid-column: span 2; width: 100%; height: 56px; margin-top: 6px; }
        #s1-chip .cap { grid-column: span 2; font-size: 17px; color: #8A8F98; }

        /* Telegram dark mobile UI (fictional channel) */
        .tgapp { width: 600px; border-radius: 26px; overflow: hidden; background: #0E1621; border: 2px solid #1c2733; font-family: "Figtree"; color: #F5F5F5; box-shadow: 0 34px 80px rgba(0,0,0,.6); }
        .tgtop { display: flex; align-items: center; gap: 14px; padding: 16px 18px; background: #17212B; }
        .tgtop svg { width: 26px; height: 26px; fill: none; stroke: #8FA3B6; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
        .tgav { width: 54px; height: 54px; border-radius: 50%; background: linear-gradient(135deg, #FF885E, #E1567C); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 22px; color: #fff; }
        .tgnm { flex: 1; font-weight: 700; font-size: 26px; line-height: 1.15; }
        .tgnm small { display: block; font-weight: 500; font-size: 19px; color: #6D7F8F; }
        .tgpin { display: flex; gap: 12px; align-items: center; padding: 12px 20px; background: #17212B; border-top: 2px solid #0E1621; font-size: 19px; }
        .tgpin i { width: 4px; height: 38px; background: #6AB2F2; border-radius: 2px; }
        .tgpin b { display: block; color: #6AB2F2; font-size: 18px; }
        .tgpin span { color: #C9D2DA; }
        .tgwall { position: relative; height: 470px; padding: 18px 20px; background-color: #0E1621;
          background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120' fill='none' stroke='%23ffffff' stroke-opacity='.05' stroke-width='2'%3E%3Ccircle cx='20' cy='22' r='8'/%3E%3Cpath d='M70 15l6 12 13 2-9 9 2 13-12-6-12 6 2-13-9-9 13-2z'/%3E%3Crect x='14' y='72' width='22' height='16' rx='3'/%3E%3Cpath d='M78 86q10-18 20 0t20 0'/%3E%3C/svg%3E"); }
        .tgday { text-align: center; } .tgday span { display: inline-block; background: rgba(0,0,0,.35); color: #DDE6EE; font-size: 17px; font-weight: 600; border-radius: 99px; padding: 5px 14px; }
        .tgb { margin-top: 16px; width: 500px; background: #182533; border-radius: 18px 18px 18px 6px; padding: 14px 18px 10px; }
        .tgn { color: #6AB2F2; font-weight: 800; font-size: 20px; }
        .tgt { font-size: 25px; line-height: 1.38; margin-top: 4px; font-weight: 500; }
        .tgt b { font-weight: 800; }
        .tgm { display: flex; justify-content: flex-end; gap: 6px; color: #6D7F8F; font-size: 16px; margin-top: 6px; }
        .tgbtn { margin-top: 8px; width: 500px; background: rgba(43,82,120,.75); color: #fff; text-align: center; border-radius: 12px; padding: 12px; font-weight: 700; font-size: 21px; }
        .tgmute { background: #17212B; text-align: center; color: #6AB2F2; font-weight: 700; font-size: 21px; letter-spacing: .06em; padding: 18px; }

        /* class pricing page (recreated, brand removed) in a tilted browser window */
        .browser { width: 780px; border-radius: 18px; overflow: hidden; background: #F4F4F4; box-shadow: 0 40px 90px rgba(0,0,0,.6); border: 2px solid #2b2d30; }
        .bbar { display: flex; align-items: center; gap: 10px; height: 46px; padding: 0 16px; background: #E6E6E6; }
        .bbar i { width: 13px; height: 13px; border-radius: 50%; } .bbar i:nth-child(1) { background: #FF5F57; } .bbar i:nth-child(2) { background: #FEBC2E; } .bbar i:nth-child(3) { background: #28C840; }
        .burl { margin-left: 14px; flex: 1; height: 28px; border-radius: 8px; background: #fff; display: flex; align-items: center; padding: 0 12px; font-family: "Figtree"; font-size: 15px; color: #6b6b6b; }
        .burl b { display: inline-block; width: 110px; height: 10px; border-radius: 99px; background: #cfcfcf; margin-right: 8px; }
        .bview { position: relative; height: 486px; overflow: hidden; }
        #s1-page { position: absolute; left: 0; top: 0; width: 1980px; padding: 22px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 22px; transform-origin: 0 0; font-family: "Figtree"; color: #1b1b1b; }
        .tier { border-radius: 22px; padding: 30px 30px 26px; border: 2px solid #E6E6E6; background: #F7F7F7; min-height: 760px; }
        .tier.dark { background: #1E1E1E; border-color: #1E1E1E; color: #fff; }
        .tier.dia { background: #EDEDED; border-color: #E2E2E2; padding: 26px 18px 18px; }
        .thead { display: flex; justify-content: space-between; align-items: center; font-weight: 800; font-size: 25px; letter-spacing: -0.01em; }
        .hemat { border: 2px solid #F26A2C; color: #F26A2C; background: #FFF4EE; border-radius: 8px; padding: 6px 12px; font-weight: 600; font-size: 22px; }
        .dark .hemat { background: transparent; }
        .price { margin-top: 26px; display: flex; align-items: baseline; gap: 14px; }
        .price b { font-weight: 800; font-size: 64px; letter-spacing: -0.035em; white-space: nowrap; }
        .price s { white-space: nowrap; }
        .thead, .dhead { white-space: nowrap; }
        .price s { color: #9a9a9a; font-size: 24px; }
        .sp { margin-top: 18px; border: 2px solid #F5B79A; background: #FFF2EC; color: #F26A2C; border-radius: 12px; padding: 12px 16px; font-weight: 700; font-size: 17px; }
        .dark .sp { background: #3A3A3A; border-color: #3A3A3A; color: #fff; }
        .inner { margin-top: 16px; background: #fff; border-radius: 18px; padding: 24px; }
        .inner .sp { background: #fff; border-color: #1b1b1b; color: #1b1b1b; }
        .tier hr { border: 0; border-top: 2px solid #E3E3E3; margin: 26px 0 20px; }
        .dark hr { border-color: #333; }
        .li { display: flex; gap: 14px; align-items: flex-start; font-size: 21px; line-height: 1.38; margin-bottom: 18px; color: #333; }
        .dark .li { color: #eee; }
        .li i { flex: none; width: 30px; height: 30px; border-radius: 50%; background: #F26A2C; position: relative; }
        .li i::after { content: ""; position: absolute; left: 10px; top: 6px; width: 7px; height: 13px; border: solid #fff; border-width: 0 3px 3px 0; transform: rotate(45deg); }
        .dark .li i { background: #fff; } .dark .li i::after { border-color: #1E1E1E; }
        .dia .dhead { display: flex; align-items: center; gap: 12px; font-weight: 800; font-size: 24px; padding: 0 8px; }
        .dia .dhead svg { width: 30px; height: 30px; }

        /* X post (fictional, identity blurred) with a real TRUE.JK stock card */
        .x { width: 690px; background: #000; border: 2px solid #2F3336; border-radius: 22px; padding: 22px 24px 16px; color: #E7E9EA; font-family: "Figtree"; box-shadow: 0 34px 80px rgba(0,0,0,.6); }
        .xh { display: flex; align-items: center; gap: 12px; font-size: 22px; color: #71767B; }
        .xav { width: 52px; height: 52px; border-radius: 50%; background: #55585c; filter: blur(5px); }
        .blurid { filter: blur(7px); color: #E7E9EA; font-weight: 800; }
        .xt { font-size: 25px; line-height: 1.38; margin-top: 12px; }
        .xt .tag { color: #1D9BF0; }
        .stock { margin-top: 14px; border: 2px solid #2F3336; border-radius: 18px; overflow: hidden; background: #0A0A0A; padding: 18px 20px 12px; position: relative; }
        .stk { display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 28px; }
        .stk small { font-weight: 500; font-size: 18px; color: #8A8F98; display: block; margin-top: 2px; }
        .stlogo { position: absolute; right: 20px; top: 16px; width: 76px; height: 76px; border-radius: 50%; overflow: hidden; background: #EEF2FA; }
        .stlogo img { width: 100%; height: 100%; }
        .stp { margin-top: 6px; font-weight: 800; font-size: 54px; letter-spacing: -0.02em; font-feature-settings: "tnum"; }
        .stc { font-size: 20px; font-weight: 600; color: #00C176; }
        .stc.dn { color: #F23F43; }
        .sect { display: inline-block; margin-top: 8px; border: 2px solid #00C176; color: #00C176; border-radius: 8px; padding: 2px 10px; font-size: 16px; font-weight: 600; }
        .truechart { display: block; width: 100%; height: auto; margin-top: 8px; }
        .tfs { display: flex; justify-content: space-between; margin-top: 6px; font-size: 17px; font-weight: 600; color: #8A8F98; }
        .tfs b { color: #00C176; border-bottom: 3px solid #00C176; }
        .xa { display: flex; justify-content: space-between; margin-top: 12px; color: #71767B; font-size: 18px; }
        .xa span { display: flex; align-items: center; gap: 8px; }
        .xa svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.8; }
      </style>

      <div id="root" data-composition-id="s1-pains" data-width="1920" data-height="1080" data-duration="10.23">
        <svg width="0" height="0" style="position:absolute" aria-hidden="true">
          <filter id="s1-f0" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur id="s1-b0" stdDeviation="0 0" /></filter>
          <filter id="s1-f1" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur id="s1-b1" stdDeviation="0 0" /></filter>
          <filter id="s1-f2" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur id="s1-b2" stdDeviation="0 0" /></filter>
          <filter id="s1-f3" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur id="s1-b3" stdDeviation="0 0" /></filter>
        </svg>
        <div id="s1-cam"><div id="s1-hit">
          <div id="s1-glow"></div>
          <div id="s1-hook"><span class="w"><span class="wi">Nyari</span></span> <span class="w"><span class="wi">info</span></span> <span class="w"><span class="wi">saham</span></span> <span class="w"><span class="wi">yang</span></span> <span class="w"><span class="wi cu">cepet</span></span> <span class="w"><span class="wi">dan</span></span> <span class="w"><span class="wi cu">bener,</span></span><br><span class="w"><span class="wi">di</span></span> <span class="w"><span class="wi">mana</span></span> <span class="w"><span class="wi">sih?</span></span></div>
          <div id="s1-kicker">Nyari info saham yang cepet dan bener, di mana sih?</div>
          <div id="s1-prog"><span><i id="s1-g0"></i></span><span><i id="s1-g1"></i></span><span><i id="s1-g2"></i></span><span><i id="s1-g3"></i></span></div>

          <!-- 1: IG stack + real KETR move -->
          <div class="slot"><div class="card" id="s1-c0" data-layout-allow-overlap style="filter:url(#s1-f0);left:-360px;top:-330px;width:760px;height:660px">
            <div class="igpost" style="left:10px;top:50px;transform:rotate(-8deg);opacity:.6"><img class="p" src="assets/pain/ig-4-ultj.jpg"></div>
            <div class="igpost" style="left:310px;top:50px;transform:rotate(7deg);opacity:.6"><img class="p" src="assets/pain/ig-1-byan.jpg"></div>
            <div class="igpost" style="left:160px;top:0">
              <div class="igh"><img class="ic" src="assets/sources/emoji/instagram.png"><span class="bar"></span><span class="stamp">3 jam lalu</span></div>
              <img class="p" src="assets/pain/ig-2-ketr.jpg">
            </div>
            <div id="s1-chip"><img class="lg" src="assets/pain/ketr-logo.png"><div class="tk">KETR<span>+11,0%</span></div><div class="nm">Ketrosden Triasmitra</div>{{KETR_SPARK}}<div class="cap">udah jalan 2 minggu sebelum beritanya ramai</div></div>
          </div></div>

          <!-- 2: Telegram paid group (fictional), genuine Telegram UI and logo -->
          <div class="slot"><div class="card" id="s1-c1" data-layout-allow-overlap style="filter:url(#s1-f1);left:-300px;top:-350px;width:600px;height:700px">
            <svg class="pf" viewBox="0 0 24 24"><defs><linearGradient id="s1-tg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2AABEE"/><stop offset="1" stop-color="#229ED9"/></linearGradient></defs><circle cx="12" cy="12" r="12" fill="url(#s1-tg)"/><path fill="#fff" d="M5.43 11.87c3.5-1.52 5.83-2.53 7-3.02 3.33-1.39 4.03-1.63 4.48-1.64.1 0 .32.02.47.14.12.1.15.23.17.33.02.09.04.31.02.47-.18 1.9-.96 6.51-1.36 8.64-.17.9-.5 1.2-.82 1.23-.7.06-1.23-.46-1.9-.91-1.06-.7-1.66-1.13-2.69-1.81-1.19-.78-.42-1.21.26-1.92.18-.18 3.25-2.98 3.31-3.23.01-.03.01-.15-.06-.21-.07-.06-.17-.04-.25-.02-.1.02-1.79 1.14-5.06 3.35-.48.33-.91.49-1.3.48-.43-.01-1.25-.24-1.86-.44-.75-.24-1.35-.37-1.3-.79.03-.22.33-.44.89-.67z"/></svg>
            <div class="tgapp">
              <div class="tgtop"><svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg><div class="tgav">VI</div><div class="tgnm">VIP INSIDER A1 &#128274;<small>1.204 subscribers</small></div><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/></svg><svg viewBox="0 0 24 24"><path d="M12 5h.01M12 12h.01M12 19h.01"/></svg></div>
              <div class="tgpin"><i></i><div><b>Pesan Tersemat</b><span>Cara gabung VIP: transfer, kirim bukti ke admin...</span></div></div>
              <div class="tgwall">
                <div class="tgday"><span>Hari ini</span></div>
                <div class="tgb"><div class="tgn">VIP INSIDER A1</div><div class="tgt"><b>SLOT VIP OKTOBER TINGGAL 5!</b> Sinyal A1 tiap pagi, akurasi 90%++. Cuma Rp1.500.000 / bulan &#128293;&#128293;</div><div class="tgm">&#128065; 2,4 rb &nbsp;07.12</div></div>
                <div class="tgbtn">&#128073; DM admin sekarang</div>
                <div class="tgb" style="width:420px"><div class="tgn">VIP INSIDER A1</div><div class="tgt">Yang belum join, jangan nyesel ya &#128527;</div><div class="tgm">&#128065; 1,9 rb &nbsp;07.40</div></div>
              </div>
              <div class="tgmute">BISUKAN</div>
            </div>
          </div></div>

          <!-- 3: class pricing page (recreated, brand removed) -->
          <div class="slot"><div class="card" id="s1-c2" data-layout-allow-overlap style="filter:url(#s1-f2);left:-430px;top:-268px;width:780px;height:536px">
            <div class="browser">
              <div class="bbar"><i></i><i></i><i></i><div class="burl"><b></b>/kelas-saham</div></div>
              <div class="bview"><div id="s1-page">
                <div class="tier">
                  <div class="thead">BASIC NO RECORDING<span class="hemat">Hemat 70%</span></div>
                  <div class="price"><b>Rp 3.700.000</b><s>Rp 10.000.000</s></div>
                  <div class="sp">&#127991; SPECIAL PRICE Member Academy : Rp 1.000.000</div><hr>
                  <div class="li"><i></i>Jadi investor saham jago dari 0 dalam 2 minggu bareng expert CFA mengelola dana triliunan</div>
                  <div class="li"><i></i>Pengalaman capai return 40% secara konsisten selama 15 tahun terakhir di pasar modal</div>
                  <div class="li"><i></i>Cara pasti (bukan cara cepat) achieve financial freedom dari saham</div>
                </div>
                <div class="tier dark">
                  <div class="thead">PREMIUM WITH RECORDING<span class="hemat">Hemat 70%</span></div>
                  <div class="price"><b>Rp 4.200.000</b><s>Rp 13.000.000</s></div>
                  <div class="sp">&#127991; SPECIAL PRICE Member Academy : Rp 1.300.000</div><hr>
                  <div class="li"><i></i>Jadi investor saham jago dari 0 dalam 2 minggu bareng expert CFA mengelola dana triliunan</div>
                  <div class="li"><i></i>Pengalaman capai return 40% secara konsisten selama 15 tahun terakhir di pasar modal</div>
                  <div class="li"><i></i>Recording dan PDF Booklet atas materi yang dipresentasikan</div>
                </div>
                <div class="tier dia">
                  <div class="dhead"><svg viewBox="0 0 24 24"><path d="M6 3h12l4 6-10 12L2 9z" fill="#F26A2C"/></svg>DIAMOND + TOP G OFFLINE SUMMIT</div>
                  <div class="inner">
                    <div class="price" style="margin-top:0"><b id="s1-dia">Rp 7.200.000</b><s>Rp 20.000.000</s></div>
                    <div class="sp">&#127991; SPECIAL PRICE Member Academy : Rp 2.500.000</div><hr>
                    <div class="li"><i></i>Jadi investor saham jago dari 0 dalam 2 minggu bareng expert CFA mengelola dana triliunan</div>
                    <div class="li"><i></i>Sesi Offline Lunch (bisa hybrid) untuk menanyakan apa saja ke mentor di hotel bintang 5</div>
                  </div>
                </div>
              </div></div>
            </div>
          </div></div>

          <!-- 4: X stockpick (fictional post, identity blurred) with real TRUE.JK data -->
          <div class="slot"><div class="card" id="s1-c3" data-layout-allow-overlap style="filter:url(#s1-f3);left:-345px;top:-388px;width:690px;height:776px">
            <img class="pf" src="assets/sources/emoji/twitter.png">
            <div class="x">
              <div class="xh"><span class="xav"></span><span class="blurid">Sahabat Cuan</span><span class="blurid" style="font-weight:500;color:#71767B">@sahabatcuan</span><span>&middot; 13 Jan</span></div>
              <div class="xt">Artinya harga <span class="tag">$TRUE</span> udah masuk area spekulasi buat jualan. Target akhirnya 610 &#128640; Ko bisa? Jawabannya ada di Sirkel VIP &#128521;</div>
              <div class="stock">
                <div class="stk">TRUE &#8964;</div><div style="font-size:18px;color:#8A8F98">PT Triniti Dinamik Tbk</div>
                <div class="stlogo"><img src="assets/pain/true-logo.png"></div>
                <div class="stp" id="s1-px">530</div>
                <div style="position:relative;height:28px"><div class="stc" id="s1-chg" style="position:absolute">&#8599; +320 (+152,38%) Year To Date</div><div class="stc dn" id="s1-chg2" style="position:absolute;opacity:0">&#8600; &minus;17 (&minus;8,10%) Year To Date</div></div>
                <div class="sect">Properti &amp; Real Estate</div>
                {{TRUE_CHART}}
                <div class="tfs"><span>1D</span><span>1W</span><span>1M</span><span>3M</span><b>YTD</b><span>1Y</span><span>3Y</span><span>5Y</span></div>
              </div>
              <div class="xa"><span><svg viewBox="0 0 24 24"><path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/></svg>86</span><span><svg viewBox="0 0 24 24"><path d="M7 7h10l-2-2M17 17H7l2 2M5 9v6M19 9v6"/></svg>143</span><span><svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>1,1 rb</span><span><svg viewBox="0 0 24 24"><path d="M5 20V12M10 20V6M15 20v-9M20 20V9"/></svg>48 rb</span></div>
            </div>
          </div></div>

          <div class="pane" id="s1-p0" data-layout-allow-overlap><div class="q"><span class="w"><span class="wi">Follow</span></span> <span class="w"><span class="wi">akun</span></span> <span class="w"><span class="wi">berita</span></span> <span class="w"><span class="wi">saham</span></span> <span class="w"><span class="wi">di</span></span> <span class="w"><span class="wi">IG?</span></span></div>
            <div class="h">Beritanya<br><span class="emw">telat...<i class="strike" id="s1-e0"></i></span></div>
            <div class="t">sahamnya keburu terbang duluan &#128517;</div></div>
          <div class="pane" id="s1-p1" data-layout-allow-overlap><div class="q"><span class="w"><span class="wi">Beli</span></span> <span class="w"><span class="wi">tiket</span></span> <span class="w"><span class="wi">grup</span></span> <span class="w"><span class="wi">Telegram</span></span> <span class="w"><span class="wi">&ldquo;insider&nbsp;A1&rdquo;?</span></span></div>
            <div class="h">Boncos bro,</div>
            <div class="t">balik modal? Boro-boro... &#129394;</div>
            <div class="money">&minus;Rp<span id="s1-money">0</span></div></div>
          <div class="pane" id="s1-p2" data-layout-allow-overlap><div class="q"><span class="w"><span class="wi">Ikut</span></span> <span class="w"><span class="wi">kelas</span></span> <span class="w"><span class="wi">saham</span></span> <span class="w"><span class="wi">sana-sini?</span></span></div>
            <div class="h">Udah<br><span class="emw">mehong,<i class="ul" id="s1-e2"></i></span></div>
            <div class="t">pas praktik ga sesuai yg dipelajari &#128557;</div></div>
          <div class="pane" id="s1-p3" data-layout-allow-overlap><div class="q"><span class="w"><span class="wi">Ikut</span></span> <span class="w"><span class="wi">stockpick</span></span> <span class="w"><span class="wi">di</span></span> <span class="w"><span class="wi">X</span></span> <span class="w"><span class="wi">sama</span></span> <span class="w"><span class="wi">Threads?</span></span></div>
            <div class="h" style="font-size:112px">Adoh<br>rungk<span id="s1-aa">aa</span><span id="s1-dd">ddd!!</span></div>
            <div class="t">Ga lagi coba-coba &#128548;</div></div>
        </div></div>
      </div>

      <script>
        (function () {
          const tl = gsap.timeline({ paused: true });
          const D = 10.23;
          // the pain cards stack in depth on purpose: tell the layout audit their text may overlap
          document.querySelectorAll('[data-composition-id="s1-pains"] .card, [data-composition-id="s1-pains"] .card *').forEach((el) => el.setAttribute("data-layout-allow-overlap", ""));
          const T0 = 2.23, PAIN = 2.0; // pains on the beat grid: 2.23 / 4.23 / 6.23 / 8.23
          const rise = (sel, t, step) => gsap.utils.toArray(sel).forEach((w, i) => tl.fromTo(w, { yPercent: 108 }, { yPercent: 0, duration: 0.16, ease: "expo.out" }, Array.isArray(t) ? t[i] : t + i * step));

          tl.fromTo("#s1-cam", { scale: 1 }, { scale: 1.035, duration: D, ease: "none" }, 0);
          tl.fromTo("#s1-glow", { opacity: 0.55, scale: 0.92 }, { opacity: 1, scale: 1.06, duration: 2.2, ease: "sine.inOut" }, 0);

          // hook (ref 1 mask rise, speech cadence), then it lifts away
          rise("#s1-hook .wi", [0.24, 0.35, 0.47, 0.61, 0.73, 0.9, 1.02, 1.4, 1.51, 1.64]);
          tl.to("#s1-hook", { y: -320, scale: 0.42, opacity: 0, duration: 0.26, ease: "power3.in" }, 1.97);
          tl.fromTo("#s1-kicker", { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: 0.3, ease: "expo.out" }, 2.1);
          tl.fromTo("#s1-prog", { opacity: 0 }, { opacity: 1, duration: 0.2 }, 2.15);

          [0, 1, 2, 3].forEach((i) => { tl.set("#s1-p" + i, { opacity: 0 }, 0); tl.set("#s1-g" + i, { scaleX: 0 }, 0); tl.set("#s1-c" + i, { opacity: 0 }, 0); });
          tl.set(".pane .h, .pane .t, .money", { opacity: 0 }, 0);
          tl.set(".strike, .ul", { scaleX: 0 }, 0);

          for (let i = 0; i < 4; i++) {
            const t0 = T0 + i * PAIN;
            const card = "#s1-c" + i, pane = "#s1-p" + i;
            const node = document.getElementById("s1-b" + i);
            const p = { v: 24 };
            const write = () => node.setAttribute("stdDeviation", p.v + " 0");
            write();
            // card arrives from the left with a 3D tilt; the streak rides the same ease
            tl.fromTo(card, { x: -380, rotationY: 26, opacity: 0 }, { x: 0, rotationY: 0, opacity: 1, duration: 0.42, ease: "expo.out", immediateRender: false }, t0);
            tl.fromTo(p, { v: 24 }, { v: 0, duration: 0.26, ease: "expo.out", onUpdate: write }, t0);
            // older cards recede in depth (depth of field, not just dimming)
            for (let k = 0; k < i; k++) {
              const d = i - k;
              tl.to("#s1-c" + k, { x: -120 * d, scale: 1 - 0.09 * d, opacity: d === 1 ? 0.34 : 0.12, filter: `blur(${3 + 3 * d}px)`, duration: 0.36, ease: "expo.out" }, t0);
            }
            tl.fromTo("#s1-g" + i, { scaleX: 0 }, { scaleX: 1, duration: PAIN, ease: "none", immediateRender: false }, t0);
            // text: setup with the card, hero on the next beat, tail a beat later
            if (i > 0) tl.to("#s1-p" + (i - 1), { opacity: 0, y: -26, duration: 0.14, ease: "power2.in" }, t0 - 0.04);
            tl.set(pane, { opacity: 1 }, t0);
            rise(pane + " .q .wi", t0 + 0.06, 0.05);
            tl.fromTo(pane + " .h", { opacity: 0, scale: 1.2, filter: "blur(12px)" }, { opacity: 1, scale: 1, filter: "blur(0px)", duration: 0.2, ease: "expo.out", immediateRender: false }, t0 + 0.5);
            tl.fromTo("#s1-hit", { scale: 1.016 }, { scale: 1, duration: 0.32, ease: "expo.out", immediateRender: false }, t0 + 0.5);
            tl.fromTo(pane + " .t", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.28, ease: "expo.out", immediateRender: false }, t0 + 0.92);
          }

          // per-pain emphasis
          tl.fromTo("#s1-e0", { scaleX: 0 }, { scaleX: 1, duration: 0.24, ease: "power2.out", immediateRender: false }, T0 + 0.82);
          tl.fromTo("#s1-chip", { opacity: 0, y: 40, scale: 0.9 }, { opacity: 1, y: 0, scale: 1, duration: 0.34, ease: "back.out(1.6)" }, T0 + 1.05);
          const money = { n: 0 };
          const mEl = document.getElementById("s1-money");
          const mFmt = () => (mEl.textContent = String(Math.round(money.n / 1000) * 1000).replace(/\B(?=(\d{3})+(?!\d))/g, "."));
          tl.call(mFmt, null, 0);
          tl.fromTo(".money", { opacity: 0 }, { opacity: 1, duration: 0.12, immediateRender: false }, T0 + PAIN + 1.0);
          tl.fromTo(money, { n: 0 }, { n: 1500000, duration: 0.7, ease: "expo.out", onUpdate: mFmt, immediateRender: false }, T0 + PAIN + 1.0);
          // kelas: camera pans across the tiers and lands on Diamond
          tl.set("#s1-page", { scale: 0.6 }, 0);
          tl.fromTo("#s1-page", { x: 0 }, { x: -1980 * 0.6 + 780 - 4, duration: 1.1, ease: "expo.inOut", immediateRender: false }, T0 + 2 * PAIN + 0.3);
          tl.fromTo("#s1-e2", { scaleX: 0 }, { scaleX: 1, duration: 0.26, ease: "power2.out", immediateRender: false }, T0 + 2 * PAIN + 0.82);
          // X: the real post-peak candles draw in, price counts 530 down to 193
          const cut = {{TRUE_CUT}}, full = {{TRUE_W}};
          tl.fromTo("#s1-trueclipr", { attr: { width: cut } }, { attr: { width: full }, duration: 0.6, ease: "power1.in", immediateRender: false }, T0 + 3 * PAIN + 0.3);
          const px = { v: 530 };
          const pxEl = document.getElementById("s1-px");
          const pxFmt = () => (pxEl.textContent = String(Math.round(px.v)));
          tl.fromTo(px, { v: 530 }, { v: 193, duration: 0.6, ease: "power2.in", onUpdate: pxFmt, immediateRender: false }, T0 + 3 * PAIN + 0.3);
          tl.to("#s1-px", { color: "#F23F43", duration: 0.15 }, T0 + 3 * PAIN + 0.5);
          tl.set("#s1-chg", { opacity: 0 }, T0 + 3 * PAIN + 0.9);
          tl.set("#s1-chg2", { opacity: 1 }, T0 + 3 * PAIN + 0.9);
          tl.fromTo("#s1-aa", { scaleX: 1 }, { scaleX: 1.55, duration: 0.6, ease: "elastic.out(1, 0.45)", immediateRender: false }, T0 + 3 * PAIN + 0.55);
          tl.fromTo("#s1-dd", { x: 0 }, { x: 68, duration: 0.6, ease: "elastic.out(1, 0.45)", immediateRender: false }, T0 + 3 * PAIN + 0.55);

          // exit: the pain stack scatters with a streak, handing off to the wall
          [0, 1, 2, 3].forEach((k, j) => tl.to("#s1-c" + k, { x: -900 - 120 * j, rotationY: 30, opacity: 0, duration: 0.3, ease: "power3.in" }, D - 0.32 + j * 0.02));
          tl.to("#s1-p3, #s1-kicker, #s1-prog", { opacity: 0, duration: 0.2, ease: "power2.in" }, D - 0.26);

          window.__timelines["s1-pains"] = tl;
        })();
      </script>
    </template>
  </body>
</html>
