"""IncrementalFinalizer: trimmed audio is decoded and polished while the user
is still talking; release pays for the tail only. Headless, no model."""

import sys
import time
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mywhisper.incremental import IncrementalFinalizer  # noqa: E402


def chunk(*words):
    """Audio stand-in: one sample per word; the fake decoder recovers the text."""
    chunk._words[len(chunk._words)] = words
    return np.full(len(words), len(chunk._words) - 1, dtype=np.float32)


chunk._words = {}


def fake_transcribe(audio, prompt=None):
    out = []
    for key in sorted(set(int(x) for x in audio)):
        out.append((" ".join(chunk._words[key]), 0.0, 1.0))
    fake_transcribe.prompts.append(prompt)
    return out


fake_transcribe.prompts = []


def wait_chunks(fin, n, s=2.0):
    deadline = time.monotonic() + s
    while fin.chunks < n and time.monotonic() < deadline:
        time.sleep(0.01)


class TestIncrementalFinalizer(unittest.TestCase):
    def setUp(self):
        chunk._words.clear()
        fake_transcribe.prompts.clear()

    def test_chunks_are_decoded_in_order_and_polished_by_sentence_group(self):
        calls = []

        def polish(text):
            calls.append(text)
            return text.upper()

        fin = IncrementalFinalizer(fake_transcribe, polish, min_span_words=4, min_decode_s=0)
        fin.push(chunk("one", "two"), ["one", "two"])
        fin.push(chunk("three", "four."), ["three", "four."])   # ≥4 words + sentence end
        fin.push(chunk("five", "six"), ["five", "six"])          # waits: no sentence end yet
        wait_chunks(fin, 3)
        self.assertEqual(calls, ["one two three four."])
        self.assertEqual(fin.take_ready(), [(0, 4, "ONE TWO THREE FOUR.")])
        self.assertEqual(fin.take_ready(), [])
        out = fin.finish(chunk("seven."))
        self.assertEqual(out, "ONE TWO THREE FOUR. FIVE SIX SEVEN.")
        self.assertEqual(calls, ["one two three four.", "five six seven."])
        self.assertEqual(fin.take_ready(), [(4, None, "FIVE SIX SEVEN.")])
        self.assertEqual(fin.chunks, 4)

    def test_small_chunks_are_merged_and_decoded_with_the_words_before_as_prompt(self):
        fin = IncrementalFinalizer(fake_transcribe, lambda t: t, min_span_words=2,
                                   min_decode_s=3 / 16000)   # 3 "samples" of audio
        fin.push(chunk("a"), ["a"])
        fin.push(chunk("b."), ["b."])
        wait_chunks(fin, 1, 0.3)
        self.assertEqual(fin.chunks, 0, "two samples: still buffered")
        fin.push(chunk("c"), ["c"])
        wait_chunks(fin, 1)
        self.assertEqual(fin.chunks, 1)
        fin.finish(chunk("d."))
        self.assertEqual(fake_transcribe.prompts, [None, "a b. c"])
        self.assertEqual(fin.text, "a b. c d.")

    def test_a_decode_that_loses_most_words_keeps_the_streams_words(self):
        def lossy(audio, prompt=None):
            return [("x", 0.0, 1.0)]

        fin = IncrementalFinalizer(lossy, lambda t: t, min_decode_s=0)
        fin.push(chunk("one", "two", "three", "four"), ["one", "two", "three", "four"])
        self.assertEqual(fin.finish(None), "one two three four")

    def test_a_polish_that_drops_most_words_is_refused(self):
        fin = IncrementalFinalizer(fake_transcribe, lambda t: "nope", min_decode_s=0)
        self.assertEqual(fin.finish(chunk("keep", "all", "of", "these", "words.")),
                         "keep all of these words.")

    def test_a_tail_that_closes_a_sentence_is_not_closed_twice(self):
        fin = IncrementalFinalizer(fake_transcribe, lambda t: t, min_span_words=2, min_decode_s=0)
        fin.push(chunk("one"), ["one"])
        self.assertEqual(fin.finish(chunk("two.")), "one two.")
        self.assertEqual(fin.take_ready(), [(0, None, "one two.")])

    def test_finish_can_swap_in_a_quick_polish_for_the_last_span(self):
        calls = []
        fin = IncrementalFinalizer(fake_transcribe, lambda t: calls.append(("slow", t)) or t,
                                   min_span_words=2, min_decode_s=0)
        fin.push(chunk("one", "two."), ["one", "two."])
        wait_chunks(fin, 1)
        out = fin.finish(chunk("three."), quick_polish=lambda t: calls.append(("quick", t)) or t.upper())
        self.assertEqual(out, "one two. THREE.")
        self.assertEqual(calls, [("slow", "one two."), ("quick", "three.")])

    def test_finish_with_nothing_pushed_is_the_batch_path(self):
        fin = IncrementalFinalizer(fake_transcribe, lambda t: t)
        self.assertEqual(fin.finish(chunk("just", "the", "tail")), "just the tail")

    def test_empty_tail_and_empty_speech_give_empty_text(self):
        fin = IncrementalFinalizer(fake_transcribe, lambda t: t)
        self.assertEqual(fin.finish(np.zeros(0, dtype=np.float32)), "")
        self.assertEqual(fin.take_ready(), [(0, None, "")])

    def test_a_failing_chunk_does_not_lose_the_rest(self):
        def transcribe(audio, prompt=None):
            if int(audio[0]) == 0:
                raise RuntimeError("decoder hiccup")
            return fake_transcribe(audio, prompt)

        fin = IncrementalFinalizer(transcribe, lambda t: t, min_decode_s=0)
        fin.push(chunk("boom"), ["boom"])
        wait_chunks(fin, 1, 0.3)
        fin.push(chunk("kept."), ["kept."])
        self.assertEqual(fin.finish(chunk("tail.")), "kept. tail.")

    def test_cancel_stops_the_thread(self):
        fin = IncrementalFinalizer(fake_transcribe, lambda t: t)
        fin.cancel()
        fin._thread.join(timeout=1)
        self.assertFalse(fin._thread.is_alive())


if __name__ == "__main__":
    unittest.main(verbosity=2)
