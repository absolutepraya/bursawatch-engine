import Image from "next/image";
import type { CSSProperties } from "react";
import { ArrowDown, ArrowRight, Check } from "lucide-react";
import { Brand, BrandMark } from "@/components/brand";
import {
  BotMessage,
  DiscordWindow,
  ForumCard,
  ForumTagChip,
  SourceIcon,
} from "@/components/discord";
import { ConfigDemo } from "@/components/config-demo";
import { MorningBrief } from "@/components/morning-brief";
import { HeroFlow } from "@/components/hero-flow";
import { PainCards } from "@/components/pain-cards";
import {
  CHANNELS,
  DEMO_DISCORD_URL,
  ENRG_PLAN,
  FORUM_POSTS,
  SOURCES,
  src,
} from "@/lib/landing-content";
import { MotionInit } from "@/components/motion-init";
import { getWorkspaceLinks } from "@/lib/workspace-links";

function DemoButton({ label = "Coba Discord demo" }: { label?: string }) {
  return (
    <a className="button copper" href={DEMO_DISCORD_URL} target="_blank" rel="noreferrer">
      {label} <ArrowRight size={17} aria-hidden="true" />
    </a>
  );
}

export default function LandingPage() {
  const workspace = getWorkspaceLinks();
  return (
    <div className="lp">
      <MotionInit />
      <a className="skip-link" href="#main-content">
        Langsung ke konten
      </a>
      <header className="lp-header">
        <Brand />
        <nav aria-label="Navigasi utama">
          <a href="#isinya">Isinya</a>
          <a href="#swing-board">Swing board</a>
          <a href="#atur">Atur sendiri</a>
        </nav>
        <div className="lp-header-actions">
          <a className="button secondary lp-header-demo" href={workspace.demo}>
            Workspace demo
          </a>
          <a className="button secondary" href={workspace.workspace}>
            Masuk workspace
          </a>
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        <section className="lp-hero" aria-labelledby="hero-title">
          <div className="lp-hero-copy">
            <h1 id="hero-title">
              Ga usah mantau semua akun.
              <span> Biar Bursawatch yang mantau.</span>
            </h1>
            <p className="lp-lede">
              Sekuritas, analis dan keterbukaan informasi IDX dipantau 24 jam, dirangkum AI, terus
              dikirim langsung ke Discord kamu.
            </p>
            <div className="lp-actions">
              <DemoButton />
              <a className="text-link" href="#isinya">
                Lihat isinya <ArrowDown size={16} aria-hidden="true" />
              </a>
            </div>
          </div>
          <HeroFlow />
        </section>

        <section className="lp-section lp-pain" aria-labelledby="pain-title">
          <h2 id="pain-title" data-reveal>
            Nyari info saham yang cepet dan bener, di mana sih?
          </h2>
          <PainCards />
          <p className="lp-pain-out" data-reveal>
            Infonya ada di mana-mana. <span>Tapi mana yang bener?</span>
          </p>
        </section>

        <section className="lp-section lp-intro" id="isinya" aria-labelledby="intro-title">
          <div className="lp-intro-head" data-reveal>
            <BrandMark className="lp-intro-mark" />
            <div>
              <h2 id="intro-title">
                Kenalin, Bursawatch.
                <span> Udah dipilah, dari sumber kredibel.</span>
              </h2>
              <p>
                Ga perlu ribet nyari sana-sini. Tiap info dipilah ke channel-nya, dirangkum AI dalam
                Bahasa Indonesia, dan selalu ada link ke sumber aslinya.
              </p>
            </div>
          </div>
          <ul className="lp-channels" data-stagger>
            {CHANNELS.map((channel) => (
              <li key={channel.name}>
                <p className="lp-channel-name">
                  <span aria-hidden="true">#</span> {channel.name}
                </p>
                <h3>{channel.label}</h3>
                <p>{channel.body}</p>
                <p className="lp-channel-example">
                  <SourceIcon name={channel.example.source} size={18} />
                  {channel.example.title}
                </p>
                <span className="lp-channel-sources" aria-label="Sumber utama">
                  {channel.sources.map((source) => (
                    <Image key={source} src={src(source)} alt="" width={24} height={24} />
                  ))}
                </span>
              </li>
            ))}
          </ul>
          <div className="lp-sources" data-reveal>
            <h3>Dipantau 24 jam dari</h3>
            <ul>
              {SOURCES.map((source) => (
                <li key={source.name}>
                  <Image src={source.logo} alt="" width={28} height={28} />
                  {source.name}
                </li>
              ))}
              <li className="lp-sources-more">
                <span className="lp-platforms" aria-hidden="true">
                  {["twitter", "telegram", "instagram"].map((name) => (
                    <Image key={name} src={src(name)} alt="" width={20} height={20} />
                  ))}
                </span>
                dan analis lain di X, Telegram, Instagram dan WhatsApp
              </li>
            </ul>
          </div>
        </section>

        <section className="lp-section lp-swing" id="swing-board" aria-labelledby="swing-title">
          <div className="lp-copy" data-reveal>
            <h2 id="swing-title">
              Swing board.
              <span> Semua trading ideas, satu tempat.</span>
            </h2>
            <p>
              Tiap trading plan dari sekuritas dapet thread sendiri. Statusnya ikut diperbarui:
              masuk area entry, kena stop-loss, sampai target tercapai.
            </p>
            <ul className="lp-checks">
              <li>
                <Check size={16} aria-hidden="true" /> Cari saham incaranmu, langsung ketemu
                plannya.
              </li>
              <li>
                <Check size={16} aria-hidden="true" /> Entry, stop-loss, target dan alasannya.
              </li>
              <li>
                <Check size={16} aria-hidden="true" /> Dikabarin pas target tercapai.
              </li>
            </ul>
          </div>
          <div className="lp-swing-visual" data-seq>
            <DiscordWindow
              className="lp-forum"
              label="Contoh forum swing board Bursawatch"
              title={<>💬 id-stocks-swing</>}
            >
              <ul className="dc-posts">
                {FORUM_POSTS.map((post, index) => (
                  <ForumCard key={post.ticker} post={post} active={index === 0} />
                ))}
              </ul>
            </DiscordWindow>
            <DiscordWindow
              className="lp-thread"
              label="Contoh thread trading plan ENRG"
              title={<>💬 ENRG - Thu, 24 Sep 2026</>}
            >
              <BotMessage time="24/9/26 05.14" source="phintraco" title="ENRG: Buy">
                <div className="dc-author">{ENRG_PLAN.analyst}</div>
                <dl className="dc-plan">
                  {ENRG_PLAN.rows.map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}:</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
                </dl>
                <p className="dc-text">
                  <b>Reasons:</b> {ENRG_PLAN.reasons}
                </p>
                <Image
                  className="dc-img"
                  src="/landing/product/enrg-plan.jpg"
                  alt="Chart ENRG dengan area support 1200 dan target 1350"
                  width={1280}
                  height={646}
                  sizes="(max-width: 700px) 80vw, 380px"
                />
              </BotMessage>
              <BotMessage
                time="25/9/26 09.21"
                className="swing-update"
                source="phintraco"
                title={
                  <>
                    ENRG: Target 1350 achieved{" "}
                    <Image className="dc-em" src={src("green")} alt="" width={18} height={18} />
                  </>
                }
              >
                <div className="dc-tags">
                  <ForumTagChip tag="tp1" />
                </div>
              </BotMessage>
            </DiscordWindow>
          </div>
        </section>

        <section className="lp-section lp-brief" aria-labelledby="brief-title">
          <div className="lp-copy" data-reveal>
            <h2 id="brief-title">
              Tiap pagi,
              <span> Bursawatch Pagi.</span>
            </h2>
            <p>Sebelum market buka, satu rangkuman buat nentuin langkah hari ini:</p>
            <ol className="lp-brief-list">
              <li>Arah IHSG, level kunci dan rencana pantau.</li>
              <li>Katalis yang perlu diperhatikan hari ini.</li>
              <li>Pasar global: KOSPI, NIKKEI dan QQQ.</li>
              <li>Agenda rilis data Indonesia berikutnya.</li>
              <li>Rotasi sektor dan rotasi konglo terhadap IHSG.</li>
            </ol>
            <p className="lp-brief-note">Contoh di samping pakai angka dummy.</p>
          </div>
          <div data-reveal style={{ "--d": "120ms" } as CSSProperties}>
            <MorningBrief />
          </div>
        </section>

        <section className="lp-section lp-config" id="atur" aria-labelledby="config-title">
          <h2 id="config-title" data-reveal>
            Infonya, dan cara nyarinya,
            <span> kamu yang atur.</span>
          </h2>
          <p className="lp-config-lede" data-reveal style={{ "--d": "80ms" } as CSSProperties}>
            Sumber, channel, jadwal sampai jam kirim, semuanya diatur dari workspace Bursawatch.
          </p>
          <ConfigDemo />
          <p className="lp-config-more">••• dan konfigurasi lainnya</p>
          <div className="lp-config-actions" data-reveal>
            <a className="button secondary" href={workspace.demo}>
              Coba workspace demo <ArrowRight size={17} aria-hidden="true" />
            </a>
            <a className="text-link" href={workspace.workspace}>
              Udah punya akun? Masuk workspace
            </a>
          </div>
        </section>

        <section className="lp-close" aria-labelledby="close-title" data-stagger>
          <BrandMark className="lp-close-mark" />
          <p className="lp-close-kicker">
            Berita <b aria-hidden="true">·</b> Trading plan <b aria-hidden="true">·</b> Anotasi
            chart
          </p>
          <h2 id="close-title">
            Dapet duluan, <span>cuan duluan.</span>
          </h2>
          <p>Gabung server demo Discord buat lihat langsung isinya.</p>
          <DemoButton />
        </section>
      </main>

      <footer className="lp-footer">
        <Brand />
        <p>
          Berita dan trading plan di halaman ini diambil dari pengiriman asli Bursawatch, 16 Sep
          sampai 1 Okt 2026. Morning brief di atas adalah contoh dengan angka dummy. Informasi,
          bukan ajakan jual/beli saham.
        </p>
        <nav className="lp-footer-links" aria-label="Workspace">
          <a href={workspace.demo}>Workspace demo</a>
          <a href={workspace.workspace}>Masuk workspace</a>
        </nav>
      </footer>
    </div>
  );
}
