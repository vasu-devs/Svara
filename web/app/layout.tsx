import type { Metadata, Viewport } from "next";
import { Syne, Hanken_Grotesk, Space_Mono } from "next/font/google";
import "./globals.css";

const display = Syne({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-display", display: "swap" });
const body = Hanken_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-body", display: "swap" });
const mono = Space_Mono({ subsets: ["latin"], weight: ["400", "700"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://vasu-devs.github.io/Svara"),
  title: "Svara · The spoken word, written on your own machine",
  description: "Svara writes down everything you say, instantly, on your own GPU. Local, free, private voice dictation for Windows. No cloud, no account.",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "Svara · The spoken word, written on your own machine",
    description: "Speak in any app. Your words are written at the cursor. Nothing leaves your GPU.",
    images: ["/og.svg"], type: "website",
  },
};
export const viewport: Viewport = { themeColor: "#f4f0e6" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
