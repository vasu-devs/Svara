import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Schibsted_Grotesk, Geist_Mono, Tiro_Devanagari_Sanskrit } from "next/font/google";
import "./globals.css";

// Three roles, one voice. Bricolage carries the headlines (its optical-size
// axis gives display sizes real character), Schibsted does the reading,
// Geist Mono sets every number and label. Tiro exists only for the Devanagari
// wordmark - system fallbacks render स्वर in whatever the OS has lying about.
const display = Bricolage_Grotesque({ subsets: ["latin"], axes: ["opsz", "wdth"], variable: "--font-display", display: "swap" });
const body = Schibsted_Grotesk({ subsets: ["latin"], variable: "--font-body", display: "swap" });
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
    images: [`${BASE}/og.svg`], type: "website",
  },
};
export const viewport: Viewport = { themeColor: "#edebe6" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable} ${deva.variable}`}>
      <body>{children}</body>
    </html>
  );
}
