"""Transform slots, style samples, and the diff.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_transforms -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.transforms import Transformer  # noqa: E402
from mywhisper.transforms.diff import (DELETE, EQUAL, INSERT,  # noqa: E402
                                       is_trivial, summarize, word_diff)
from mywhisper.transforms.slots import (MAX_SAMPLE_BUDGET,  # noqa: E402
                                        MIN_SAMPLE_WORDS, SlotRegistry)


class TestSlotRegistry(unittest.TestCase):
    def test_slot_one_defaults_to_prompt_engineer(self):
        registry = SlotRegistry({})
        self.assertEqual(registry.get(1).name, "Prompt Engineer")
        self.assertIn("prompt engineer", registry.get(1).prompt.lower())

    def test_user_can_claim_slot_one(self):
        registry = SlotRegistry({"slots": {1: {"name": "Mine", "prompt": "p"}}})
        self.assertEqual(registry.get(1).name, "Mine")

    def test_custom_slots_load(self):
        registry = SlotRegistry({"slots": {
            2: {"name": "Concise", "prompt": "Tighten this.",
                "hotkey": "<cmd>+<alt>+2"}}})
        slot = registry.get(2)
        self.assertEqual(slot.name, "Concise")
        self.assertEqual(slot.hotkey, "<cmd>+<alt>+2")

    def test_slot_without_prompt_or_builtin_is_skipped(self):
        registry = SlotRegistry({"slots": {3: {"name": "Broken"}}})
        self.assertIsNone(registry.get(3))

    def test_out_of_range_slots_are_skipped(self):
        registry = SlotRegistry({"slots": {
            0: {"prompt": "x"}, 10: {"prompt": "x"}}})
        self.assertIsNone(registry.get(0))
        self.assertIsNone(registry.get(10))

    def test_unknown_builtin_is_skipped_not_fatal(self):
        registry = SlotRegistry({"slots": {4: {"builtin": "telepathy"}}})
        self.assertIsNone(registry.get(4))

    def test_duplicate_hotkeys_lose_the_second_binding(self):
        registry = SlotRegistry({"slots": {
            2: {"name": "A", "prompt": "a", "hotkey": "<cmd>+<alt>+2"},
            3: {"name": "B", "prompt": "b", "hotkey": "<cmd>+<alt>+2"}}})
        self.assertEqual(registry.get(2).hotkey, "<cmd>+<alt>+2")
        self.assertIsNone(registry.get(3).hotkey)

    def test_non_mapping_slots_config_does_not_crash(self):
        registry = SlotRegistry({"slots": ["nope"]})
        self.assertEqual(registry.get(1).name, "Prompt Engineer")

    def test_hotkey_map_only_includes_bound_slots(self):
        registry = SlotRegistry({"slots": {
            1: {"name": "PE", "builtin": "prompt_engineer",
                "hotkey": "<cmd>+<alt>+1"},
            2: {"name": "No key", "prompt": "x"}}})
        self.assertEqual(list(registry.hotkey_map(lambda n: n)),
                         ["<cmd>+<alt>+1"])

    def test_voice_addressing_by_name(self):
        registry = SlotRegistry({"slots": {
            2: {"name": "Concise", "prompt": "x"}}})
        self.assertEqual(registry.by_name("make it concise").number, 2)
        self.assertEqual(registry.by_name("Concise").number, 2)
        self.assertIsNone(registry.by_name("translate to french"))

    def test_auto_slot(self):
        cfg = {"slots": {2: {"name": "C", "prompt": "x"}},
               "auto_after_dictation": 2}
        self.assertEqual(SlotRegistry(cfg).auto_slot().number, 2)
        self.assertIsNone(SlotRegistry({"slots": {}}).auto_slot())

    def test_auto_slot_pointing_at_nothing_is_none(self):
        registry = SlotRegistry({"auto_after_dictation": 7})
        self.assertIsNone(registry.auto_slot())


class TestStyleSamples(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-samples-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch("mywhisper.paths.base_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write(self, name: str, words: int) -> str:
        path = self.tmp / name
        path.write_text(" ".join(["word"] * words), encoding="utf-8")
        return name

    def test_a_valid_sample_is_attached(self):
        name = self._write("voice.txt", 120)
        registry = SlotRegistry({"slots": {
            2: {"name": "Mine", "prompt": "Rewrite.", "samples": [name]}}})
        prompt = registry.get(2).system_prompt()
        self.assertIn("Rewrite.", prompt)
        self.assertIn("--- sample ---", prompt)

    def test_too_short_samples_are_dropped(self):
        name = self._write("tiny.txt", MIN_SAMPLE_WORDS - 10)
        registry = SlotRegistry({"slots": {
            2: {"name": "Mine", "prompt": "Rewrite.", "samples": [name]}}})
        self.assertNotIn("--- sample ---", registry.get(2).system_prompt())

    def test_missing_files_are_skipped_not_fatal(self):
        registry = SlotRegistry({"slots": {
            2: {"name": "Mine", "prompt": "Rewrite.", "samples": ["nope.txt"]}}})
        self.assertEqual(registry.get(2).system_prompt(), "Rewrite.")

    def test_sample_budget_is_enforced(self):
        # Five 500-word samples on a local 3B model is a latency cliff.
        names = [self._write(f"s{i}.txt", 500) for i in range(5)]
        registry = SlotRegistry({"slots": {
            2: {"name": "Mine", "prompt": "Rewrite.", "samples": names}}})
        prompt = registry.get(2).system_prompt()
        self.assertLessEqual(len(prompt.split()), MAX_SAMPLE_BUDGET + 100)

    def test_a_single_string_sample_is_accepted(self):
        name = self._write("voice.txt", 120)
        registry = SlotRegistry({"slots": {
            2: {"name": "Mine", "prompt": "R", "samples": name}}})
        self.assertIn("--- sample ---", registry.get(2).system_prompt())


class TestWordDiff(unittest.TestCase):
    def test_identical_text_is_all_equal(self):
        self.assertEqual([op for op, _ in word_diff("a b c", "a b c")], [EQUAL])

    def test_insertion(self):
        ops = word_diff("a c", "a b c")
        self.assertIn(INSERT, [op for op, _ in ops])

    def test_deletion(self):
        ops = word_diff("a b c", "a c")
        self.assertIn(DELETE, [op for op, _ in ops])

    def test_replacement_shows_both_sides(self):
        ops = [op for op, _ in word_diff("the cat sat", "the dog sat")]
        self.assertIn(DELETE, ops)
        self.assertIn(INSERT, ops)

    def test_reassembles_losslessly(self):
        before, after = "one two  three", "one two three four"
        self.assertEqual(
            "".join(t for op, t in word_diff(before, after) if op != INSERT),
            before)
        self.assertEqual(
            "".join(t for op, t in word_diff(before, after) if op != DELETE),
            after)

    def test_adjacent_runs_are_merged(self):
        ops = word_diff("a b c d", "x y z w")
        self.assertLessEqual(len([o for o, _ in ops if o == INSERT]), 1)

    def test_summarize_counts_words(self):
        added, removed = summarize("one two three", "one two three four five")
        self.assertEqual((added, removed), (2, 0))

    def test_is_trivial_ignores_whitespace_only_changes(self):
        self.assertTrue(is_trivial("a  b", "a b"))
        self.assertFalse(is_trivial("a b", "a c"))

    def test_empty_inputs(self):
        self.assertEqual(word_diff("", ""), [])
        self.assertEqual(summarize("", ""), (0, 0))


class _FakeLlm:
    def __init__(self, result="rewritten text", reachable=True):
        self.result = result
        self._reachable = reachable
        self.calls = []

    def reachable(self, *_a, **_k):
        return self._reachable

    def run_prompt(self, system_prompt, text, style_hint=None):
        self.calls.append((system_prompt, text))
        return self.result


class TestApplyToText(unittest.TestCase):
    """`auto_after_dictation` runs on every finished dictation, so it must be
    a silent no-op when it can't work — never a toast per utterance."""

    def _transformer(self, llm, **cfg):
        base = {"slots": {2: {"name": "Concise", "prompt": "Tighten."}},
                "auto_after_dictation": 2, "max_chars": 8000}
        base.update(cfg)
        return Transformer(llm, base, notify=lambda *_: None)

    def test_runs_the_configured_slot(self):
        llm = _FakeLlm("tight")
        self.assertEqual(self._transformer(llm).apply_to_text("some words"),
                         "tight")
        self.assertIn("Tighten.", llm.calls[0][0])

    def test_no_slot_configured_is_a_no_op(self):
        transformer = self._transformer(_FakeLlm(), auto_after_dictation=None)
        self.assertIsNone(transformer.apply_to_text("some words"))

    def test_unreachable_llm_is_a_silent_no_op(self):
        transformer = self._transformer(_FakeLlm(reachable=False))
        self.assertIsNone(transformer.apply_to_text("some words"))

    def test_unchanged_output_is_treated_as_no_change(self):
        transformer = self._transformer(_FakeLlm("same words"))
        self.assertIsNone(transformer.apply_to_text("same words"))

    def test_oversized_text_is_skipped(self):
        transformer = self._transformer(_FakeLlm(), max_chars=10)
        self.assertIsNone(transformer.apply_to_text("x" * 50))

    def test_empty_text_is_skipped(self):
        self.assertIsNone(self._transformer(_FakeLlm()).apply_to_text("   "))


class TestPreviewGate(unittest.TestCase):
    def test_preview_auto_rejects_when_the_window_cannot_open(self):
        # If the user asked to review every rewrite, a broken window must not
        # silently apply an unreviewed one.
        transformer = Transformer(_FakeLlm("new"), {"preview": "auto"},
                                  notify=lambda *_: None)
        with mock.patch("mywhisper.howto_ui.show_diff",
                        side_effect=RuntimeError("no display")):
            self.assertFalse(transformer._confirm("old", "new", "T"))

    def test_default_preview_mode_is_on_request(self):
        self.assertEqual(SlotRegistry({}).preview, "on_request")


if __name__ == "__main__":
    unittest.main()
