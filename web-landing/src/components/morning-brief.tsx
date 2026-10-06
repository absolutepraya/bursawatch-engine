import Image from "next/image";
import type { ReactNode } from "react";
import { BotMessage, DiscordWindow } from "@/components/discord";
import { BRIEF, src, type PriceTone } from "@/lib/landing-content";

/** The Bursawatch Pagi example: one brief and two rotation posts. Dummy figures. */

function Emoji({ name }: { name: string }) {
  return <Image className="dc-em" src={src(name)} alt="" width={18} height={18} />;
}

function BriefImage({ file, alt }: { file: string; alt: string }) {
  return (
    <Image
      className="dc-img brief-img"
      src={`/landing/brief/${file}.png`}
      alt={alt}
      width={1400}
      height={file === "ihsg-branded" ? 1225 : 894}
      sizes="(max-width: 700px) 85vw, 440px"
    />
  );
}

function Rotation({
  time,
  emoji,
  title,
  lead,
  rows,
  image,
}: {
  time: string;
  emoji: string;
  title: string;
  lead: ReactNode;
  rows: readonly (readonly [string, string, string])[];
  image: { file: string; alt: string };
}) {
  return (
    <BotMessage time={time} title={`${emoji} ${title}: ${BRIEF.date}`}>
      <p className="dc-text dc-note">{BRIEF.timing}</p>
      <p className="dc-text">{lead}</p>
      <ul className="dc-list">
        {rows.map(([name, phase, detail]) => (
          <li key={name}>
            <b>
              {name} · {phase}:
            </b>{" "}
            {detail}
          </li>
        ))}
      </ul>
      <p className="dc-text dc-note">{BRIEF.rotationBasis}</p>
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
      <BotMessage time="Senin 08.00" title={`🌇 BURSAWATCH PAGI: ${BRIEF.date}`}>
        <p className="dc-text dc-note">{BRIEF.timing}</p>
        <p className="dc-text">
          <b>IHSG: {BRIEF.verdict}</b> {BRIEF.scenario}
        </p>
        <p className="dc-text">
          <b>Yang diperhatikan:</b> {BRIEF.watch}
        </p>
        <p className="dc-text">
          <b>Rencana pantau:</b> {BRIEF.plan}
        </p>
        <p className="dc-text dc-subhead">
          <b>Pasar global</b>
        </p>
        <ul className="dc-quotes">
          {BRIEF.global.map((quote) => (
            <li key={quote.name}>
              <Emoji name={quote.emoji} /> {quote.name}: {quote.change}{" "}
              <Emoji name={TONE_EMOJI[quote.tone]} />
            </li>
          ))}
        </ul>
        <p className="dc-text dc-note">{BRIEF.snapshot}</p>
        <p className="dc-text dc-subhead">
          <b>Agenda Indonesia · 3 rilis berikutnya</b>
        </p>
        <ul className="dc-list">
          {BRIEF.agenda.map(([when, what, source]) => (
            <li key={what}>
              {when} · {what}. <span className="dc-link">(Sources: {source})</span>
            </li>
          ))}
        </ul>
        <BriefImage file="ihsg-branded" alt="Chart harian IHSG dengan RSI 14 di area 30" />
      </BotMessage>
      <Rotation
        time="Senin 08.00"
        emoji="🏭"
        title="ROTASI SEKTOR"
        lead={
          <>
            <b>Energy masih memimpin; Financials mulai mengejar.</b> Technology tetap unggul
            terhadap IHSG, tetapi momentumnya melemah.
          </>
        }
        rows={BRIEF.sectors}
        image={{
          file: "sector-rotation-dummy",
          alt: "Grafik rotasi sektor: kuadran Leading, Improving, Weakening dan Lagging",
        }}
      />
      <Rotation
        time="Senin 08.00"
        emoji="🐉"
        title="ROTASI KONGLO"
        lead={
          <>
            <b>Barito memimpin, Djarum membaik, Astra kehilangan momentum.</b> Ketiganya menunjukkan
            fase relatif yang berbeda terhadap IHSG.
          </>
        }
        rows={BRIEF.konglo}
        image={{
          file: "konglo-rotation-dummy",
          alt: "Grafik rotasi grup konglomerasi terhadap IHSG",
        }}
      />
    </DiscordWindow>
  );
}
