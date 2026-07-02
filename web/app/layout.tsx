import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const sans = Plus_Jakarta_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700", "800"], variable: "--font-sans", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || "https://vasu-devs.github.io/Svara"),
  title: "Svara · Speak. It's written. On your own machine.",
  description: "Svara floats over any app and writes down what you say, live, on your own GPU. Local, free, private voice dictation for Windows.",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "Svara · Speak. It's written.",
    description: "A voice-dictation overlay that writes your words at the cursor, in any app. Nothing leaves your GPU.",
    images: ["/og.svg"], type: "website",
  },
};
export const viewport: Viewport = { themeColor: "#050506" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
