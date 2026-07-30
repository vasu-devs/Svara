"""The first-run setup window, actually built.

This is the first thing anyone sees after double-clicking the exe, and it was
the last screen with no test at all - it could only be checked by installing
the app and watching. Two earlier bugs lived here precisely because of that:
the progress bar running backwards, and the window growing taller than the
screen so the Start button sat below the bottom edge.

The window is built in a subprocess (tests/_setup_probe.py). It constructs its
own `ctk.CTk()` root, and a second Tk root inside a process that already has
one is a reliable source of order-dependent flakiness; `_run_setup_ctk` also
ends in `mainloop()`, so the stub belongs somewhere it cannot leak into
another test.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_setup_screens -v
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "tests" / "_setup_probe.py"


def _probe(scaling: str = "1.333") -> dict:
    env = {**os.environ, "PROBE_SCALING": scaling, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run([sys.executable, str(PROBE)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=180, env=env)
    for line in reversed((proc.stdout or "").splitlines()):
        if line.strip().startswith("{"):
            return json.loads(line)
    raise AssertionError(
        f"probe produced no report (exit {proc.returncode})\n"
        f"stdout: {(proc.stdout or '')[-600:]}\nstderr: {(proc.stderr or '')[-600:]}")


try:
    import customtkinter  # noqa: F401
    import tkinter as _tk

    _r = _tk.Tk(); _r.destroy()
    CAN_RUN = True
except Exception:  # noqa: BLE001 — headless CI, or no customtkinter
    CAN_RUN = False


@unittest.skipUnless(CAN_RUN, "no display or customtkinter unavailable")
class TestFirstRunSetupWindow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = _probe()

    def test_the_window_builds_at_all(self):
        self.assertTrue(self.report.get("ok"),
                        f"setup window failed to build: "
                        f"{self.report.get('error')}\n{self.report.get('trace', '')}")

    def test_the_model_picker_offers_real_choices(self):
        # The whole point of the screen. If the list came back empty the user
        # would face a Start button and nothing to choose.
        texts = " ".join(self.report["texts"]).lower()
        found = [n for n in ("tiny", "base", "small", "distil", "large")
                 if n in texts]
        self.assertGreaterEqual(
            len(found), 3,
            f"the model picker only offers {found} — a user cannot choose")

    def test_a_model_is_preselected(self):
        # Landing on a screen where nothing is chosen makes Start ambiguous.
        self.assertIn("●", "".join(self.report["texts"]),
                      "no model is marked as selected on arrival")

    def test_the_start_button_is_present(self):
        self.assertTrue(
            any("start" in t.lower() for t in self.report["texts"]),
            "there is no button to leave this screen")

    def test_nothing_is_clipped_below_the_window(self):
        """The bug that shipped once: the window grew past the screen and the
        Start button went with it. Model cards below the fold are fine - they
        are inside the scrollable list and scrolling reaches them. Anything
        else below the edge is unreachable."""
        stuck = [o for o in self.report["offscreen"] if not o["scrolls"]]
        self.assertFalse(
            stuck,
            f"{len(stuck)} control(s) sit below the window edge and cannot be "
            f"clicked: {stuck[:3]}")

    def test_no_label_is_truncated(self):
        self.assertFalse(
            self.report["truncated"],
            f"the window cuts its own text: {self.report['truncated'][:3]}")

    def test_the_window_fits_on_the_screen(self):
        # It is not resizable and has no scrollbar of its own, so a window
        # taller than the display is permanently unusable.
        self.assertLessEqual(
            self.report["height"], self.report["screen_h"] - 40,
            f"the setup window is {self.report['height']}px tall on a "
            f"{self.report['screen_h']}px screen — the bottom is off-display")


if __name__ == "__main__":
    unittest.main()
