"""No app or real user database: every test uses isolated SQLite fixtures."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from mywhisper.history import History


class HistoryInsights(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        patch = mock.patch("mywhisper.paths.base_dir", return_value=self.root)
        patch.start()
        self.addCleanup(patch.stop)
        self.history = History({})
        self.addCleanup(self.history.close)
        self.now = datetime(2026, 9, 6, 12, tzinfo=timezone.utc).timestamp()

    def record(self, text, seconds_ago=0, app="editor.exe", kind="dictation"):
        with mock.patch("mywhisper.history.time.time", return_value=self.now - seconds_ago):
            self.history.record(text, app, kind)

    def test_totals_days_apps_and_no_transcript_in_summary(self):
        self.record("one two three", app="editor.exe")
        self.record("four five", seconds_ago=86400, app="chat.exe")
        self.record("excluded original", kind="polish-original")
        self.record("outside range", seconds_ago=31 * 86400)
        result = self.history.usage(30, now=self.now)
        self.assertEqual((result["dictations"], result["words"], result["active_days"]), (2, 5, 2))
        self.assertEqual(len(result["daily"]), 30)
        self.assertEqual(result["apps"][0]["app"], "editor.exe")
        self.assertNotIn("one two three", json.dumps(result))

    def test_retention_is_applied_without_restarting(self):
        self.record("expired", seconds_ago=7200)
        self.record("retained")
        self.history.retention_hours = 1
        with mock.patch("mywhisper.history.time.time", return_value=self.now):
            self.assertEqual(self.history.last(), "retained")
            self.assertEqual(len(self.history.recent()), 1)
            self.assertEqual(self.history.usage(now=self.now)["dictations"], 1)
            count = self.history.export_json(self.root / "export.json")
        self.assertEqual(count, 1)
        self.assertNotIn("expired", (self.root / "export.json").read_text())

    def test_expired_last_is_not_recoverable_via_last(self):
        self.record("expired", seconds_ago=7200)
        self.history.retention_hours = 1
        with mock.patch("mywhisper.history.time.time", return_value=self.now):
            self.assertIsNone(self.history.last())

    def test_reads_enforce_retention_even_if_pruning_cannot_delete(self):
        self.record("expired", seconds_ago=7200)
        self.history.retention_hours = 1
        with mock.patch.object(self.history, "prune"), \
             mock.patch("mywhisper.history.time.time", return_value=self.now):
            self.assertIsNone(self.history.last())
            self.assertEqual(self.history.recent(), [])
            self.assertEqual(self.history.recent(query="expired"), [])
            self.assertEqual(self.history.usage(now=self.now)["dictations"], 0)
            self.assertEqual(self.history.export_json(self.root / "empty.json"), 0)

    def test_search_treats_percent_and_underscore_literally(self):
        self.record("100% ready")
        self.record("user_name")
        self.record("ordinary text")
        self.assertEqual(len(self.history.recent(query="%")), 1)
        self.assertEqual(len(self.history.recent(query="_")), 1)
        self.assertEqual(self.history.recent(query="READY")[0][-1], "100% ready")

    def test_lossless_export_and_original_kinds(self):
        self.record("नमस्ते\n  user_name\n")
        self.record("old wording", kind="polish-original")
        self.assertEqual(self.history.export_json(self.root / "out.json"), 2)
        out = json.loads((self.root / "out.json").read_text(encoding="utf-8"))
        self.assertEqual(out["entries"][0]["text"], "नमस्ते\n  user_name\n")
        self.assertEqual(out["entries"][1]["kind"], "polish-original")

    def test_export_cannot_overwrite_its_database(self):
        for suffix in ("", "-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                self.history.export_json(self.root / ("history.db" + suffix))

    def test_failed_export_preserves_existing_file(self):
        path = self.root / "out.json"
        path.write_text("previous export")
        with mock.patch("mywhisper.history.os.replace", side_effect=OSError("blocked")):
            with self.assertRaises(OSError):
                self.history.export_json(path)
        self.assertEqual(path.read_text(), "previous export")
        self.assertEqual(list(self.root.glob(".svara-history-*")), [])

    def test_disabled_history_produces_no_new_database(self):
        disabled = History({"enabled": False})
        disabled.record("do not save")
        self.assertEqual(disabled.usage(now=self.now)["dictations"], 0)
        with self.assertRaises(ValueError):
            disabled.export_json(self.root / "nothing.json")
        self.assertFalse((self.root / "nothing.json").exists())

    def test_clear_removes_insights_as_well(self):
        self.record("one two")
        self.history.clear()
        self.assertEqual(self.history.usage(now=self.now)["words"], 0)


if __name__ == "__main__":
    unittest.main()
