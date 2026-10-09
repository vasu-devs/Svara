# Svara web (Next.js)

The interactive landing site for Svara. Next.js 16 (App Router) + React 19,
with CSS transitions and a shared canvas animation engine. Requires Node.js 20.9+.

Highlights:
- A dark room, and the pill is the only light in it. The page is still a
  transcript: one dictation typeset as it lands, with proofreader's notes in
  the margin. It is set in bone on charcoal, and a warm light follows what
  you are reading; Svara's corrections glow amber as they happen.
- The first line types itself with the mistakes in ("Um, talk into, talk
  into any app"), the pill riding beside the caret the way the real one stays
  next to where you type, then the filler collapses and the pill settles into
  its slot. Double-tap Right Alt on the page to see it again.
- The Codex renders of this world sit inside the transcript as plates where
  the copy mentions them: the Alt key, the pill beside a heatsink, the
  unplugged cable, the strings, the real pill render, the real first-run
  window. Numbers from `BENCH.md`, the connection ledger from `PRIVACY.md`.
- It reacts to you. Your cursor is the torch: move it and the light in the
  room follows, stop and it drifts back to what you are reading. Click the
  pill and it hears you: a real level from your microphone, measured in the
  tab with Web Audio, drawn on the strings, never recorded or sent. Words
  glint under the cursor, plates tilt in 3D with a sliding highlight, and the
  download button leans toward the pointer with an amber glow.
- Hover a corrected word to see what was heard; hover a margin note to
  underline its words. Timecodes per paragraph; the score in the top bar
  keeps transcript time, words typed, and the zero bytes uploaded.
- Motion is GSAP: ScrollSmoother for inertia, ScrollTrigger for the word
  reveals, the light and the pill on the ticker. Reduced motion renders the
  finished transcript with the light off.

Type: Newsreader (the transcript, with its optical-size axis), Bricolage
Grotesque (the interface), Geist Mono (notes, numbers, timecodes), Tiro
Devanagari Sanskrit (the स्वर mark). Tokens live at the top of
`app/globals.css`; the copy and its interventions are the `BLOCKS` array in
`app/page.tsx`. The social preview is `public/og.png`.

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
