"""Semantic endpointing — telling "thinking" apart from "finished".

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_endpoint -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.endpoint import looks_complete, should_finish  # noqa: E402


class TestLooksComplete(unittest.TestCase):
    def test_terminal_punctuation_ends_it(self):
        for text in ("Send it to the team.", "Are you there?", "Stop!",
                     "He said \"go.\"", "そうですね。"):
            self.assertTrue(looks_complete(text), text)

    def test_a_dangling_conjunction_is_someone_thinking(self):
        for text in ("send it to the team and", "we should go because",
                     "I want to talk about the thing but"):
            self.assertFalse(looks_complete(text), text)

    def test_a_dangling_preposition_is_someone_thinking(self):
        for text in ("put the file in", "send this to", "talk about the"):
            self.assertFalse(looks_complete(text), text)

    def test_a_dangling_auxiliary_is_someone_thinking(self):
        for text in ("I think we should", "the deploy is", "we are going"):
            self.assertFalse(looks_complete(text), text)

    def test_hesitation_is_not_an_ending(self):
        self.assertFalse(looks_complete("so the plan is um"))

    def test_a_trailing_comma_says_more_is_coming(self):
        self.assertFalse(looks_complete("first we build the thing,"))

    def test_a_complete_clause_without_punctuation_counts(self):
        # Whisper often omits the full stop; the words still finished.
        self.assertTrue(looks_complete("send it to the team tomorrow"))

    def test_too_few_words_waits(self):
        # A stray word the VAD caught is not a sentence.
        self.assertFalse(looks_complete("okay"))
        self.assertFalse(looks_complete("the thing"))

    def test_empty(self):
        self.assertFalse(looks_complete(""))
        self.assertFalse(looks_complete("   "))
        self.assertFalse(looks_complete("..."))


class TestShouldFinish(unittest.TestCase):
    def test_below_the_threshold_never_fires(self):
        self.assertFalse(should_finish("done.", 500, 900))
        self.assertFalse(should_finish("done.", 500, 900, semantic=True))

    def test_without_semantic_the_timer_alone_decides(self):
        # The pre-0.5 behaviour, preserved exactly.
        self.assertTrue(should_finish("and then we", 950, 900))

    def test_semantic_keeps_listening_through_a_mid_clause_pause(self):
        self.assertFalse(should_finish("send it to the team and", 950, 900,
                                       max_silence_ms=2500, semantic=True))

    def test_semantic_stops_on_a_finished_sentence(self):
        self.assertTrue(should_finish("send it to the team.", 950, 900,
                                      max_silence_ms=2500, semantic=True))

    def test_the_ceiling_always_wins(self):
        # An unfinished sentence must not hold the recording open forever.
        self.assertTrue(should_finish("send it to the team and", 2600, 900,
                                      max_silence_ms=2500, semantic=True))

    def test_no_ceiling_configured_still_terminates_on_completion(self):
        self.assertTrue(should_finish("send it to the team today", 5000, 900,
                                      max_silence_ms=0, semantic=True))

    def test_empty_transcript_waits_rather_than_cutting_off(self):
        # No streamed text yet (streaming off, or nothing decoded). Better to
        # hit the ceiling than to stop someone who has said nothing decodable.
        self.assertFalse(should_finish("", 950, 900, max_silence_ms=2500,
                                       semantic=True))
        self.assertTrue(should_finish("", 3000, 900, max_silence_ms=2500,
                                      semantic=True))


if __name__ == "__main__":
    unittest.main()
