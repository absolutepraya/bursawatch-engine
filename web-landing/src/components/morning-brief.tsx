import Image from "next/image";
import { BotMessage, DiscordWindow, PriceBlock, SectorsBadge } from "@/components/discord";
import { BRIEF, src, type PriceTone } from "@/lib/landing-content";

/** The Bursawatch Pagi preview: one brief and two rotation images, 7 Oct 2026 data from the preview run. */

function Emoji({ name }: { name: string }) {
  return <Image className="dc-em" src={src(name)} alt="" width={18} height={18} />;
}

const IMAGES = {
  "ihsg-real-yahoo": { width: 1600, height: 1160 },
  "sector-rotation": { width: 1800, height: 1149 },
  "konglo-rotation": { width: 1800, height: 1662 },
} as const;

function BriefImage({ file, alt }: { file: keyof typeof IMAGES; alt: string }) {
  return (
    <Image
      className="dc-img brief-img"
      src={`/landing/brief/${file}.png`}
      alt={alt}
      width={IMAGES[file].width}
      height={IMAGES[file].height}
      sizes="(max-width: 700px) 85vw, 520px"
    />
  );
}

function Rotation({
  time,
  emoji,
  title,
  badge,
  image,
}: {
  time: string;
  emoji: string;
  title: string;
  badge: string;
  image: { file: keyof typeof IMAGES; alt: string };
}) {
  return (
    <BotMessage time={time} title={`${emoji} ${title}: ${BRIEF.date}`}>
      <SectorsBadge label={badge} />
      <BriefImage {...image} />
    </BotMessage>
  );
}

const TONE_EMOJI: Record<PriceTone, string> = { up: "green", down: "red" };

export function MorningBrief() {
  return (
    <DiscordWindow
      className="lp-brief-card"
      label="Contoh morning brief Bursawatch Pagi"
      title={<># morning-brief</>}
      scrollable
    >
      <BotMessage time="Rabu 08.00" title={`🌇 BURSAWATCH PAGI: ${BRIEF.date}`}>
        <PriceBlock
          label="Penutupan IHSG terakhir (IDR)"
          last={BRIEF.close.last}
          rows={BRIEF.close.rows}
        />
        <SectorsBadge label="outlook IHSG" />
        <p className="dc-text">
          <b>Outlook IHSG:</b> {BRIEF.outlook}
        </p>
        <p className="dc-text dc-subhead">
          <b>Pasar global:</b>
        </p>
        <ul className="dc-quotes">
          {BRIEF.global.map((quote) => (
            <li key={quote.name}>
              <Emoji name={quote.emoji} /> {quote.name}: {quote.change}{" "}
              <Emoji name={TONE_EMOJI[quote.tone]} />
            </li>
          ))}
        </ul>
        <p className="dc-text dc-subhead">
          <b>Agenda Ekonomi Indonesia</b> <span className="dc-link">[BPS]</span>
        </p>
        <ul className="dc-list">
          {BRIEF.agenda.map(([what, when]) => (
            <li key={what}>
              {what} - {when}
            </li>
          ))}
        </ul>
        <BriefImage
          file="ihsg-real-yahoo"
          alt="Chart harian IHSG dengan rata-rata bergerak MA 10, 20, 50, 100 dan RSI 14 di 43"
        />
      </BotMessage>
      <Rotation
        time="Rabu 08.00"
        emoji="🏭"
        title="ROTASI SEKTOR"
        badge="rotasi sektor"
        image={{
          file: "sector-rotation",
          alt: "Rotasi sektor: Energy dan Technology di kuadran Leading, Basic Materials dan Properties & Real Estate Improving, tiga sektor Weakening dan tiga Lagging, dengan tabel kekuatan dan momentum",
        }}
      />
      <Rotation
        time="Rabu 08.00"
        emoji="🐉"
        title="ROTASI KONGLO"
        badge="rotasi konglo"
        image={{
          file: "konglo-rotation",
          alt: "Rotasi konglo: empat grup Leading, lima Improving, satu Weakening dan enam Lagging, dengan tabel kekuatan dan momentum",
        }}
      />
    </DiscordWindow>
  );
}
