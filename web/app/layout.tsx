import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Manrope, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const display = Bricolage_Grotesque({ subsets: ["latin"], weight: ["500", "600", "700", "800"], variable: "--font-display", display: "swap" });
const body = Manrope({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-body", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["500", "600"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://svara.vercel.app"),
  title: "Svara · Private voice dictation that runs on your own machine",
  description: "Svara turns speech into text in any app, running entirely on your own GPU. Local, free, instant, open source. A private alternative to cloud dictation.",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "Svara · Private voice dictation, on your machine",
    description: "Speak in any app. Text appears at your cursor. Nothing leaves your GPU. Free and open source.",
    images: ["/og.svg"], type: "website",
  },
};
export const viewport: Viewport = { themeColor: "#07080b" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
