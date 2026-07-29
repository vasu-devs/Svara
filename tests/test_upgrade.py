"""Upgrading from v0.4 — the path most users will actually take.

A new user gets the bundled `config.yaml` with every 0.5 option documented in
it. An *upgrading* user keeps the config.yaml they already have, which knows
nothing about `locale:`, `logging:`, transform slots or the new shortcuts. Auto
update replaces the binary, not their settings.

So the question these tests answer is: does someone who upgrades get the new
features, or do they silently get a half-configured app? Everything here runs
against the real v0.4.1 config, extracted from git.

Also covers `setup_ui._apply_config`, which rewrites config.yaml with line
regexes — adding keys to that file can quietly make it target the wrong line,
and it runs on every first launch.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_upgrade -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper import config as config_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
V04_COMMIT = "7cde18f"       # the v0.4.1 release


def _v04_config() -> str | None:
    try:
        # encoding matters: config.yaml is full of ▸ — “ ” and the Windows
        # default (cp1252) raises on them.
        out = subprocess.run(
            ["git", "show", f"{V04_COMMIT}:config.yaml"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, check=False)
        return out.stdout if out.returncode == 0 and out.stdout else None
    except (subprocess.SubprocessError, OSError):
        return None


class _UpgradeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v04 = _v04_config()
        if not cls.v04:
            raise unittest.SkipTest("v0.4 config unavailable (shallow clone?)")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-upgrade-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.cfg_path = self.tmp / "config.yaml"
        self.cfg_path.write_text(self.v04, encoding="utf-8")
        patcher = mock.patch("mywhisper.paths.base_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = config_mod.load(self.cfg_path)


class TestV04ConfigStillLoads(_UpgradeCase):
    def test_it_parses(self):
        self.assertEqual(self.cfg["model"]["name"], "base.en")
        self.assertEqual(self.cfg["recording"]["hotkey"], "right alt")

    def test_new_sections_arrive_from_defaults(self):
        for section in ("logging", "locale", "asr", "scratchpad"):
            self.assertIn(section, self.cfg,
                          f"{section} missing — upgraders lose the feature")

    def test_new_keys_inside_existing_sections_arrive_too(self):
        # The deep merge has to reach INTO sections the old file already has,
        # or an upgrader keeps their `transforms:` block and loses slots.
        self.assertIn("slots", self.cfg["transforms"])
        self.assertIn("preview", self.cfg["transforms"])
        self.assertIn("terminal_newline", self.cfg["injection"])
        self.assertIn("warn_on_elevated", self.cfg["injection"])
        self.assertIn("read_caret_text", self.cfg["context"])
        self.assertIn("auto_learn", self.cfg["dictionary"])
        self.assertIn("device_policy", self.cfg["audio"])
        self.assertIn("commit_policy", self.cfg["streaming"])
        self.assertIn("semantic", self.cfg["recording"]["auto_stop"])

    def test_the_users_own_settings_are_never_overwritten(self):
        raw = self.v04.replace("hotkey: right alt", "hotkey: f8")
        self.cfg_path.write_text(raw, encoding="utf-8")
        cfg = config_mod.load(self.cfg_path)
        self.assertEqual(cfg["recording"]["hotkey"], "f8")

    def test_privacy_gates_are_off_for_upgraders(self):
        # These must never arrive switched on just because a user upgraded.
        self.assertFalse(self.cfg["logging"]["debug_transcripts"])
        self.assertFalse(self.cfg["dictionary"]["auto_learn"])
        self.assertFalse(self.cfg["context"]["read_caret_text"])


class TestUpgradersGetTheFeatures(_UpgradeCase):
    def test_prompt_engineer_is_bound_without_editing_config(self):
        from mywhisper.transforms.slots import SlotRegistry

        registry = SlotRegistry(self.cfg["transforms"])
        slot = registry.get(1)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.name, "Prompt Engineer")
        self.assertEqual(slot.hotkey, "<cmd>+<alt>+1",
                         "upgraders would have no way to trigger it")

    def test_view_diff_shortcut_exists(self):
        self.assertEqual(self.cfg["shortcuts"]["view_diff"], "<cmd>+<alt>+o")

    def test_terminal_safety_is_on_by_default_for_upgraders(self):
        from mywhisper.injection import classify, is_terminal_app

        self.assertEqual(classify("windowsterminal.exe", self.cfg["injection"]),
                         "terminal")
        self.assertTrue(is_terminal_app("cmd.exe", self.cfg["injection"]))
        self.assertEqual(self.cfg["injection"]["terminal_newline"], "space")

    def test_locale_typography_works_for_upgraders(self):
        from mywhisper.pipeline import CleanupPipeline

        pipe = CleanupPipeline(self.cfg["cleanup"], self.cfg["dictionary"],
                               self.cfg["locale"], self.cfg["context"])
        ctx = pipe.context(locale="fr-FR")
        self.assertIn(" ", pipe.run("Bonjour !", ctx=ctx))

    def test_the_pipeline_builds_from_a_v04_config(self):
        from mywhisper.pipeline import CleanupPipeline

        pipe = CleanupPipeline(self.cfg["cleanup"], self.cfg["dictionary"],
                               self.cfg["locale"], self.cfg["context"])
        self.assertEqual(pipe.chain.order[-1], "personalizer")
        self.assertEqual(pipe.run("um hello there"), "hello there")


class TestUserDataSurvives(_UpgradeCase):
    def test_an_existing_dictionary_is_preserved(self):
        (self.tmp / "dictionary.yaml").write_text(
            "words: [Kubernetes]\nreplacements: {swara: Svara}\n",
            encoding="utf-8")
        merged = config_mod.merged_dictionary(self.cfg)
        self.assertIn("Kubernetes", merged["words"])
        self.assertEqual(merged["replacements"]["swara"], "Svara")

    def test_an_existing_scratchpad_txt_is_migrated_and_kept(self):
        from mywhisper.scratchpad import Scratchpad

        legacy = self.tmp / "scratchpad.txt"
        legacy.write_text("notes I care about", encoding="utf-8")
        store = Scratchpad()
        self.addCleanup(store.close)
        bodies = [store.body(i) for i, _t, _u in store.notes()]
        self.assertIn("notes I care about", bodies)
        self.assertTrue(legacy.is_file(),
                        "the original file must survive the migration")

    def test_an_existing_history_db_still_opens(self):
        from mywhisper.history import History

        first = History(self.cfg["history"])
        first.record("dictated before the upgrade", app="notepad.exe")
        first.close()

        second = History(self.cfg["history"])
        self.addCleanup(second.close)
        self.assertEqual(second.last(), "dictated before the upgrade")


class TestApplyConfigRegex(unittest.TestCase):
    """`setup_ui._apply_config` rewrites config.yaml by line regex. New keys can
    silently make it hit the wrong line — and it runs on every first launch."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-applycfg-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _apply(self, source: str, **kw):
        from mywhisper.setup_ui import _apply_config

        path = self.tmp / "config.yaml"
        path.write_text(source, encoding="utf-8")
        _apply_config(path, kw.get("model", "large-v3-turbo"),
                      kw.get("device", "cuda"),
                      kw.get("compute", "int8_float16"))
        return config_mod.load(path)

    def test_it_targets_the_model_section_in_the_shipped_config(self):
        source = (ROOT / "config.yaml").read_text(encoding="utf-8")
        cfg = self._apply(source)
        self.assertEqual(cfg["model"]["name"], "large-v3-turbo")
        self.assertEqual(cfg["model"]["device"], "cuda")
        self.assertEqual(cfg["model"]["compute_type"], "int8_float16")

    def test_it_does_not_disturb_the_new_sections(self):
        source = (ROOT / "config.yaml").read_text(encoding="utf-8")
        before = config_mod.load(ROOT / "config.yaml")
        after = self._apply(source)
        for section in ("locale", "logging", "injection", "transforms",
                        "streaming", "audio", "scratchpad", "asr"):
            self.assertEqual(after[section], before[section],
                             f"_apply_config corrupted the {section} section")

    def test_device_policy_is_not_mistaken_for_device(self):
        # `audio.device_policy` sits at the same indent as `model.device`.
        source = (ROOT / "config.yaml").read_text(encoding="utf-8")
        cfg = self._apply(source, device="cuda")
        self.assertEqual(cfg["audio"]["device_policy"], "preferred")
        self.assertEqual(cfg["model"]["device"], "cuda")

    def test_slot_names_are_not_mistaken_for_the_model_name(self):
        # `transforms.slots.1.name` is a `name:` key too, just deeper.
        source = (ROOT / "config.yaml").read_text(encoding="utf-8")
        cfg = self._apply(source, model="tiny.en")
        self.assertEqual(cfg["model"]["name"], "tiny.en")
        self.assertEqual(cfg["transforms"]["slots"][1]["name"],
                         "Prompt Engineer")

    def test_it_still_works_on_a_v04_config(self):
        source = _v04_config()
        if not source:
            self.skipTest("v0.4 config unavailable")
        cfg = self._apply(source, model="small.en", device="cpu",
                          compute="int8")
        self.assertEqual(cfg["model"]["name"], "small.en")


if __name__ == "__main__":
    unittest.main()
