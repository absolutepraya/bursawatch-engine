import Image from "next/image";
import type { CSSProperties } from "react";
import { BrandMark } from "@/components/brand";
import { DiscordWindow, FeedItem } from "@/components/discord";
import { NEWS_FEED, src } from "@/lib/landing-content";

/** Hero visual: many watched sources converge into one summarized delivery. */

const HERO_SOURCES = [
  { name: "Phintraco", logo: "phintraco" },
  { name: "BRI Danareksa", logo: "bridanareksa" },
  { name: "Tuntun", logo: "tuntun" },
  { name: "IDX", logo: "idx" },
  { name: "IHSG Journal", logo: "aldotjahjadi", badge: "twitter" },
  { name: "Kobeissi", logo: "kobeissiletter", badge: "twitter" },
];

export function HeroFlow() {
  return (
    <div className="hero-flow">
      <ul className="hero-sources" aria-label="Sebagian sumber yang dipantau">
        {HERO_SOURCES.map((source, index) => (
          <li key={source.name} style={{ "--i": index } as CSSProperties}>
            <span className="hero-src-av">
              <Image src={src(source.logo)} alt="" width={26} height={26} />
              {source.badge ? (
                <Image
                  className="hero-src-badge"
                  src={src(source.badge)}
                  alt=""
                  width={12}
                  height={12}
                />
              ) : null}
            </span>
            {source.name}
          </li>
        ))}
      </ul>
      <div className="hero-merge" aria-hidden="true">
        <svg viewBox="0 0 300 64" preserveAspectRatio="none">
          {[50, 150, 250].map((x) => (
            <path key={x} d={`M${x} 0 C ${x} 34, 150 26, 150 64`} />
          ))}
          {[50, 150, 250].map((x, index) => (
            <path
              key={`pulse-${x}`}
              className="hero-pulse"
              style={{ "--i": index } as CSSProperties}
              pathLength={1}
              d={`M${x} 0 C ${x} 34, 150 26, 150 64`}
            />
          ))}
        </svg>
        <span className="hero-node">
          <BrandMark />
        </span>
      </div>
      <DiscordWindow
        className="hero-message"
        label="Contoh pesan Bursawatch di channel id-stocks-news, dengan data sektor dari Sectors"
        title={<># id-stocks-news</>}
      >
        <FeedItem message={NEWS_FEED[0]} />
      </DiscordWindow>
    </div>
  );
}
