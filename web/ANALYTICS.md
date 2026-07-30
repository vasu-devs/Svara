# Live numbers on the site

Two different counters, deliberately built on two different things.

## Downloads — live now, nothing to configure

Read straight from the GitHub Releases API (`lib/stats.ts`). It is public and
CORS-enabled, so the browser fetches it directly. No token, no backend, no
Upstash — and it works on the static GitHub Pages build.

It is also the **authoritative** number. GitHub counts every asset fetch,
including ones that never touch this site: someone landing on the Releases
page, or an existing install's auto-updater pulling the new build. A counter we
incremented on our own download button would measure *button clicks* — a
smaller, different number that we would then be labelling "downloads".

Only `Svara-X.Y.Z.exe` assets are counted. `cuda-runtime.zip` is a one-time
dependency, not a download of the app, and including it would inflate the
figure.

Cached in `sessionStorage` for 30 minutes: GitHub allows 60 unauthenticated
requests per hour per IP, and a visitor clicking around should not spend them.

If the call fails — rate limited, offline, GitHub down — the site shows the
static stat instead of a `0`. A confident wrong number is worse than no number.

## Visitors — needs Upstash **and** a server deployment

This one genuinely needs somewhere to write, so it cannot work on GitHub Pages.

### Why it is not just "add an API route"

The site builds for **two targets** from one codebase:

| Target | Command | Output |
|---|---|---|
| GitHub Pages | `GH_PAGES=1 npm run build` | `output: "export"` — fully static |
| Vercel | `npm run build` | normal server build |

A static export **cannot contain a dynamic route handler**. Next fails the
entire build:

```
Error: export const dynamic = "force-dynamic" on page "/api/visits"
cannot be used with "output: export"
```

That is a red deploy for the live site, caused by adding one file. So server
routes are named **`route.node.ts`**, and `pageExtensions` in `next.config.mjs`
only counts that extension when *not* exporting:

```js
pageExtensions: isGh ? ["ts", "tsx"] : ["ts", "tsx", "node.ts"]
```

Pages never sees the route; Vercel does. `tests/test_site_analytics.py` locks
this in, including a check that no plain `route.ts` sneaks in later.

### Turning it on

1. Create a Redis database at [console.upstash.com](https://console.upstash.com).
2. Add these to **Vercel → Project → Settings → Environment Variables**
   (never to a file in this repo):

   | Variable | Where to find it |
   |---|---|
   | `UPSTASH_REDIS_REST_URL` | Upstash console → REST API |
   | `UPSTASH_REDIS_REST_TOKEN` | same page — this has **write access** |
   | `VISIT_SALT` | any long random string you invent |

3. Redeploy.

Until then `/api/visits` returns `501 {configured: false}` and the site simply
omits the visitor line. Nothing breaks, nothing logs, no placeholder appears.

> **The token must stay server-side.** `route.node.ts` is a server route, so
> reading `process.env` there never reaches the browser. Do not move it into a
> client component or rename it to `NEXT_PUBLIC_*` — that ships a credential
> with write access to your Redis to every visitor, who can then inflate or
> delete your numbers. There is a test for this.

### What is stored about a visitor

Nothing that identifies them.

- **No cookie**, and no ID is returned, so nobody can be followed between
  sessions.
- Uniqueness uses a **HyperLogLog** (`PFADD`/`PFCOUNT`) — a ~12 KB probabilistic
  sketch, not a list. It answers *roughly how many* and cannot answer *was this
  person here*, because individual entries are not retained.
- The value fed into it is `SHA-256(day | salt | IP | user-agent)`, and the day
  component **rolls every 24 hours**. Yesterday's hashes cannot be recomputed,
  so records are unlinkable across days by construction.

### This does not change what the app promises

`PRIVACY.md` says the desktop app has *"no analytics endpoint, no crash
reporter — not disabled by default, absent."* That is about **Svara itself**,
and it stays exactly true: none of this lives in `mywhisper/`, and the app makes
no request to any of it. `test_site_analytics.py` fails the build if the words
`upstash` or `analytics` ever appear in the Python package.

Website traffic measurement and desktop telemetry are different promises. Only
the first one is happening here.
