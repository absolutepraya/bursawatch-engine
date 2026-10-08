import Image from "next/image";
import type { CSSProperties } from "react";
import { BrandMark } from "@/components/brand";
import { DiscordWindow, FeedItem } from "@/components/discord";
import { NEWS_FEED, src } from "@/lib/landing-content";

/** Hero visual: watched sources pour through the mark and land as one message enriched by Sectors. */

const HERO_SOURCES = [
  { name: "Phintraco", logo: "phintraco" },
  { name: "BRI Danareksa", logo: "bridanareksa" },
  { name: "Tuntun", logo: "tuntun" },
  { name: "IDX", logo: "idx" },
  { name: "IHSG Journal", logo: "aldotjahjadi", badge: "twitter" },
  { name: "Kobeissi", logo: "kobeissiletter", badge: "twitter" },
];

/** Funnel geometry in one 540 x 210 box: three source columns, the mark at (270, 100), the message below. */
const W = 540;
const H = 210;
const NODE = { x: 270, y: 100 };
const COLUMNS = [87, 270, 453];

const IN_PATHS = COLUMNS.flatMap((center, column) =>
  [0, 1, 2, 3, 4].map((j) => {
    const xs = center + (j - 2) * 26;
    const d = `M${xs} 0 C ${xs} ${50 + j * 4}, ${NODE.x + (xs - NODE.x) * 0.12} ${40 + j * 3}, ${NODE.x} ${NODE.y}`;
    return { d, index: column * 5 + j };
  }),
);
const OUT_PATHS = Array.from({ length: 9 }, (_, m) => {
  const xe = 40 + m * 57.5;
  return { d: `M${NODE.x} 148 C ${NODE.x} 176, ${xe} 160, ${xe} ${H}`, index: m };
});
/** Post fragments ride six of the incoming threads into the mark. */
const FRAGMENTS = [1, 3, 6, 8, 11, 13];

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
      <div className="hero-funnel" aria-hidden="true">
        <svg viewBox={`0 0 ${W} ${H}`}>
          <defs>
            <linearGradient id="fn-in" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="100">
              <stop offset="0" stopColor="#dea777" stopOpacity="0.15" />
              <stop offset="1" stopColor="#f0be91" stopOpacity="0.9" />
            </linearGradient>
            <linearGradient
              id="fn-out"
              gradientUnits="userSpaceOnUse"
              x1="0"
              y1="148"
              x2="0"
              y2={H}
            >
              <stop offset="0" stopColor="#f0be91" stopOpacity="0.9" />
              <stop offset="1" stopColor="#dea777" stopOpacity="0.25" />
            </linearGradient>
            <radialGradient id="fn-glow">
              <stop offset="0" stopColor="#dea777" stopOpacity="0.28" />
              <stop offset="1" stopColor="#dea777" stopOpacity="0" />
            </radialGradient>
          </defs>
          <ellipse
            className="fn-glow"
            cx={NODE.x}
            cy={NODE.y + 20}
            rx="150"
            ry="90"
            fill="url(#fn-glow)"
          />
          {IN_PATHS.map(({ d, index }) => (
            <path
              key={`in-${index}`}
              className="fn-thread fn-in"
              pathLength={1}
              d={d}
              style={{ "--i": index } as CSSProperties}
            />
          ))}
          {IN_PATHS.map(({ d, index }) => (
            <path
              key={`streak-${index}`}
              className="fn-streak"
              pathLength={1}
              d={d}
              style={{ "--i": index } as CSSProperties}
            />
          ))}
          {FRAGMENTS.map((pathIndex, i) => (
            <g
              key={`frag-${pathIndex}`}
              className="fn-frag"
              style={
                {
                  offsetPath: `path("${IN_PATHS[pathIndex].d}")`,
                  "--i": i,
                } as CSSProperties
              }
            >
              <rect x="-17" y="-10" width="34" height="20" rx="5" />
              <path d="M-10 -3.5H10M-10 3H3" />
            </g>
          ))}
          {OUT_PATHS.map(({ d, index }) => (
            <path
              key={`out-${index}`}
              className="fn-thread fn-out"
              pathLength={1}
              d={d}
              style={{ "--i": index } as CSSProperties}
            />
          ))}
          {OUT_PATHS.map(({ d, index }) => (
            <path
              key={`out-streak-${index}`}
              className="fn-streak fn-streak-out"
              pathLength={1}
              d={d}
              style={{ "--i": index } as CSSProperties}
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
      <span className="hero-enrich" aria-hidden="true">
        <Image src={src("sectors-mark")} alt="" width={16} height={16} />
        Enriched by Sectors
        <i />
      </span>
    </div>
  );
}
