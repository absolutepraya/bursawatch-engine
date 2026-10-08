import Image from "next/image";
import type { ReactNode } from "react";
import {
  FORUM_TAG_LABEL,
  src,
  type FeedMessage,
  type ForumPost,
  type ForumTag,
  type PriceRow,
} from "@/lib/landing-content";

/** Static recreations of real Bursawatch Discord deliveries. Never live data. */

export function DiscordWindow({
  title,
  label,
  children,
  className = "",
  scrollable = false,
}: {
  title: ReactNode;
  label: string;
  children: ReactNode;
  className?: string;
  scrollable?: boolean;
}) {
  return (
    <figure className={`dc-window ${className}`} aria-label={label}>
      <div className="dc-channel">{title}</div>
      {scrollable ? (
        <div className="dc-scroll" data-scrollable tabIndex={0} role="region" aria-label={label}>
          {children}
        </div>
      ) : (
        <div className="dc-scroll">{children}</div>
      )}
    </figure>
  );
}

function BotHeader({ time, via }: { time: string; via?: string }) {
  return (
    <div className="dc-head">
      <Image className="dc-avatar" src="/landing/bot-avatar.png" alt="" width={40} height={40} />
      <div>
        <span className="dc-bot">Bursawatch</span>
        <span className="dc-app">APP</span>
        <span className="dc-time">{time}</span>
        {via ? <span className="dc-via">· {via}</span> : null}
      </div>
    </div>
  );
}

export function SourceIcon({ name, size = 20 }: { name: string; size?: number }) {
  return <Image className="dc-src" src={src(name)} alt="" width={size} height={size} />;
}

