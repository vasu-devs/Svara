"""The first-run download bar.

Reported from the field: the bar jitters. It does, and for a reason that is
easy to reproduce once written down - huggingface_hub creates one tqdm bar per
file as each file *starts*, so the denominator grows during the download and a
plain done/total keeps jumping backwards.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_download_progress -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.setup_ui import smooth_fraction  # noqa: E402


class TestSmoothFraction(unittest.TestCase):
    def test_basic_progress(self):
        self.assertAlmostEqual(smooth_fraction(50, 100), 0.5)

    def test_zero_total_holds_the_floor(self):
        # Before any size has resolved, show what we last showed, not 0.
        self.assertEqual(smooth_fraction(0, 0), 0.0)
        self.assertEqual(smooth_fraction(1000, 0, floor=0.42), 0.42)

    def test_never_exceeds_one(self):
        # A total that resolves late can leave done > total for a tick.
        self.assertEqual(smooth_fraction(150, 100), 1.0)

    def test_never_goes_backwards(self):
        # THE BUG. File one is 500 MB and half done, so the bar sits at 50%.
        # File two's size then lands, the denominator jumps to 1500 MB, and a
        # naive fraction would drop the bar to 17%.
        naive = 250 / 1500
        self.assertLess(naive, 0.5)
        self.assertEqual(smooth_fraction(250, 1500, floor=0.5), 0.5)

    def test_a_realistic_multi_file_download_is_monotonic(self):
        # Five files whose totals arrive one at a time, which is exactly what
        # snapshot_download does with our allow_patterns.
        sizes = [1_400_000_000, 2_200_000, 1_800_000, 900_000, 480_000]
        done = 0
        total = 0
        shown = 0.0
        readings = []
        for i, size in enumerate(sizes):
            total += size                      # this file's bar appears
            for _ in range(10):                # and then streams
                done += size // 10
                shown = smooth_fraction(done, total, shown)
                readings.append(shown)

        for a, b in zip(readings, readings[1:]):
            self.assertGreaterEqual(
                b, a, "the bar moved backwards, which is the reported jitter")
        self.assertLessEqual(readings[-1], 1.0)
        self.assertGreater(readings[-1], 0.98, "should finish at ~100%")

    def test_the_naive_version_would_fail_that(self):
        # Guards the guard: proves the scenario above genuinely regresses
        # without the clamp, so this suite would have caught the real bug.
        sizes = [1_400_000_000, 2_200_000, 1_800_000]
        done = total = 0
        readings = []
        for size in sizes:
            total += size
            for _ in range(5):
                done += size // 5
                readings.append(done / total)
        self.assertTrue(any(b < a for a, b in zip(readings, readings[1:])),
                        "scenario no longer reproduces the regression")


class TestProgressTqdm(unittest.TestCase):
    """The tqdm shim that feeds the numbers."""

    def _shim(self):
        from mywhisper.setup_ui import _progress_tqdm
        dl = {"done": 0, "total": 0}
        return dl, _progress_tqdm(dl)

    def test_byte_bars_accumulate_across_files(self):
        dl, Tqdm = self._shim()
        a = Tqdm(total=100, unit="B")
        b = Tqdm(total=400, unit="B")
        a.update(50)
        b.update(100)
        self.assertEqual(dl["done"], 150)
        self.assertEqual(dl["total"], 500)

    def test_non_byte_bars_are_ignored(self):
        # snapshot_download also opens a "files" counter bar; counting it as
        # bytes would corrupt both numbers.
        dl, Tqdm = self._shim()
        files = Tqdm(total=5, unit="it")
        files.update(1)
        self.assertEqual(dl["done"], 0)
        self.assertEqual(dl["total"], 0)

    def test_each_bar_gets_a_distinct_key(self):
        # Previously keyed on id(), which Python reuses after garbage
        # collection - a recycled id would merge two files' totals through
        # max() and leave the bar permanently short of 100%.
        dl, Tqdm = self._shim()
        keys = set()
        for _ in range(50):
            bar = Tqdm(total=10, unit="B")
            bar.update(1)
            keys.add(bar._key)
            del bar
        self.assertEqual(len(keys), 50, "bar keys collided")
        self.assertEqual(dl["total"], 500)

    def test_total_tracks_the_high_water_of_each_bar(self):
        # Xet-style bars start at total=0 and learn their size later.
        dl, Tqdm = self._shim()
        bar = Tqdm(total=0, unit="B")
        bar.update(10)
        bar.total = 900
        bar.update(10)
        self.assertEqual(dl["total"], 900)
        self.assertEqual(dl["done"], 20)


if __name__ == "__main__":
    unittest.main()
