import type { Metadata, Viewport } from "next";
import { Playfair_Display, Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const serif = Playfair_Display({ subsets: ["latin"], weight: ["400", "500", "600", "700"], style: ["normal", "italic"], variable: "--font-serif", display: "swap" });
const sans = Hanken_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://vasu-devs.github.io/Svara"),
  title: "Svara · Your voice, written like a melody.",
  description: "Svara transcribes in real time, entirely on your machine. No uploads. No servers. No fees. Local, free, private voice dictation for Windows.",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "Svara · Your voice, written like a melody.",
    description: "Double-tap a key and speak. Svara transcribes in real time, entirely on your machine.",
    images: ["/og.svg"], type: "website",
  },
};
export const viewport: Viewport = { themeColor: "#e7d2be" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
