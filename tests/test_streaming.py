"""The live-streaming commit state machine.

Until 0.5 this logic lived inline in the streamer loop and could only be
exercised by `test_livepath.py` — a real model, real audio, ~13 s per run, and
non-deterministic pass boundaries. These tests drive the same code with
hand-written segment sequences, so the edge cases that actually bite (a
hypothesis that revises itself, a boundary that repeats a word) are reproducible.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_streaming -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.streaming import (AdaptiveAgreementPolicy,  # noqa: E402
                                 LocalAgreementPolicy, StreamState,
                                 align_remainder, make_policy, plan_trim)

SR = 16000


def seg(text, start, end):
    return (text, start, end)


class TestLocalAgreement(unittest.TestCase):
    def setUp(self):
        self.policy = LocalAgreementPolicy(hold_back=1)

    def test_nothing_is_stable_on_the_first_pass(self):
        self.assertEqual(self.policy.stable_prefix(["hello", "world"], []), 0)

    def test_agreement_minus_the_held_back_word(self):
        stable = self.policy.stable_prefix(["a", "b", "c"], ["a", "b", "x"])
        self.assertEqual(stable, 1)      # a, b agree; b is held back

    def test_a_settled_hypothesis_releases_everything(self):
        # The speaker paused — the last word is no longer at risk.
        words = ["a", "b", "c"]
        self.assertEqual(self.policy.stable_prefix(words, list(words)), 3)

    def test_a_revision_retracts_the_unstable_tail(self):
        self.assertEqual(
            self.policy.stable_prefix(["the", "cat"], ["the", "cot"]), 0)

    def test_hold_back_zero_commits_the_whole_agreement(self):
        policy = LocalAgreementPolicy(hold_back=0)
        self.assertEqual(policy.stable_prefix(["a", "b", "c"], ["a", "b", "x"]), 2)

    def test_empty_hypothesis(self):
        self.assertEqual(self.policy.stable_prefix([], ["a"]), 0)


class TestAdaptivePolicy(unittest.TestCase):
    def test_holds_back_early(self):
        policy = AdaptiveAgreementPolicy(hold_back=1, confident_after=5)
        self.assertEqual(policy.stable_prefix(["a", "b", "c"], ["a", "b", "x"]), 1)

    def test_stops_holding_back_once_the_run_is_long(self):
        policy = AdaptiveAgreementPolicy(hold_back=1, confident_after=3)
        words = ["a", "b", "c", "d", "e"]
        last = ["a", "b", "c", "d", "X"]
        self.assertEqual(policy.stable_prefix(words, last), 4)


class TestPolicyFactory(unittest.TestCase):
    def test_known_names(self):
        self.assertIsInstance(make_policy("local_agreement"), LocalAgreementPolicy)
        self.assertIsInstance(make_policy("adaptive"), AdaptiveAgreementPolicy)

    def test_unknown_name_falls_back_without_raising(self):
        self.assertIsInstance(make_policy("telepathy"), LocalAgreementPolicy)

    def test_extra_kwargs_are_tolerated_by_the_simple_policy(self):
        policy = make_policy("local_agreement", hold_back=2, confident_after=9)
        self.assertEqual(policy.hold_back, 2)


class TestTrimming(unittest.TestCase):
    """Trimming is what keeps pass time flat however long you talk."""

    def test_committed_segments_are_trimmed(self):
        segs = [seg("one two", 0.0, 1.0), seg("three four", 1.0, 2.0),
                seg("five", 2.0, 3.0)]
        dropped, secs = plan_trim(segs, committed_count=4, window_dur_s=10.0)
        self.assertEqual(dropped, 4)
        self.assertEqual(secs, 2.0)

    def test_uncommitted_segments_are_kept(self):
        segs = [seg("one two", 0.0, 1.0), seg("three", 1.0, 2.0),
                seg("four", 2.0, 3.0)]
        dropped, _ = plan_trim(segs, committed_count=1, window_dur_s=10.0)
        self.assertEqual(dropped, 0, "a partly-typed segment must not be trimmed")

    def test_the_active_segment_is_never_trimmed(self):
        # segs[-1] is still being spoken.
        segs = [seg("one", 0.0, 1.0)]
        dropped, _ = plan_trim(segs, committed_count=1, window_dur_s=10.0)
        self.assertEqual(dropped, 0)

    def test_the_guard_protects_recent_audio(self):
        segs = [seg("one", 0.0, 2.8), seg("two", 2.8, 3.0)]
        dropped, _ = plan_trim(segs, committed_count=2, window_dur_s=3.0)
        self.assertEqual(dropped, 0, "within 0.5s of the window edge")

    def test_the_guard_relaxes_once_the_window_is_over_the_cap(self):
        # Speech with no pauses would otherwise grow the window forever.
        segs = [seg("one", 0.0, 39.7), seg("two", 39.7, 40.0)]
        self.assertEqual(plan_trim(segs, 2, 40.0, max_window_s=0)[0], 0)
        self.assertEqual(plan_trim(segs, 2, 40.0, max_window_s=30)[0], 1)

    def test_no_segments(self):
        self.assertEqual(plan_trim([], 5, 10.0), (0, 0.0))


class TestStreamState(unittest.TestCase):
    def test_first_pass_types_nothing(self):
        state = StreamState(sr=SR)
        step = state.step([seg("hello world", 0.0, 1.0)], SR)
        self.assertFalse(step.has_new)
        self.assertEqual(state.committed, [])

    def test_second_agreeing_pass_types_the_stable_prefix(self):
        state = StreamState(sr=SR)
        state.step([seg("hello world", 0.0, 1.0)], SR)
        step = state.step([seg("hello world there", 0.0, 1.5)], int(1.5 * SR))
        self.assertEqual(step.new_words, ["hello"])   # "world" held back
        self.assertEqual(state.committed, ["hello"])

    def test_a_revised_word_is_never_typed(self):
        state = StreamState(sr=SR)
        state.step([seg("the cot", 0.0, 1.0)], SR)
        step = state.step([seg("the cat sat", 0.0, 1.5)], int(1.5 * SR))
        self.assertNotIn("cot", step.new_words)

    def test_words_are_never_typed_twice(self):
        state = StreamState(sr=SR)
        typed = []
        for words, dur in [("a b", 1.0), ("a b c", 1.5), ("a b c d", 2.0),
                           ("a b c d", 2.5)]:
            step = state.step([seg(words, 0.0, dur)], int(dur * SR))
            typed.extend(step.new_words)
        self.assertEqual(typed, ["a", "b", "c", "d"])

    def test_can_type_false_records_but_commits_nothing(self):
        # The dictation hotkey is physically held: synthetic keystrokes would
        # arrive as Alt+char and be eaten by the target app.
        state = StreamState(sr=SR)
        state.step([seg("hello world", 0.0, 1.0)], SR, can_type=False)
        step = state.step([seg("hello world", 0.0, 1.0)], SR, can_type=False)
        self.assertFalse(step.has_new)
        self.assertEqual(state.committed, [])

    def test_trim_advances_t0_and_drops_committed_words(self):
        state = StreamState(sr=SR)
        segs = [seg("one two", 0.0, 1.0), seg("three", 1.0, 2.0),
                seg("four", 2.0, 3.0)]
        state.step(segs, int(10 * SR))
        state.step(segs, int(10 * SR))       # settled → all three commit
        self.assertEqual(state.committed[-1:], ["four"])
        self.assertGreater(state.t0, 0)
        self.assertNotIn("one", state.committed)

    def test_empty_hypothesis_is_a_no_op(self):
        state = StreamState(sr=SR)
        step = state.step([], SR)
        self.assertFalse(step.has_new)
        self.assertEqual(state.t0, 0)


class TestAlignRemainder(unittest.TestCase):
    """The stream/tail boundary — where a duplicated word actually came from."""

    def test_exact_prefix(self):
        self.assertEqual(
            align_remainder(["push", "the", "code"],
                            ["push", "the", "code", "to", "github"]),
            ["to", "github"])

    def test_nothing_committed_yet(self):
        self.assertEqual(align_remainder([], ["a", "b"]), ["a", "b"])

    def test_nothing_left_to_type(self):
        self.assertEqual(align_remainder(["a", "b"], ["a", "b"]), [])

    def test_a_repeated_boundary_word_is_not_typed_twice(self):
        # The real regression: the final pass emits "to" once, index slicing
        # lands before it, and the user gets "push the code to to get hub".
        self.assertEqual(
            align_remainder(["push", "the", "code", "to"],
                            ["push", "the", "code", "to", "get", "hub"]),
            ["get", "hub"])

    def test_punctuation_drift_on_the_boundary_word(self):
        # The streamer typed "world", the final pass says "world," — same word.
        self.assertEqual(
            align_remainder(["hello", "world"], ["hello", "world,", "again"]),
            ["again"])

    def test_case_drift(self):
        self.assertEqual(
            align_remainder(["hello", "WORLD"], ["Hello", "world", "again"]),
            ["again"])

    def test_overlap_after_a_disagreeing_prefix(self):
        # The final pass re-decoded the window differently at the front but
        # converges: continue after the largest tail/head overlap.
        self.assertEqual(
            align_remainder(["um", "the", "cat"], ["the", "cat", "sat"]),
            ["sat"])

    def test_total_disagreement_falls_back_to_counting(self):
        out = align_remainder(["a", "b", "c"], ["x", "y", "z", "w"])
        self.assertEqual(out, ["w"])

    def test_passes_disagreeing_on_word_boundaries(self):
        # The real failure: base.en heard "GitHub" while streaming and
        # "get hub" on the final pass. Different lengths, no common prefix, no
        # tail/head overlap - counting re-typed the tail as
        # "...to GitHub today. get hub today."
        self.assertEqual(
            align_remainder(["push", "to", "GitHub", "today."],
                            ["push", "to", "get", "hub", "today."]),
            [])

    def test_boundary_disagreement_still_yields_genuinely_new_words(self):
        self.assertEqual(
            align_remainder(["push", "to", "GitHub", "today."],
                            ["push", "to", "get", "hub", "today.", "and",
                             "tell", "me"]),
            ["and", "tell", "me"])

    def test_empty_final_pass(self):
        self.assertEqual(align_remainder(["a"], []), [])

    def test_decoder_repeating_the_seam_word_is_dropped(self):
        # The live-path failure: the final pass genuinely decodes the boundary
        # word twice, so nothing is misaligned and alignment alone cannot help.
        # committed ends "...to"; the final pass emits "to get hub" again.
        self.assertEqual(
            align_remainder(["push", "the", "code", "to"],
                            ["push", "the", "code", "to", "to", "get", "hub"]),
            ["get", "hub"])

    def test_seam_dedup_ignores_case_and_punctuation(self):
        self.assertEqual(
            align_remainder(["hello", "World"], ["hello", "World", "world,", "again"]),
            ["again"])

    def test_a_repeat_further_along_is_left_alone(self):
        # Only the exact seam is de-duplicated. A doubled word later in the
        # remainder is the speaker's, not the decoder's.
        self.assertEqual(
            align_remainder(["a", "b"], ["a", "b", "c", "d", "d", "e"]),
            ["c", "d", "d", "e"])

    def test_legitimate_repeats_not_on_the_seam_survive(self):
        self.assertEqual(
            align_remainder(["she", "said"], ["she", "said", "that", "that", "was", "fine"]),
            ["that", "that", "was", "fine"])


if __name__ == "__main__":
    unittest.main()
