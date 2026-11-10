"""Spoken edit commands erase exactly the words the user asked for."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.pipeline.text_rules import apply_edit_commands  # noqa: E402


class TestEditCommands(unittest.TestCase):
    def run_cmd(self, text):
        return " ".join(apply_edit_commands(text.split()))

    def test_remove_the_last_n_words(self):
        self.assertEqual(self.run_cmd("go ahead do 2 plus 2 remove the last three words and 3 plus 3"),
                         "go ahead do and 3 plus 3")
        self.assertEqual(self.run_cmd("one two three four delete last 2 words"), "one two")

    def test_last_sentence_and_scrap_that_go_back_to_the_sentence_end(self):
        self.assertEqual(self.run_cmd("Keep this. Drop all of that, scrap that please"),
                         "Keep this. please")
        self.assertEqual(self.run_cmd("Keep this. Remove this last part"), "Keep this.")

    def test_no_command_is_untouched(self):
        self.assertEqual(self.run_cmd("the last word of the sentence"), "the last word of the sentence")

    def test_more_words_than_present_clears_to_the_start(self):
        self.assertEqual(self.run_cmd("a b remove the last ten words c"), "c")


if __name__ == "__main__":
    unittest.main(verbosity=2)
