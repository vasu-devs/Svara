"""VoiceSession: which line is next, how a take is saved, resuming."""

import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.voice_session import LINES, STYLES, VoiceSession  # noqa: E402

TWO_LINES = ["Alpha beta.", "Gamma delta."]
TWO_STYLES = [("normal", "Normal"), ("fast", "Fast")]


class TestVoiceSession(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name) / "voice"

    def tearDown(self):
        self.dir.cleanup()

    def test_the_shipped_set_is_sixty_lines_plus_two_short_style_samples(self):
        self.assertEqual(len(LINES), 60)
        self.assertEqual([c for _k, _h, c in STYLES], [60, 20, 20])
        s = VoiceSession(self.root)
        self.assertEqual(s.total, 100)
        self.assertEqual([p["total"] for p in s.progress()], [60, 20, 20])

    def test_takes_advance_through_every_line_of_a_style_then_the_next_style(self):
        s = VoiceSession(self.root, TWO_LINES, TWO_STYLES)
        self.assertTrue(s.block_start())
        seen = []
        audio = np.zeros(16000, dtype=np.float32)
        while not s.finished:
            line_id, text, style = s.current
            seen.append(style)
            self.assertIsNotNone(s.save_take(audio))
        self.assertEqual(seen, ["normal", "normal", "fast", "fast"])
        self.assertEqual(s.done, 4)
        wavs = sorted(p.name for p in (self.root / "clips").glob("*.wav"))
        self.assertEqual(len(wavs), 4)
        with wave.open(str(self.root / "clips" / wavs[0])) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()),
                             (1, 2, 16000, 16000))
        rec = json.loads((self.root / "lines.jsonl").read_text().splitlines()[0])
        self.assertEqual(set(rec), {"line_id", "text", "style", "take", "wav", "duration_s", "recorded_at"})
        self.assertEqual(rec["text"], TWO_LINES[rec["line_id"] - 1])

    def test_upcoming_and_progress_feed_the_teleprompter(self):
        s = VoiceSession(self.root, TWO_LINES, TWO_STYLES)
        first = s.current[1]
        nxt = s.upcoming()
        self.assertIn(nxt, TWO_LINES)
        self.assertNotEqual(nxt, first)
        s.save_take(np.zeros(16000, dtype=np.float32))
        self.assertEqual(s.current[1], nxt)
        self.assertEqual([p["done"] for p in s.progress()], [1, 0])
        while not s.finished:
            s.save_take(np.zeros(16000, dtype=np.float32))
        self.assertIsNone(s.upcoming())

    def test_matches_accepts_a_misread_word_and_rejects_other_speech(self):
        from mywhisper.voice_session import matches
        line = "The boy was there when the sun rose."
        self.assertTrue(matches(line, "the boy was there when the sun rose"))
        self.assertTrue(matches(line, "the boy was there when the sun rows"))
        self.assertFalse(matches(line, "did we push out something new today"))
        self.assertFalse(matches(line, "hello"))
        self.assertFalse(matches(line, ""))

    def test_spoken_and_written_numbers_score_as_the_same_words(self):
        from mywhisper.bench import wer
        from mywhisper.voice_session import matches
        for ref, hyp in [
                ("Twenty twenty-six, nineteen ninety-nine, two thousand and five.", "2026, 1999, 2005."),
                ("Meet me at 4:45 on the 23rd of March, not the 24th.",
                 "meet me at four forty five on the twenty third of march not the twenty fourth"),
                ("The invoice total is 1,250 dollars and 99 cents.",
                 "the invoice total is one thousand two hundred fifty dollars and ninety nine cents"),
                ("Call 555-0123 and ask for extension 42.",
                 "call five five five oh one two three and ask for extension forty two")]:
            self.assertEqual(wer(ref, hyp), 0.0, hyp)
            self.assertTrue(matches(ref, hyp))
        self.assertGreater(wer("Four hours of steady work.", "for hours of steady work"), 0)

    def test_a_key_slip_is_not_a_take(self):
        s = VoiceSession(self.root, TWO_LINES, TWO_STYLES)
        self.assertIsNone(s.save_take(np.zeros(1000, dtype=np.float32)))
        self.assertEqual(s.done, 0)

    def test_resume_and_skip(self):
        s = VoiceSession(self.root, TWO_LINES, TWO_STYLES)
        first = s.current
        s.save_take(np.zeros(16000, dtype=np.float32))
        s.skip()
        again = VoiceSession(self.root, TWO_LINES, TWO_STYLES)
        self.assertEqual(again.done, 1, "a skipped line is not persisted: it comes back next time")
        self.assertNotEqual(again.current, first)
        self.assertEqual(again.current[2], "normal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
