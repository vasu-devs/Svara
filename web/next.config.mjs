/** @type {import('next').NextConfig} */
// GH_PAGES=1 → static export under the /Svara project path (GitHub Pages).
// Unset (default) → normal Next app for Vercel (served at the domain root).
const isGh = process.env.GH_PAGES === "1";

const nextConfig = {
  reactStrictMode: true,
  ...(isGh
    ? {
        output: "export",
        basePath: "/Svara",
        images: { unoptimized: true },
        trailingSlash: true,
      }
    : {}),
};

export default nextConfig;
