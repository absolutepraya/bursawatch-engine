import type { CreateAutomationInput } from "@/lib/types";

type BriefPreferences = Pick<CreateAutomationInput, "language" | "tone">;

// Preview copy only. Production briefs will come from the Hermes integration.
const copy = {
  en: {
    concise: "The daily price change passed your threshold. Review the next closing price and company announcements for context.",
    beginner: "This stock moved more in one day than the limit you set. That tells you the size of the move, not its cause. Check company announcements before drawing a conclusion.",
    analyst: "The daily close-to-close move exceeded the configured threshold. Assess follow-through at the next close and check issuer disclosures. This price signal does not establish a fundamental catalyst.",
  },
  id: {
    concise: "Perubahan harga harian melewati batas yang kamu atur. Cek harga penutupan berikutnya dan pengumuman perusahaan untuk konteksnya.",
    beginner: "Harga saham ini bergerak lebih besar dari batas harian yang kamu tentukan. Angka ini menunjukkan besar perubahan, bukan penyebabnya. Baca pengumuman perusahaan sebelum mengambil kesimpulan.",
    analyst: "Perubahan harga antarpenutupan melampaui ambang yang ditetapkan. Evaluasi kelanjutan pergerakan pada penutupan berikutnya dan periksa keterbukaan informasi emiten. Sinyal harga ini belum menjelaskan katalis fundamental.",
  },
};

export function briefPreviewText({ language, tone }: BriefPreferences) {
  return copy[language][tone];
}
