/**
 * Live numbers for the site.
 *
 * Downloads come straight from the GitHub Releases API, not from a counter we
 * keep ourselves. Three reasons that is the right source:
 *
 *   1. It is authoritative. GitHub counts every asset fetch, including the many
 *      that never touch this site - people who land on the Releases page, or
 *      whose auto-updater pulls the new build. A counter incremented when our
 *      download button is clicked measures button clicks, which is a different
 *      and smaller number that we would then present as "downloads".
 *   2. It needs no credentials. The endpoint is public and CORS-enabled, so it
 *      works from a fully static GitHub Pages build, which is what this site
 *      is (next.config.mjs sets output: "export" under GH_PAGES).
 *   3. Nothing can be written to it. There is no token in the bundle to leak.
 *
 * Unique visitors are a different problem - they genuinely need somewhere to
 * write - and live in visits.ts.
 */

export type ReleaseStats = {
  downloads: number;
  latest: string | null;
};

const API = "https://api.github.com/repos/vasu-devs/Svara/releases";
const CACHE_KEY = "svara:releases";
const CACHE_MS = 30 * 60 * 1000; // GitHub allows 60 unauthenticated req/hour/IP

type Asset = { name: string; download_count: number };
type Release = { assets?: Asset[] };

/** Count the app itself. The CUDA runtime is a one-time dependency some users
 *  fetch, not a download of Svara, and counting it would inflate the figure. */
function tally(releases: Release[]): ReleaseStats {
  let downloads = 0;
  let latest: string | null = null;
  let best = [-1, -1, -1];

  for (const release of releases) {
    for (const asset of release.assets ?? []) {
      const match = /^Svara-(\d+)\.(\d+)\.(\d+)\.exe$/i.exec(asset.name);
      if (!match) continue;
      downloads += asset.download_count ?? 0;
      const version = [+match[1], +match[2], +match[3]];
      if (version.some((n, i) => n > best[i] && version.slice(0, i)
          .every((m, j) => m === best[j]))) {
        best = version;
        latest = version.join(".");
      }
    }
  }
  return { downloads, latest };
}

export async function fetchReleaseStats(): Promise<ReleaseStats | null> {
  if (typeof window === "undefined") return null;

  try {
    const cached = sessionStorage.getItem(CACHE_KEY);
    if (cached) {
      const { at, value } = JSON.parse(cached);
      if (Date.now() - at < CACHE_MS) return value as ReleaseStats;
    }
  } catch {
    // sessionStorage can throw in private modes; a cache miss is harmless.
  }

  try {
    const res = await fetch(API, {
      headers: { Accept: "application/vnd.github+json" },
    });
    // Rate limited, offline, or GitHub having a moment: show nothing rather
    // than a zero, because a confident "0 downloads" is worse than silence.
    if (!res.ok) return null;
    const value = tally(await res.json());
    try {
      sessionStorage.setItem(CACHE_KEY,
        JSON.stringify({ at: Date.now(), value }));
    } catch {
      /* ignore */
    }
    return value;
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ visits */

export type VisitStats = { visits: number; unique: number };

/**
 * Record this visit and read the running totals back.
 *
 * Returns null whenever there is no counter to talk to, which is the normal
 * case on the GitHub Pages build: that deployment is a static export with no
 * /api routes, so the call 404s and the UI simply omits the numbers. The same
 * null covers an unconfigured or unreachable Upstash, so a dead Redis can
 * never surface an error to a visitor.
 *
 * Fires once per tab. A reload counts again - it is a visit counter, not a
 * session counter - but the unique tally is deduplicated server-side.
 */
export async function recordVisit(): Promise<VisitStats | null> {
  if (typeof window === "undefined") return null;
  if (process.env.NEXT_PUBLIC_STATIC_EXPORT === "1") return null;
  try {
    const base = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
    const res = await fetch(`${base}/api/visits`, { method: "POST" });
    if (!res.ok) return null;                 // 501 unconfigured, 503 down, 404 static
    const data = await res.json();
    if (!data?.configured) return null;
    return { visits: data.visits ?? 0, unique: data.unique ?? 0 };
  } catch {
    return null;
  }
}
