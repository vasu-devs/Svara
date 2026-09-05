/** @type {import('next').NextConfig} */
// GH_PAGES=1 → static export under the /Svara project path (GitHub Pages).
// Unset (default) → normal Next app for Vercel (served at the domain root).
const isGh = process.env.GH_PAGES === "1";

const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_STATIC_EXPORT: isGh ? "1" : "0",
    NEXT_PUBLIC_BASE_PATH: isGh ? "/Svara" : "",
  },
  // Server routes are named `*.node.ts` and are only treated as routes when we
  // are NOT exporting. A static export cannot contain a dynamic route handler
  // at all - Next fails the whole build with "cannot be used with output:
  // export" - which would take down the Pages deploy along with it. Excluding
  // the extension is what keeps the two targets independent: Vercel gets the
  // live visitor counter, Pages quietly ships without one.
  pageExtensions: isGh
    ? ["ts", "tsx"]
    : ["ts", "tsx", "node.ts"],
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
