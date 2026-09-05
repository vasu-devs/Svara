/**
 * Live visitor counter, backed by Upstash Redis.
 *
 * Runs ONLY on a server deployment (Vercel). The GitHub Pages build is a
 * static export and drops this route entirely - see the `isGh` branch in
 * next.config.mjs, which is why this file must never be imported from a page.
 * The client calls it, notices a non-OK response, and hides the stat.
 *
 * Privacy. This is the website, not the app: Svara itself still sends nothing
 * anywhere, and PRIVACY.md's "no analytics endpoint, no telemetry" claim is
 * about the desktop client. Even so this endpoint stores no visitor:
 *
 *   - No cookie is set and no ID is handed back, so nobody can be followed
 *     between sessions.
 *   - Uniqueness uses a HyperLogLog, which keeps a ~12 KB sketch rather than a
 *     list of visitors. It can answer "roughly how many" and cannot answer
 *     "was this person here", because the individual entries are not retained.
 *   - The value fed to it is a SHA-256 of IP + user-agent + a salt that ROLLS
 *     DAILY. Yesterday's hashes cannot be recomputed or matched, so the record
 *     is unlinkable across days by construction.
 *
 * Upstash credentials come from the environment and are never bundled: this is
 * a server route, so the token stays server-side. Do not move these reads into
 * a client component or a NEXT_PUBLIC_ variable - that would ship a token with
 * write access to your Redis to every visitor.
 */

const URL_ = process.env.UPSTASH_REDIS_REST_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN;

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TOTAL = "svara:visits:total";
const UNIQUE = "svara:visits:unique";

/** Upstash's REST API takes a command as a path segment array. */
async function redis(...cmd: (string | number)[]): Promise<unknown> {
  const res = await fetch(`${URL_}/${cmd.map(encodeURIComponent).join("/")}`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`upstash ${res.status}`);
  return (await res.json()).result;
}

/** A per-visitor value that stops being computable tomorrow. */
async function dailyFingerprint(req: Request): Promise<string> {
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0].trim() ?? "";
  const ua = req.headers.get("user-agent") ?? "";
  const day = new Date().toISOString().slice(0, 10);
  const salt = process.env.VISIT_SALT ?? "svara";
  const data = new TextEncoder().encode(`${day}|${salt}|${ip}|${ua}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest).slice(0, 16))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export async function POST(req: Request) {
  // Not configured is a normal state, not an error: the site is fully
  // functional without a counter, and must not log noise on every request.
  if (!URL_ || !TOKEN) {
    return Response.json({ configured: false }, { status: 501 });
  }
  try {
    const [total] = await Promise.all([
      redis("INCR", TOTAL),
      redis("PFADD", UNIQUE, await dailyFingerprint(req)),
    ]);
    const unique = await redis("PFCOUNT", UNIQUE);
    return Response.json({
      configured: true,
      visits: Number(total) || 0,
      unique: Number(unique) || 0,
    });
  } catch {
    // Redis being down must never take the marketing site with it.
    return Response.json({ configured: false }, { status: 503 });
  }
}

/** Read-only, for a dashboard or a curious visitor. Does not count itself. */
export async function GET() {
  if (!URL_ || !TOKEN) {
    return Response.json({ configured: false }, { status: 501 });
  }
  try {
    const [visits, unique] = await Promise.all([
      redis("GET", TOTAL),
      redis("PFCOUNT", UNIQUE),
    ]);
    return Response.json({
      configured: true,
      visits: Number(visits) || 0,
      unique: Number(unique) || 0,
    });
  } catch {
    return Response.json({ configured: false }, { status: 503 });
  }
}
