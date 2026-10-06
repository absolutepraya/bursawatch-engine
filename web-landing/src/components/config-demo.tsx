import Image from "next/image";
import { src } from "@/lib/landing-content";

/** Illustrations of the coming workspace settings. Not a working control. */

function Toggle({ label, on, fresh = false }: { label: string; on: boolean; fresh?: boolean }) {
  return (
    <span className="cfg-row" data-fresh={fresh || undefined}>
      {label}
      <span className="cfg-toggle" data-on={on || undefined}>
        <i />
      </span>
    </span>
  );
}

function NightSummary() {
  return (
    <>
      <Toggle label="Morning brief, 08.00" on />
      <Toggle label="Ringkasan malam, 21.00" on fresh />
    </>
  );
}

function Analysts() {
  return (
    <>
      <span className="cfg-row">
        <Image src={src("tuntun")} alt="" width={26} height={26} /> Tuntun Sekuritas
        <span className="cfg-check">✓</span>
      </span>
      <span className="cfg-row cfg-add" data-fresh>
        <Image src={src("rickyho1989")} alt="" width={26} height={26} /> Ricky Ho
        <span className="cfg-added">+ Ditambah</span>
      </span>
    </>
  );
}

function SendTime() {
  return (
    <span className="cfg-time">
      <span className="cfg-label">Jam kirim morning brief</span>
      <span>
        <s>08.00</s> <b>06.30</b>
      </span>
    </span>
  );
}

function Weekly() {
  return (
    <>
      <span className="cfg-seg">
        <span>Harian</span>
        <span data-selected>Mingguan</span>
      </span>
      <span className="cfg-label">Seminggu sekali aja.</span>
    </>
  );
}

const ITEMS = [
  {
    question: "Mau semua beritanya dirangkum tiap malem aja?",
    summary: "Ringkasan malam jam 21.00 dinyalakan.",
    Scene: NightSummary,
  },
  {
    question: "Mau mantau analis favoritmu?",
    summary: "Ricky Ho ditambahkan ke daftar sumber.",
    Scene: Analysts,
  },
  {
    question: "Mau ganti jam kirimnya?",
    summary: "Jam kirim morning brief diganti dari 08.00 ke 06.30.",
    Scene: SendTime,
  },
  {
    question: "Males baca tiap hari?",
    summary: "Pengiriman diganti dari harian ke mingguan.",
    Scene: Weekly,
  },
];

export function ConfigDemo() {
  return (
    <ul className="lp-config-grid" data-seq>
      {ITEMS.map(({ question, summary, Scene }) => (
        <li key={question}>
          <h3>{question}</h3>
          <div className="cfg-ui" role="img" aria-label={`Contoh pengaturan: ${summary}`}>
            <Scene />
          </div>
          <p className="lp-bisa">BISA.</p>
        </li>
      ))}
    </ul>
  );
}
