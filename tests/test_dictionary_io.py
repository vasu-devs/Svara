"""Dictionary CSV import/export, the auto-learn queue, and correction detection.

Auto-learn is the most invasive feature in the codebase, so most of these tests
are about what it must *not* do: never write to the dictionary on its own,
never act on a single session, never learn from a rephrase.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_dictionary_io -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.autolearn import AutoLearner, find_corrections  # noqa: E402
from mywhisper.dictionary_io import (LearnQueue, export_csv,  # noqa: E402
                                     import_csv, load_dictionary,
                                     save_dictionary)


class _TmpBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-dict-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch("mywhisper.paths.base_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)


class TestDictionaryFile(_TmpBase):
    def test_missing_file_yields_the_expected_shape(self):
        data = load_dictionary()
        self.assertEqual(data["words"], [])
        self.assertEqual(data["replacements"], {})
        self.assertEqual(data["snippets"], {})

    def test_round_trip(self):
        save_dictionary({"words": ["Svara"], "replacements": {"a": "b"},
                         "snippets": {}, "spoken_punctuation": False})
        self.assertEqual(load_dictionary()["words"], ["Svara"])

    def test_corrupt_file_does_not_raise(self):
        (self.tmp / "dictionary.yaml").write_text("{[not yaml", encoding="utf-8")
        self.assertEqual(load_dictionary()["words"], [])

    def test_save_is_atomic_leaving_no_temp_file(self):
        save_dictionary({"words": ["x"]})
        self.assertFalse((self.tmp / "dictionary.yaml.tmp").exists())


class TestCsvImport(_TmpBase):
    def _csv(self, body: str) -> Path:
        path = self.tmp / "in.csv"
        path.write_text(body, encoding="utf-8")
        return path

    def test_two_column_import(self):
        data = load_dictionary()
        report = import_csv(self._csv("draught,draft\nget hub,GitHub\n"), data)
        self.assertEqual(report.added, 2)
        self.assertEqual(data["replacements"]["draught"], "draft")

    def test_single_column_becomes_words(self):
        data = load_dictionary()
        report = import_csv(self._csv("Kubernetes\nCTranslate2\n"), data)
        self.assertEqual(report.added, 2)
        self.assertIn("Kubernetes", data["words"])

    def test_a_header_row_is_tolerated(self):
        data = load_dictionary()
        report = import_csv(self._csv("heard,typed\ndraught,draft\n"), data)
        self.assertEqual(report.added, 1)
        self.assertNotIn("heard", data["replacements"])

    def test_existing_entries_are_never_overwritten(self):
        # A bulk import that quietly replaced the user's own corrections would
        # defeat the one feature that exists to preserve them.
        data = load_dictionary()
        data["replacements"]["draught"] = "DRAFT-MINE"
        report = import_csv(self._csv("draught,draft\n"), data)
        self.assertEqual(data["replacements"]["draught"], "DRAFT-MINE")
        self.assertEqual(report.added, 0)
        self.assertEqual(len(report.conflicts), 1)
        self.assertIn("already existed", report.summary())

    def test_identical_existing_entry_is_not_a_conflict(self):
        data = load_dictionary()
        data["replacements"]["draught"] = "draft"
        report = import_csv(self._csv("draught,draft\n"), data)
        self.assertEqual(report.conflicts, [])

    def test_row_limit_is_enforced_and_reported(self):
        rows = "\n".join(f"w{i},x{i}" for i in range(1500))
        report = import_csv(self._csv(rows), load_dictionary())
        self.assertTrue(report.truncated)
        self.assertLessEqual(report.added, 1000)
        self.assertIn("limit", report.summary())

    def test_blank_rows_are_ignored(self):
        report = import_csv(self._csv("a,b\n\n\nc,d\n"), load_dictionary())
        self.assertEqual(report.added, 2)

    def test_missing_file_is_reported_not_raised(self):
        report = import_csv(self.tmp / "nope.csv", load_dictionary())
        self.assertEqual(report.added, 0)

    def test_export_round_trips_through_import(self):
        original = {"words": ["Svara"], "replacements": {"a": "b"},
                    "snippets": {"sig": "Best,\nV"}}
        out = self.tmp / "out.csv"
        self.assertEqual(export_csv(out, original), 3)
        fresh = load_dictionary()
        import_csv(out, fresh)
        self.assertIn("Svara", fresh["words"])
        self.assertEqual(fresh["replacements"]["a"], "b")


class TestLearnQueue(_TmpBase):
    def test_a_single_observation_never_becomes_a_suggestion(self):
        queue = LearnQueue(session_id=1.0, threshold=3)
        self.assertIsNone(queue.observe("cuban", "kubernetes"))
        self.assertEqual(queue.pending(), [])

    def test_repetition_within_one_session_is_not_enough(self):
        # One frustrated editing session should not teach Svara anything.
        queue = LearnQueue(session_id=1.0, threshold=3)
        for _ in range(6):
            queue.observe("cuban", "kubernetes")
        self.assertEqual(queue.pending(), [])

    def test_crossing_both_thresholds_produces_a_suggestion(self):
        queue = LearnQueue(session_id=1.0, threshold=3)
        queue.observe("cuban", "kubernetes")
        queue.observe("cuban", "kubernetes")
        queue = LearnQueue(session_id=2.0, threshold=3)   # a new session
        ready = queue.observe("cuban", "kubernetes")
        self.assertIsNotNone(ready)
        self.assertEqual(ready.corrected, "kubernetes")

    def test_a_suggestion_is_announced_only_once(self):
        queue = LearnQueue(session_id=1.0, threshold=2)
        queue.observe("cuban", "kubernetes")
        queue = LearnQueue(session_id=2.0, threshold=2)
        self.assertIsNotNone(queue.observe("cuban", "kubernetes"))
        self.assertIsNone(queue.observe("cuban", "kubernetes"))

    def test_nothing_reaches_the_dictionary_without_accept(self):
        queue = LearnQueue(session_id=1.0, threshold=2)
        queue.observe("cuban", "kubernetes")
        queue = LearnQueue(session_id=2.0, threshold=2)
        queue.observe("cuban", "kubernetes")
        self.assertEqual(load_dictionary()["replacements"], {})

    def test_accept_promotes_into_the_dictionary(self):
        queue = LearnQueue(session_id=1.0, threshold=2)
        queue.observe("cuban", "kubernetes")
        queue = LearnQueue(session_id=2.0, threshold=2)
        queue.observe("cuban", "kubernetes")
        data = load_dictionary()
        self.assertTrue(queue.accept("cuban", data))
        self.assertEqual(load_dictionary()["replacements"]["cuban"],
                         "kubernetes")

    def test_reject_removes_the_candidate(self):
        queue = LearnQueue(session_id=1.0, threshold=2)
        queue.observe("cuban", "kubernetes")
        self.assertTrue(queue.reject("cuban"))
        self.assertFalse(queue.reject("cuban"))

    def test_identical_text_is_not_a_correction(self):
        queue = LearnQueue(session_id=1.0, threshold=2)
        self.assertIsNone(queue.observe("word", "word"))
        self.assertIsNone(queue.observe("", "x"))

    def test_state_survives_a_restart(self):
        LearnQueue(session_id=1.0, threshold=2).observe("cuban", "kubernetes")
        reloaded = LearnQueue(session_id=1.0, threshold=2)
        self.assertIn("cuban", [c.heard.lower() for c in reloaded._items.values()])


class TestFindCorrections(unittest.TestCase):
    def test_a_single_word_fix_is_found(self):
        pairs = find_corrections("deploy the cuban cluster today",
                                 "deploy the kubernetes cluster today")
        self.assertEqual(pairs, [("cuban", "kubernetes")])

    def test_identical_text_yields_nothing(self):
        self.assertEqual(find_corrections("same text", "same text"), [])

    def test_rephrasing_is_not_a_correction(self):
        # Two unrelated words mean the user rewrote their sentence, which
        # teaches nothing about recognition.
        self.assertEqual(
            find_corrections("let us go to the shop",
                             "let us go to the cinema"), [])

    def test_one_to_many_replacement_is_ignored(self):
        self.assertEqual(
            find_corrections("the cuban cluster", "the kube ernetes cluster"),
            [])

    def test_short_words_are_ignored(self):
        self.assertEqual(find_corrections("a be c", "a de c"), [])

    def test_digits_are_ignored(self):
        self.assertEqual(find_corrections("meet at 500", "meet at 600"), [])

    def test_empty_inputs(self):
        self.assertEqual(find_corrections("", "anything"), [])


class TestAutoLearnerGating(_TmpBase):
    def test_disabled_learner_schedules_nothing(self):
        queue = LearnQueue(session_id=1.0)
        learner = AutoLearner(queue, enabled=False)
        learner.watch("some dictated text here")
        self.assertIsNone(learner._timer)

    def test_enabled_learner_schedules_a_check(self):
        learner = AutoLearner(LearnQueue(session_id=1.0), enabled=True,
                              delay_s=99)
        self.addCleanup(learner.stop)
        learner.watch("some dictated text here")
        self.assertIsNotNone(learner._timer)

    def test_one_word_dictations_are_ignored(self):
        learner = AutoLearner(LearnQueue(session_id=1.0), enabled=True)
        learner.watch("hello")
        self.assertIsNone(learner._timer)

    def test_the_check_feeds_the_queue(self):
        queue = LearnQueue(session_id=1.0, threshold=2)
        learner = AutoLearner(
            queue, enabled=True,
            read_caret=lambda n: "deploy the kubernetes cluster today")
        learner._check("deploy the cuban cluster today")
        self.assertIn("cuban", queue._items)

    def test_a_failing_caret_read_is_a_non_event(self):
        queue = LearnQueue(session_id=1.0)
        learner = AutoLearner(queue, enabled=True,
                              read_caret=lambda n: (_ for _ in ()).throw(
                                  RuntimeError("uia down")))
        learner._check("some text here")     # must not raise
        self.assertEqual(queue._items, {})


if __name__ == "__main__":
    unittest.main()
