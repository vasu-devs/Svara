"""Headless library tests. All files are temporary fixtures."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mywhisper import config, libraries


class VocabularyLibraries(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / "team.svara-library.json"
        self.entries = {"words": ["Svara", "部署"], "replacements": {"get hub": "GitHub"},
                        "snippets": {"my signature": "Best,\n  Alice\n"}}

    def test_roundtrip_preserves_unicode_multiline_and_only_vocabulary(self):
        entries = dict(self.entries, enabled=True, libraries=["private-path"], prompt="not exported")
        self.assertEqual(libraries.export_library(self.path, entries), 4)
        self.assertEqual(libraries.load_library(self.path), self.entries)
        self.assertNotIn("private-path", self.path.read_text(encoding="utf-8"))

    def test_personal_conflicts_and_cross_section_conflicts_are_not_overwritten(self):
        target = {"words": ["svara"], "replacements": {"GET HUB": "Personal",
                                                           "My Signature": "Keep mine"}, "snippets": {}}
        report = libraries.merge_library(target, self.entries)
        self.assertEqual((report.added, report.duplicates, report.conflicts), (1, 1, 2))
        self.assertEqual(target["replacements"]["GET HUB"], "Personal")
        self.assertFalse(target["snippets"])

    def test_import_is_idempotent(self):
        target = {}
        libraries.merge_library(target, self.entries)
        snapshot = copy.deepcopy(target)
        report = libraries.merge_library(target, self.entries)
        self.assertEqual(target, snapshot)
        self.assertEqual(report.added, 0)
        self.assertEqual(report.duplicates, 4)

    def test_bad_entries_do_not_partially_mutate_the_target(self):
        for bad in ({"words": ["Good", 42]}, {"snippets": {"empty": ""}},
                    {"replacements": {"key": "bad\x00text"}}, {"words": ["case", "CASE"]}):
            with self.subTest(bad=bad):
                target = copy.deepcopy(self.entries)
                with self.assertRaises(ValueError):
                    libraries.merge_library(target, bad)
                self.assertEqual(target, self.entries)

    def test_unknown_versions_and_oversized_files_are_rejected(self):
        self.path.write_text(json.dumps({"format": libraries.FORMAT, "version": 2, "entries": {}}))
        with self.assertRaises(ValueError):
            libraries.load_library(self.path)
        self.path.write_bytes(b" " * (libraries.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            libraries.load_library(self.path)

    def test_failed_export_keeps_previous_file(self):
        self.path.write_text("original")
        with mock.patch("mywhisper.libraries.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                libraries.export_library(self.path, self.entries)
        self.assertEqual(self.path.read_text(), "original")
        self.assertEqual(list(self.root.glob(".svara-library-*")), [])

    def test_config_loads_libraries_with_personal_precedence(self):
        libraries.export_library(self.path, self.entries)
        cfg = config.load(None)
        cfg["dictionary"]["libraries"] = [self.path.name]
        cfg["dictionary"]["snippets"] = {"my signature": "My own signature"}
        with mock.patch("mywhisper.paths.base_dir", return_value=self.root):
            out = config.merged_dictionary(cfg)
        self.assertEqual(out["snippets"]["my signature"], "My own signature")
        self.assertIn("Svara", out["words"])
        self.assertNotIn("Svara", cfg["dictionary"]["words"])

    def test_reload_drops_deleted_shared_entries(self):
        cfg = config.load(None)
        cfg["dictionary"]["libraries"] = [str(self.path)]
        libraries.export_library(self.path, self.entries)
        with mock.patch("mywhisper.paths.base_dir", return_value=self.root):
            first = config.merged_dictionary(cfg)
            libraries.export_library(self.path, {})
            second = config.merged_dictionary(cfg)
        self.assertIn("Svara", first["words"])
        self.assertNotIn("Svara", second["words"])

    def test_invalid_library_does_not_break_startup_or_log_private_path(self):
        cfg = config.load(None)
        cfg["dictionary"]["libraries"] = [str(self.root / "private-team-name.json")]
        with mock.patch("mywhisper.paths.base_dir", return_value=self.root), \
             self.assertLogs("mywhisper.libraries", level="WARNING") as captured:
            result = config.merged_dictionary(cfg)
        self.assertIsInstance(result, dict)
        self.assertNotIn("private-team-name", "".join(captured.output))


if __name__ == "__main__":
    unittest.main()
