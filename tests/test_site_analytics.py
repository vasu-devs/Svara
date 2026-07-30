"""The website ships to two targets at once, and they disagree about servers.

  - GitHub Pages gets `GH_PAGES=1` -> output: "export", a fully static site.
    A static export CANNOT contain a dynamic route handler: Next fails the
    entire build with "cannot be used with output: export". Adding one file
    named app/api/<x>/route.ts is therefore enough to take the live site's
    deploy down, and nothing about writing that file looks dangerous.
  - Vercel gets a normal server build, where the same route is wanted.

The rule that keeps both alive: server routes are named `route.node.ts`, and
`pageExtensions` only counts that extension when we are not exporting. These
tests hold that rule in place, because the failure it prevents is a red deploy
rather than a visible bug in review.

Also covered: the analytics we added must not quietly become telemetry. The
counters are website-side; PRIVACY.md's promise that the desktop app has no
analytics endpoint has to keep being true.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_site_analytics -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


class TestBothBuildTargetsSurvive(unittest.TestCase):

    def config(self) -> str:
        return (WEB / "next.config.mjs").read_text(encoding="utf-8")

    def test_the_static_export_excludes_server_routes(self):
        cfg = self.config()
        self.assertIn("pageExtensions", cfg,
                      "without pageExtensions the export picks up API routes "
                      "and the GitHub Pages build fails outright")
        # Under GH_PAGES the list must NOT contain node.ts.
        match = re.search(r"pageExtensions:\s*isGh\s*\?\s*(\[[^\]]*\])", cfg)
        self.assertIsNotNone(match, "pageExtensions is no longer keyed on isGh")
        self.assertNotIn("node.ts", match.group(1),
                         "the static export would try to build the API route")

    def test_the_server_build_includes_them(self):
        cfg = self.config()
        tail = cfg.split("pageExtensions", 1)[1]
        self.assertIn("node.ts", tail,
                      "the Vercel build would silently ship without /api/visits")

    def test_no_route_file_bypasses_the_convention(self):
        # The whole guard rests on server routes being invisible to the export.
        # A plain route.ts anywhere under app/ defeats it.
        strays = [p for p in (WEB / "app").rglob("route.ts")]
        self.assertFalse(
            strays,
            f"{[str(p.relative_to(WEB)) for p in strays]} would break the "
            "GitHub Pages deploy. Name server routes route.node.ts instead.")

    def test_the_visits_route_exists_under_the_safe_name(self):
        self.assertTrue((WEB / "app" / "api" / "visits" / "route.node.ts").is_file())


class TestCountersStayHonest(unittest.TestCase):

    def stats(self) -> str:
        return (WEB / "lib" / "stats.ts").read_text(encoding="utf-8")

    def test_downloads_come_from_github_not_a_counter_we_keep(self):
        # A self-kept counter measures button clicks, and would undercount
        # every download that came from the Releases page or the updater.
        self.assertIn("api.github.com", self.stats(),
                      "download numbers must come from the authoritative source")

    def test_a_failed_fetch_shows_nothing_rather_than_zero(self):
        src = self.stats()
        self.assertIn("return null", src,
                      "a rate-limited API must not render a confident '0 downloads'")

    def test_no_upstash_token_is_exposed_to_the_browser(self):
        # The REST token has write access. In a client bundle it would let any
        # visitor tamper with or delete the counters.
        for path in WEB.rglob("*.ts*"):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            src = path.read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("NEXT_PUBLIC_UPSTASH", src,
                             f"{path.name} would ship the Redis token to clients")
            if path.name.endswith(".node.ts"):
                continue  # server-only file: reading the token here is correct
            self.assertNotIn("UPSTASH_REDIS_REST_TOKEN", src,
                             f"{path.name} is not a server route but reads the token")

    def test_credentials_are_not_committed(self):
        for name in (".env", ".env.local", ".env.production"):
            self.assertFalse((WEB / name).is_file(),
                             f"web/{name} must never be committed")

    def test_the_desktop_app_gained_no_telemetry(self):
        # PRIVACY.md's claim is about the app, and these counters are the site.
        # If analytics ever leaks into mywhisper/, that claim becomes false.
        for path in (ROOT / "mywhisper").rglob("*.py"):
            src = path.read_text(encoding="utf-8", errors="ignore").lower()
            for banned in ("upstash", "analytics", "telemetry_send"):
                self.assertNotIn(
                    banned, src,
                    f"mywhisper/{path.name} mentions {banned!r}; the desktop "
                    "app must keep sending nothing anywhere (PRIVACY.md)")


if __name__ == "__main__":
    unittest.main()
