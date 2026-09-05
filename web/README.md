# Svara web (Next.js)

The interactive landing site for Svara. Next.js 16 (App Router) + React 19,
with CSS transitions and a shared canvas animation engine. Requires Node.js 20.9+.

Highlights:
- A bounded draggable hero pill and cursor-reactive ribbons
- Three scripted dictation examples with playback, pause, replay, and progress
- Eight canvas visualizers, suspended when offscreen or the tab is hidden
- **Tap-to-recolor** theming that morphs the whole page accent
- Reduced-motion support, keyboard focus styles, and a mobile-friendly layout

## Develop

```bash
npm ci
npm run dev      # http://localhost:3000
npm run build    # production build
npm run start    # serve the production build
npm run typecheck # TypeScript validation (also exposed as the lint alias)
```

## Deploy to Vercel

1. Push this repo to GitHub (already at github.com/vasu-devs/Svara).
2. In Vercel, "Add New Project" and import the repo.
3. **Set the Root Directory to `web`** (this app lives in a subfolder).
4. Framework preset auto-detects Next.js. Click Deploy.

Optional: set `NEXT_PUBLIC_SITE_URL` to your Vercel domain so Open Graph image
URLs resolve absolutely.

For GitHub Pages, build with `GH_PAGES=1` (PowerShell:
`$env:GH_PAGES='1'; npm run build`). This exports the same site to `out/` under
the `/Svara` base path. Server-only visitor counting is excluded and never
requested by that build. The GitHub Actions deployment publishes `web/out`.

Google Fonts are downloaded at build time and served from the app afterwards.
An initial production build needs network access to Google's font service.
