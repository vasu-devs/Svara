"""Scratchpad storage, microphone policy, and the benchmark's metric maths.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_stores -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.audio_policy import (is_external, is_internal,  # noqa: E402
                                    rank_devices, should_switch)
from mywhisper.bench import cer, term_recall, wer  # noqa: E402
from mywhisper.scratchpad import (SOURCE_DICTATED, SOURCE_TRANSFORM,  # noqa: E402
                                  Scratchpad)


class TestScratchpad(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-scratch-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch("mywhisper.paths.base_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_and_read(self):
        store = Scratchpad()
        self.addCleanup(store.close)
        note_id = store.create("Ideas")
        store.save(note_id, "hello")
        self.assertEqual(store.body(note_id), "hello")
        self.assertEqual([t for _i, t, _u in store.notes()], ["Ideas"])

    def test_versions_record_their_source(self):
        store = Scratchpad()
        self.addCleanup(store.close)
        note_id = store.create()
        store.save(note_id, "first")
        store.save(note_id, "second", source=SOURCE_DICTATED)
        store.save(note_id, "third", source=SOURCE_TRANSFORM)
        sources = [source for _id, _ts, source, _body in store.versions(note_id)]
        self.assertIn(SOURCE_TRANSFORM, sources)
        self.assertIn(SOURCE_DICTATED, sources)

    def test_identical_saves_do_not_create_versions(self):
        # An autosave timer firing on an idle window must not fill the log.
        store = Scratchpad()
        self.addCleanup(store.close)
        note_id = store.create()
        store.save(note_id, "same")
        before = len(store.versions(note_id))
        for _ in range(5):
            store.save(note_id, "same")
        self.assertEqual(len(store.versions(note_id)), before)

    def test_restore_brings_back_an_earlier_body(self):
        store = Scratchpad()
        self.addCleanup(store.close)
        note_id = store.create()
        store.save(note_id, "original")
        store.save(note_id, "ruined by a transform", source=SOURCE_TRANSFORM)
        version_id = store.versions(note_id)[0][0]
        self.assertTrue(store.restore(note_id, version_id))
        self.assertEqual(store.body(note_id), "original")

    def test_restore_is_itself_undoable(self):
        store = Scratchpad()
        self.addCleanup(store.close)
        note_id = store.create()
        store.save(note_id, "a")
        store.save(note_id, "b")
        store.restore(note_id, store.versions(note_id)[0][0])
        self.assertTrue(any(body == "b"
                            for _i, _t, _s, body in store.versions(note_id)))

    def test_delete(self):
        store = Scratchpad()
        self.addCleanup(store.close)
        note_id = store.create()
        self.assertTrue(store.delete(note_id))
        self.assertEqual(store.notes(), [])

    def test_ensure_one_creates_a_note_when_empty(self):
        store = Scratchpad()
        self.addCleanup(store.close)
        self.assertTrue(store.ensure_one())
        self.assertEqual(len(store.notes()), 1)

    def test_disabled_store_is_inert(self):
        store = Scratchpad(enabled=False)
        self.assertEqual(store.notes(), [])
        self.assertEqual(store.create(), 0)
        self.assertEqual(store.body(1), "")

    def test_legacy_txt_is_migrated_and_kept(self):
        # Losing someone's notes in an auto-update is unrecoverable.
        legacy = self.tmp / "scratchpad.txt"
        legacy.write_text("my old notes", encoding="utf-8")
        store = Scratchpad()
        self.addCleanup(store.close)
        bodies = [store.body(i) for i, _t, _u in store.notes()]
        self.assertIn("my old notes", bodies)
        self.assertTrue(legacy.is_file(), "the original file must survive")

    def test_migration_runs_only_once(self):
        legacy = self.tmp / "scratchpad.txt"
        legacy.write_text("my old notes", encoding="utf-8")
        Scratchpad().close()
        store = Scratchpad()
        self.addCleanup(store.close)
        self.assertEqual(len(store.notes()), 1)


class TestDeviceClassification(unittest.TestCase):
    def test_external_names(self):
        for name in ("HyperX QuadCast USB", "AirPods Pro", "Jabra Headset",
                     "Blue Yeti", "Logitech Webcam"):
            self.assertTrue(is_external(name), name)

    def test_internal_names(self):
        for name in ("Microphone Array (Realtek)", "Internal Microphone",
                     "Built-in Microphone"):
            self.assertTrue(is_internal(name), name)

    def test_external_wins_over_internal_keywords(self):
        # "USB Microphone Array" is a device someone plugged in.
        self.assertTrue(is_external("USB Microphone Array"))
        self.assertFalse(is_internal("USB Microphone Array"))


class TestDeviceRanking(unittest.TestCase):
    DEVICES = [
        {"name": "Microphone Array (Realtek)", "max_input_channels": 2},
        {"name": "Speakers", "max_input_channels": 0},
        {"name": "HyperX QuadCast USB", "max_input_channels": 1},
        {"name": "Some Other Input", "max_input_channels": 1},
    ]

    def test_external_first_puts_the_usb_mic_at_the_top(self):
        self.assertEqual(rank_devices(self.DEVICES, "external_first")[0], 2)

    def test_external_first_ranks_internal_last(self):
        order = rank_devices(self.DEVICES, "external_first")
        self.assertGreater(order.index(0), order.index(2))

    def test_preferred_honours_the_configured_device(self):
        self.assertEqual(rank_devices(self.DEVICES, "preferred", preferred=3)[0], 3)

    def test_system_default_leads_with_none(self):
        self.assertIsNone(rank_devices(self.DEVICES, "system_default")[0])

    def test_outputs_are_never_offered(self):
        self.assertNotIn(1, rank_devices(self.DEVICES, "external_first"))

    def test_unknown_policy_behaves_as_preferred(self):
        self.assertEqual(rank_devices(self.DEVICES, "nonsense", preferred=3)[0], 3)

    def test_order_has_no_duplicates(self):
        order = rank_devices(self.DEVICES, "external_first")
        self.assertEqual(len(order), len(set(map(str, order))))


class TestShouldSwitch(unittest.TestCase):
    DEVICES = TestDeviceRanking.DEVICES

    def test_switches_up_to_an_external_mic(self):
        self.assertTrue(should_switch("external_first",
                                      "Microphone Array (Realtek)",
                                      self.DEVICES))

    def test_stays_put_when_already_on_an_external_mic(self):
        # "Svara keeps changing my microphone" is worse than "Svara didn't
        # notice my new headset".
        self.assertFalse(should_switch("external_first", "HyperX QuadCast USB",
                                       self.DEVICES))

    def test_leaves_when_the_external_mic_disappears(self):
        gone = [d for d in self.DEVICES if "HyperX" not in d["name"]]
        self.assertTrue(should_switch("external_first", "HyperX QuadCast USB",
                                      gone))

    def test_other_policies_never_switch(self):
        self.assertFalse(should_switch("preferred", "Microphone Array (Realtek)",
                                       self.DEVICES))


class TestBenchMetrics(unittest.TestCase):
    def test_perfect_match_is_zero_wer(self):
        self.assertEqual(wer("hello world", "hello world"), 0.0)

    def test_normalisation_ignores_case_and_punctuation(self):
        # Otherwise you measure the post-processor's comma taste, not the
        # recogniser.
        self.assertEqual(wer("Hello, world!", "hello world"), 0.0)

    def test_one_substitution_in_four_words(self):
        self.assertAlmostEqual(wer("a b c d", "a b x d"), 0.25)

    def test_deletion_counts(self):
        self.assertAlmostEqual(wer("a b c d", "a b c"), 0.25)

    def test_empty_reference_is_zero_not_a_crash(self):
        self.assertEqual(wer("", "anything"), 0.0)

    def test_cer_is_finer_grained_than_wer(self):
        self.assertLess(cer("kubernetes", "kubernetez"),
                        wer("kubernetes", "kubernetez"))

    def test_term_recall(self):
        hits, total = term_recall("deploy the kubernetes cluster",
                                  "deploy the cuban cluster", ["kubernetes"])
        self.assertEqual((hits, total), (0, 1))
        hits, total = term_recall("deploy the kubernetes cluster",
                                  "deploy the kubernetes cluster",
                                  ["kubernetes"])
        self.assertEqual((hits, total), (1, 1))


if __name__ == "__main__":
    unittest.main()
