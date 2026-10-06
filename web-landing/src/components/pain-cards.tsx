import Image from "next/image";
import { PAINS, TRUE_CLOSES, src } from "@/lib/landing-content";

/** Illustrative pain scenes. The accounts and offers are made up. */

function IgScene() {
  return (
    <div className="pain-ig">
      <Image
        src="/landing/pain/ig-2-ketr.jpg"
        alt="Postingan berita saham KETR di Instagram"
        width={1080}
        height={1350}
        sizes="(max-width: 700px) 70vw, 240px"
      />
      <span className="pain-ig-chip">
        <Image src="/landing/pain/ketr-logo.png" alt="" width={18} height={18} />
        KETR udah +11,0%
      </span>
    </div>
  );
}

function TelegramScene() {
  return (
    <div className="pain-tg">
      <p className="pain-tg-pin">
        <b>Pesan Tersemat</b> Cara gabung VIP: transfer, kirim bukti ke admin...
      </p>
      <div className="pain-tg-bubble">
        <b>VIP INSIDER A1</b>
        <span>SLOT VIP OKTOBER TINGGAL 5!</span>
        Sinyal A1 tiap pagi, akurasi 90%++. Cuma Rp1.500.000 / bulan 🔥🔥
        <small>👁 2,4 rb · 07.12</small>
      </div>
    </div>
  );
}

function KelasScene() {
  return (
    <div className="pain-kelas">
      <span className="pain-kelas-tier">DIAMOND + TOP G OFFLINE SUMMIT</span>
      <span className="pain-kelas-was">Rp 20.000.000</span>
      <span className="pain-kelas-now">Rp 7.200.000</span>
      <span className="pain-kelas-note">Hemat 70%. Slot terbatas!</span>
    </div>
  );
}

function XScene() {
  const max = Math.max(...TRUE_CLOSES);
  const min = Math.min(...TRUE_CLOSES);
  const points = TRUE_CLOSES.map((close, i) => {
    const x = (i / (TRUE_CLOSES.length - 1)) * 200;
    const y = 6 + (1 - (close - min) / (max - min)) * 58;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <div className="pain-x">
      <p>
        <b>Sahabat Cuan</b> <span>@sahabatcuan · 13 Jan</span>
      </p>
      <p>
        Artinya harga <em>$TRUE</em> udah masuk area spekulasi buat jualan. Target akhirnya 610 🚀
      </p>
      <div className="pain-x-chart">
        <span>
          <Image src="/landing/pain/true-logo.png" alt="" width={18} height={18} /> TRUE
        </span>
        <svg viewBox="0 0 200 70" role="img" aria-label="Harga TRUE naik ke 530 lalu jatuh ke 193">
          <polyline points={points} pathLength={1} fill="none" stroke="#F23F43" strokeWidth="2.4" />
        </svg>
        <span className="pain-x-drop">530 → 193</span>
      </div>
    </div>
  );
}

const SCENES = { ig: IgScene, telegram: TelegramScene, kelas: KelasScene, x: XScene };
const PLATFORM = { ig: "instagram", telegram: "telegram", kelas: null, x: "twitter" } as const;

export function PainCards() {
  return (
    <ol className="pain-grid" data-stagger>
      {PAINS.map((pain) => {
        const Scene = SCENES[pain.id];
        const platform = PLATFORM[pain.id];
        return (
          <li className="pain-card" key={pain.id}>
            <div className="pain-scene" aria-hidden={pain.id === "ig" ? undefined : true}>
              {platform ? (
                <Image
                  className="pain-platform"
                  src={src(platform)}
                  alt=""
                  width={22}
                  height={22}
                />
              ) : null}
              <Scene />
            </div>
            <h3>{pain.question}</h3>
            <p>
              <strong>{pain.hero}</strong> {pain.tail}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
