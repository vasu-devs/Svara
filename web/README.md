# Svara — web (Next.js)

The interactive landing site for Svara. Next.js 14 (App Router) + Framer Motion,
with a live canvas engine that renders the app's real visualizers.

Highlights:
- Hero pill you can **drag and fling** (spring physics), with **cursor-reactive** ribbons
- **Scroll-driven showcase** that scrubs through all eight visualizers
- **Tap-to-recolor** theming that morphs the whole page accent
- Magnetic buttons, spotlight cards, count-up stats, live typing demo

## Develop

```bash
npm install
npm run dev      # http://localhost:3000
npm run build    # production build
npm run start    # serve the production build
```

## Deploy to Vercel

1. Push this repo to GitHub (already at github.com/vasu-devs/Svara).
2. In Vercel, "Add New Project" and import the repo.
3. **Set the Root Directory to `web`** (this app lives in a subfolder).
4. Framework preset auto-detects Next.js. Click Deploy.

Optional: set `NEXT_PUBLIC_SITE_URL` to your Vercel domain so Open Graph image
URLs resolve absolutely.

The simpler static version of the site also lives in `../docs` and is served via
GitHub Pages at https://vasu-devs.github.io/Svara/.