export function PriceBlock({
  last,
  rows,
  cap,
  label = "Harga terakhir (IDR)",
}: {
  last: string;
  rows: PriceRow[];
  cap?: string;
  label?: string;
}) {
  return (
    <div className="dc-price">
      <div className="dc-price-head">
        <span>
          {label}: <b>{last}</b>
        </span>
        {cap ? (
          <span>
            Kapitalisasi pasar: <b>{cap}</b>
          </span>
        ) : null}
      </div>
      <ul>
        {rows.map((row) => (
          <li key={row.label}>
            <Image src={src(row.tone === "up" ? "green" : "red")} alt="" width={16} height={16} />
            {row.label}: <b>{row.value}</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

const SENTIMENT_GLYPH = { up: "\u25B2", down: "\u25BC", flat: "\u25CF" } as const;

/** Sector from Sectors, analyst consensus and a sentiment read (samples are marked "contoh"). */
export function SectorsCard({ sector, consensus, sentiment }: NonNullable<FeedMessage["sectors"]>) {
  return (
    <div className="dc-sectors-card" data-tone={sentiment.tone}>
      <Image className="dc-sectors-ico" src={src("sectors-mark")} alt="" width={28} height={28} />
      <dl>
        <div>
          <dt>Sektor</dt>
          <dd>{sector}</dd>
        </div>
        <div className="dc-sectors-cons">
          <dt>Konsensus analis</dt>
          <dd>
            {"\u25B2"} {consensus.rating} <span>({consensus.detail})</span>
          </dd>
        </div>
        <div className="dc-sectors-sent">
          <dt>Sentimen</dt>
          <dd>
            {SENTIMENT_GLYPH[sentiment.tone]} {sentiment.label}
          </dd>
        </div>
      </dl>
      <em className="dc-sectors-sample">contoh</em>
    </div>
  );
}

/** Marks an analysis part that is computed with Sectors data. */
export function SectorsBadge({ label }: { label: string }) {
  return (
    <p className="dc-text dc-sectors-badge">
      <Image className="dc-sectors-ico" src={src("sectors-mark")} alt="" width={20} height={20} />
      <span>
        Sectors <i>· {label}</i>
      </span>
    </p>
  );
}

export function BotMessage({
  time,
  via,
  source,
  title,
  children,
  className = "",
}: {
  time: string;
  via?: string;
  source?: string;
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <article className={`dc-msg ${className}`.trim()}>
      <BotHeader time={time} via={via} />
      <div className="dc-body">
        <h3 className="dc-title">
          {source ? <SourceIcon name={source} /> : null}
          {title}
        </h3>
        {children}
      </div>
    </article>
  );
}

export function FeedItem({ message }: { message: FeedMessage }) {
  return (
    <BotMessage time={message.time} via={message.via} source={message.source} title={message.title}>
      {message.author ? (
        <div className="dc-author">
          <span className="dc-author-av">
            <Image src={message.author.avatar} alt="" width={20} height={20} />
            {message.author.badge ? (
              <Image
                className="dc-badge"
                src={message.author.badge}
                alt=""
                width={10}
                height={10}
              />
            ) : null}
          </span>
          {message.author.name}
        </div>
      ) : null}
      <p className="dc-text">
        <i>(Ringkasan)</i> {message.summary}
      </p>
      {message.price ? <PriceBlock {...message.price} cap={message.cap} /> : null}
      {message.sectors ? <SectorsCard {...message.sectors} /> : null}
      {message.image ? (
        <Image
          className="dc-img"
          src={message.image.src}
          alt={message.image.alt}
          width={message.image.width}
          height={message.image.height}
          sizes="(max-width: 700px) 80vw, 360px"
        />
      ) : null}
    </BotMessage>
  );
}

const TAG_ICON: Record<ForumTag, ReactNode> = {
  primary: (
    <>
      <path d="M6 1h8l-2 6H8z" fill="#3B82F6" />
      <circle cx="10" cy="13" r="6" fill="#F5B32F" />
    </>
  ),
  support: (
    <>
      <path d="M6 1h8l-2 6H8z" fill="#3B82F6" />
      <circle cx="10" cy="13" r="6" fill="#B8C0CC" />
    </>
  ),
  below: <path d="M3 5h14L10 17z" fill="#F23F43" />,
  above: <path d="M10 3l7 12H3z" fill="#2EE65F" />,
  zone: <rect x="4" y="4" width="12" height="12" fill="#F5D90A" />,
  onSupport: <rect x="4" y="4" width="12" height="12" fill="#F5D90A" />,
  resolved: <path d="M3 10l4.5 4.5L17 5" fill="none" stroke="#4A9BF5" strokeWidth="2.6" />,
  stop: <circle cx="10" cy="10" r="6" fill="#F23F43" />,
  tp1: (
    <>
      <circle cx="10" cy="10" r="7" fill="#2EE65F" />
      <path d="M6.5 10.2l2.4 2.4 4.6-4.8" fill="none" stroke="#04210d" strokeWidth="2" />
    </>
  ),
};

export function ForumTagChip({ tag }: { tag: ForumTag }) {
  return (
    <span className="dc-tag">
      <svg viewBox="0 0 20 20" aria-hidden="true">
        {TAG_ICON[tag]}
      </svg>
      {FORUM_TAG_LABEL[tag]}
    </span>
  );
}

export function ForumCard({ post, active = false }: { post: ForumPost; active?: boolean }) {
  return (
    <li className="dc-post" data-active={active || undefined}>
      <div>
        <div className="dc-tags">
          {post.tags.map((tag) => (
            <ForumTagChip key={tag} tag={tag} />
          ))}
        </div>
        <p className="dc-post-title">
          {post.ticker} - {post.date}
        </p>
        <p className="dc-post-by">
          <span>Bursawatch</span>: <SourceIcon name={post.source} size={16} /> {post.ticker}:
        </p>
        <p className="dc-post-meta">
          {post.replies} balasan · {post.ago}
        </p>
      </div>
      <Image
        className="dc-thumb"
        src={post.image}
        alt={`Chart ${post.ticker}`}
        width={160}
        height={92}
        sizes="160px"
      />
    </li>
  );
}
