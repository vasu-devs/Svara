"""LiveScreen: raw live-typed words on screen, rewritten span by span with the
fewest keystrokes. Pure, headless."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.streaming import LiveScreen  # noqa: E402


class TestLiveScreen(unittest.TestCase):
    def test_append_types_words_with_trailing_spaces(self):
        s = LiveScreen()
        self.assertEqual(s.append(["do", "2", "plus", "2"]), "do 2 plus 2 ")
        self.assertEqual(s.marks, [0, 3, 5, 10])

    def test_rewrite_only_backspaces_from_the_span_start(self):
        s = LiveScreen()
        s.append(["do", "2", "plus", "2", "nah", "I", "meant", "3", "plus", "3."])
        s.append(["and", "then"])
        retract, typed = s.rewrite(0, 10, "Do 3+3.")
        self.assertEqual(retract, len("do 2 plus 2 nah I meant 3 plus 3. and then "))
        self.assertEqual(typed, "Do 3+3. and then ")
        self.assertEqual(s.text, "Do 3+3. and then ")
        self.assertEqual(s.raw(10, None), "and then ")
        # the next span starts where the raw suffix now sits
        retract, typed = s.rewrite(10, None, "And then.")
        self.assertEqual(retract, len("and then "))
        self.assertEqual(s.text, "Do 3+3. And then. ")

    def test_empty_polish_drops_the_span(self):
        s = LiveScreen()
        s.append(["um", "uh"])
        s.append(["hello"])
        retract, typed = s.rewrite(0, 2, "")
        self.assertEqual((retract, typed), (len("um uh hello "), "hello "))
        self.assertEqual(s.text, "hello ")

    def test_rewrite_past_the_end_appends(self):
        s = LiveScreen()
        s.append(["one"])
        retract, typed = s.rewrite(1, None, "two.")
        self.assertEqual((retract, typed), (0, "two. "))
        self.assertEqual(s.text, "one two. ")


class TestSameWords(unittest.TestCase):
    def test_case_and_punctuation_do_not_count_as_a_change(self):
        from mywhisper.streaming import same_words
        self.assertTrue(same_words("so the island feels lame ", "So, the island feels lame."))
        self.assertFalse(same_words("do 2 plus 2 no I meant 3 ", "Do 3+3."))
        self.assertFalse(same_words("um so meet at five ", "Meet at five."))


if __name__ == "__main__":
    unittest.main(verbosity=2)
