import { ExternalLink, MessageCircle, ShieldCheck } from "lucide-react";

import { INFORMATION_ONLY_DISCLAIMER } from "@/lib/safety";
import { briefPreviewText } from "@/lib/brief-copy";

export function WhatsAppPreview({
  symbol = "BBRI",
  destination = "+62 812 •••• 1847",
  language = "id",
  tone = "concise",
  compact = false,
}: {
  symbol?: string;
  destination?: string;
  language?: "id" | "en";
  tone?: "concise" | "beginner" | "analyst";
  compact?: boolean;
}) {
  const isIndonesian = language === "id";
  return (
    <aside
      className={compact ? "evidence-rail compact" : "evidence-rail"}
      aria-label="WhatsApp preview"
    >
      <div className="evidence-rail-header">
        <div>
          <p className="preview-channel">
            <MessageCircle aria-hidden="true" size={16} /> WhatsApp
          </p>
          <p className="destination">{destination}</p>
        </div>
        <span className="preview-label">Preview</span>
      </div>
      <div className="message-bubble">
        <p className="message-title">
          {symbol} · {isIndonesian ? "Ringkasan harian" : "Daily brief"}
        </p>
        <p>{briefPreviewText({ language, tone })}</p>
        <p>
          <strong>{isIndonesian ? "Pantau berikutnya:" : "Watch next:"}</strong>{" "}
          {isIndonesian
            ? "harga penutupan dan berita perusahaan terbaru."
            : "the next closing price and recent company announcements."}
        </p>
        <p className="disclaimer">
          {isIndonesian
            ? INFORMATION_ONLY_DISCLAIMER
            : "Information only, not investment advice. Review the cited sources and your own risk."}
        </p>
      </div>
      <div className="evidence-links">
        <p>
          <ShieldCheck aria-hidden="true" size={15} /> Daily prices from Sectors.
        </p>
        <a
          href="https://docs.sectors.app/api-references/v2/indonesia/transaction/daily"
          target="_blank"
          rel="noreferrer"
        >
          Sectors daily data <ExternalLink aria-hidden="true" size={14} />
        </a>
      </div>
    </aside>
  );
}
