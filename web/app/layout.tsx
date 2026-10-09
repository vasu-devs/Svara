import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Newsreader, Geist_Mono, Tiro_Devanagari_Sanskrit } from "next/font/google";
import "./globals.css";

// Two voices. Newsreader, with its optical-size axis, sets the transcript:
// the words you spoke, as a manuscript. Bricolage is the interface voice:
// wordmark, buttons. Geist Mono sets every note, number and timecode. Tiro
// exists only for the Devanagari mark.
const serif = Newsreader({ subsets: ["latin"], axes: ["opsz"], style: ["normal", "italic"], variable: "--font-serif", display: "swap" });
const display = Bricolage_Grotesque({ subsets: ["latin"], axes: ["opsz", "wdth"], variable: "--font-display", display: "swap" });
const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-mono", display: "swap" });
const deva = Tiro_Devanagari_Sanskrit({ subsets: ["devanagari"], weight: "400", variable: "--font-deva", display: "swap" });

const BASE = process.env.NEXT_PUBLIC_BASE_PATH || "";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://vasu-devs.github.io/Svara"),
  title: "Svara — private voice dictation for Windows",
  description: "Double-tap a key and speak. Svara types what you say at the cursor in any app, using Whisper on your own machine. No uploads, no account, no subscription. Free and open source.",
  icons: { icon: `${BASE}/favicon.svg` },
  openGraph: {
    title: "Svara — private voice dictation for Windows",
    description: "Talk into any app. Nothing leaves your PC. Free, open source, offline.",
    images: [{ url: `${BASE}/og.png`, width: 1200, height: 630 }], type: "website",
  },
};
export const viewport: Viewport = { themeColor: "#100e0c" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${display.variable} ${mono.variable} ${deva.variable}`}>
      <body>{children}</body>
    </html>
  );
}
