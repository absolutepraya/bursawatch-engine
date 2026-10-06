import "@fontsource-variable/hanken-grotesk";
import "./globals.css";

import type { Metadata, Viewport } from "next";

export const metadata: Metadata = {
  title: {
    default: "Bursawatch: Know what changed",
    template: "%s · Bursawatch",
  },
  description:
    "Configure source-backed market workflows, review jobs and run history, and inspect published records.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark",
  themeColor: "#141615",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <body>{children}</body>
    </html>
  );
}
