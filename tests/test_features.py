"""Unit tests for the v0.4.0 feature layer: cleanup levels/backtrack, history,
updater asset picking, app-context hotwords, dictionary merging, install
setup-carry on upgrade.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_features -v
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import appcontext, config, install, updater  # noqa: E402
from mywhisper.cleanup import CleanupPipeline, apply_backtrack  # noqa: E402
from mywhisper.history import History  # noqa: E402


def make_pipeline(level="light", dict_cfg=None, llm_enabled=False):
    return CleanupPipeline(
        {"level": level, "strip_fillers": True,
         "llm": {"enabled": llm_enabled, "url": "http://127.0.0.1:9",
                 "model": "x", "timeout_s": 1, "prompt": "p"}},
        dict_cfg)


class TestBacktrack(unittest.TestCase):
    def test_scratch_that_drops_the_clause(self):
        self.assertEqual(apply_backtrack("send the email scratch that delete it"),
                         "delete it")

    def test_strike_that_with_punctuation(self):
        self.assertEqual(apply_backtrack("meet at two, strike that, meet at three"),
                         "meet at three")

    def test_never_erases_everything(self):
        self.assertEqual(apply_backtrack("scratch that"), "scratch that")

    def test_plain_text_untouched(self):
        self.assertEqual(apply_backtrack("nothing to retract here"),
                         "nothing to retract here")


class TestCleanupLevels(unittest.TestCase):
    def test_none_keeps_fillers(self):
        self.assertEqual(make_pipeline("none").run("um, hello there"),
                         "um, hello there")

    def test_light_strips_fillers_but_not_backtrack(self):
        out = make_pipeline("light").run("um, send it scratch that stop")
        self.assertNotIn("um", out)
        self.assertIn("scratch that", out)

    def test_medium_applies_backtrack(self):
        self.assertEqual(make_pipeline("medium").run("um, send it scratch that stop"),
                         "stop")

    def test_high_without_ollama_behaves_as_medium(self):
        pipe = make_pipeline("high")
        with mock.patch.object(pipe.llm, "reachable", return_value=False):
            self.assertEqual(pipe.run("um, send it scratch that stop"), "stop")

    def test_unknown_level_falls_back_to_light(self):
        self.assertEqual(make_pipeline("extreme").level, "light")

    def test_personal_rules_still_apply_at_none(self):
        pipe = make_pipeline("none", {"replacements": {"swara": "Svara"}})
        self.assertEqual(pipe.run("um, swara"), "um, Svara")

    def test_bullet_point_vocab(self):
        pipe = make_pipeline("light", {"spoken_punctuation": True})
        self.assertEqual(pipe.run("first item bullet point second item"),
                         "first item\n- second item")


class TestHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-hist-"))
        patcher = mock.patch("mywhisper.paths.base_dir",
                             return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_record_and_last(self):
        h = History({"enabled": True})
        h.record("first thing", app="code.exe")
        h.record("second thing", app="slack.exe")
        self.assertEqual(h.last(), "second thing")
        h.close()

    def test_last_skips_non_dictations(self):
        h = History({"enabled": True})
        h.record("real dictation")
        h.record("recovered blob", kind="recovered")
        self.assertEqual(h.last(), "real dictation")
        h.close()

    def test_search(self):
        h = History({"enabled": True})
        h.record("the quick brown fox")
        h.record("something else")
        rows = h.recent(10, query="brown")
        self.assertEqual(len(rows), 1)
        self.assertIn("fox", rows[0][3])
        h.close()

    def test_disabled_is_inert(self):
        h = History({"enabled": False})
        h.record("should vanish")
        self.assertIsNone(h.last())
        self.assertEqual(h.recent(), [])

    def test_clear(self):
        h = History({"enabled": True})
        h.record("gone soon")
        h.clear()
        self.assertIsNone(h.last())
        h.close()


class TestUpdaterAssetPick(unittest.TestCase):
    def test_prefers_highest_versioned_asset(self):
        release = {"tag_name": "v0.4.0", "assets": [
            {"name": "Svara-0.3.0.exe", "browser_download_url": "u3"},
            {"name": "Svara-0.4.0.exe", "browser_download_url": "u4"},
            {"name": "cuda-runtime.zip", "browser_download_url": "uz"},
        ]}
        version, url, name = updater.pick_asset(release)
        self.assertEqual((version, url, name), ("0.4.0", "u4", "Svara-0.4.0.exe"))

    def test_bare_exe_uses_release_tag(self):
        release = {"tag_name": "v1.2.3", "assets": [
            {"name": "Svara.exe", "browser_download_url": "u"}]}
        version, url, name = updater.pick_asset(release)
        self.assertEqual(version, "1.2.3")

    def test_no_exe_asset(self):
        self.assertIsNone(updater.pick_asset(
            {"tag_name": "v9", "assets": [{"name": "notes.txt",
                                           "browser_download_url": "u"}]}))


class TestAppContext(unittest.TestCase):
    def test_title_hotwords_picks_proper_nouns(self):
        words = appcontext.title_hotwords(
            "svara-streaming-fix — Vasudev/Svara — Visual Studio Code")
        lower = [w.lower() for w in words]
        self.assertIn("vasudev", lower)
        self.assertIn("svara", lower)
        self.assertNotIn("visual", lower)   # window chrome filtered
        self.assertNotIn("code", lower)

    def test_limit_and_dedup(self):
        words = appcontext.title_hotwords("Svara Svara Svara Alpha Beta", limit=2)
        self.assertEqual(len(words), 2)

    def test_empty_title(self):
        self.assertEqual(appcontext.title_hotwords(""), [])


class TestMergedDictionary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-dict-"))
        patcher = mock.patch("mywhisper.paths.base_dir",
                             return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def test_overlay_merges_words_and_rules(self):
        (self.tmp / "dictionary.yaml").write_text(
            'words: [Extra]\nreplacements: {"b": "B2"}\n', encoding="utf-8")
        cfg = {"dictionary": {"words": ["Base"],
                              "replacements": {"a": "A", "b": "B"},
                              "snippets": {}, "spoken_punctuation": True}}
        merged = config.merged_dictionary(cfg)
        self.assertEqual(merged["words"], ["Base", "Extra"])
        self.assertEqual(merged["replacements"], {"a": "A", "b": "B2"})
        self.assertTrue(merged["spoken_punctuation"])

    def test_missing_overlay_file_is_fine(self):
        cfg = {"dictionary": {"words": ["Only"], "replacements": {},
                              "snippets": {}, "spoken_punctuation": False}}
        self.assertEqual(config.merged_dictionary(cfg)["words"], ["Only"])

    def test_broken_overlay_falls_back(self):
        (self.tmp / "dictionary.yaml").write_text("[not a mapping]",
                                                  encoding="utf-8")
        cfg = {"dictionary": {"words": ["Safe"], "replacements": {},
                              "snippets": {}, "spoken_punctuation": False}}
        self.assertEqual(config.merged_dictionary(cfg)["words"], ["Safe"])


class TestUpgradeCarriesSetup(unittest.TestCase):
    """An update must not re-run first-run setup — the flag follows the exe."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-up-"))
        self.downloads = self.tmp / "Downloads"
        self.localappdata = self.tmp / "LocalAppData"
        self.downloads.mkdir()
        self.localappdata.mkdir()
        self.new_exe = self.downloads / "Svara-new.exe"
        self.new_exe.write_bytes(b"NEW version bytes")
        self._patches = [
            mock.patch.dict(os.environ,
                            {"LOCALAPPDATA": str(self.localappdata)}),
            mock.patch.object(sys, "executable", str(self.new_exe)),
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(install, "APP_NAME", "SvaraUpgradeSelfTest"),
            mock.patch.object(install, "_spawn", return_value=True),
            mock.patch.object(install, "set_autostart", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_matching_flag_is_restamped_for_new_exe(self):
        from mywhisper import __version__
        old_exe = install.installed_exe()
        old_exe.parent.mkdir(parents=True)
        old_exe.write_bytes(b"OLD version bytes")
        install._write_manifest("0.0.1")
        flag = old_exe.parent / ".svara_ready"
        flag.write_text(install._stamp_of(old_exe, "0.0.1"), encoding="utf-8")

        self.assertTrue(install.ensure_installed())

        new_stamp = install._stamp_of(install.installed_exe(), __version__)
        self.assertEqual(flag.read_text(encoding="utf-8"), new_stamp,
                         "setup-done must follow the upgraded exe")

    def test_stale_flag_is_not_carried(self):
        old_exe = install.installed_exe()
        old_exe.parent.mkdir(parents=True)
        old_exe.write_bytes(b"OLD version bytes")
        install._write_manifest("0.0.1")
        flag = old_exe.parent / ".svara_ready"
        flag.write_text("0.0.1:12345:999", encoding="utf-8")  # never matched

        install.ensure_installed()

        from mywhisper import __version__
        self.assertNotEqual(flag.read_text(encoding="utf-8"),
                            install._stamp_of(install.installed_exe(),
                                              __version__),
                            "an unfinished setup must stay unfinished")


class TestQuickKeysValidation(unittest.TestCase):
    def test_invalid_combo_skipped_valid_kept(self):
        from mywhisper.quickkeys import QuickKeys
        hits = []
        qk = QuickKeys({"paste_last": "<shift>+<alt>+z",
                        "copy_last": "not-a-combo!!!",
                        "polish": None},
                       {"paste_last": lambda: hits.append(1),
                        "copy_last": lambda: hits.append(2),
                        "polish": lambda: hits.append(3)})
        self.assertIsNotNone(qk._listener)  # at least one valid binding


if __name__ == "__main__":
    unittest.main(verbosity=2)
