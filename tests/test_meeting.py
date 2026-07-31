"""Unit tests for meeting mode: the silence-gated Chunker (pure logic) and the
MeetingSession file/summary flow with transcription + LLM mocked. Capture
threads are not started — soundcard is never touched here.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_meeting -v
"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from mywhisper.asr.base import Segment  # noqa: E402
from mywhisper.meeting import SR, Chunker, MeetingSession, _ts  # noqa: E402

BLOCK = 1600  # 100 ms
LOUD = np.full(BLOCK, 0.1, dtype=np.float32)
QUIET = np.zeros(BLOCK, dtype=np.float32)


def run_blocks(ck, blocks, t0=0.0):
    out = []
    now = t0
    for b in blocks:
        out.extend(ck.feed(b, now))
        now += BLOCK / SR
    return out, now


class TestChunker(unittest.TestCase):
    def test_speech_then_silence_emits_one_chunk(self):
        ck = Chunker(silence_ms=700)
        chunks, _ = run_blocks(ck, [QUIET] * 3 + [LOUD] * 10 + [QUIET] * 8)
        self.assertEqual(len(chunks), 1)
        start, audio = chunks[0]
        self.assertGreaterEqual(len(audio) / SR, 1.0)  # speech + preroll

    def test_silence_only_emits_nothing(self):
        ck = Chunker()
        chunks, _ = run_blocks(ck, [QUIET] * 50)
        self.assertEqual(chunks, [])

    def test_noise_blip_is_dropped(self):
        ck = Chunker(min_speech_s=0.4)
        chunks, _ = run_blocks(ck, [QUIET] * 3 + [LOUD] * 2 + [QUIET] * 10)
        self.assertEqual(chunks, [], "0.2s of noise is not an utterance")

    def test_long_monologue_splits_at_ceiling(self):
        ck = Chunker(max_chunk_s=2.0, silence_ms=700)
        chunks, _ = run_blocks(ck, [LOUD] * 55 + [QUIET] * 10)
        self.assertGreaterEqual(len(chunks), 2,
                                "a 5.5s monologue must appear before it ends")

    def test_preroll_is_included(self):
        ck = Chunker(preroll_blocks=3)
        chunks, _ = run_blocks(ck, [QUIET] * 6 + [LOUD] * 10 + [QUIET] * 8)
        _start, audio = chunks[0]
        # 10 loud + up to 3 preroll + trailing silence blocks
        self.assertGreater(len(audio), 10 * BLOCK)

    def test_flush_emits_open_chunk(self):
        ck = Chunker()
        chunks, now = run_blocks(ck, [QUIET] * 3 + [LOUD] * 10)
        self.assertEqual(chunks, [])          # still open
        self.assertEqual(len(ck.flush(now)), 1)

    def test_constant_hiss_is_rate_bounded_not_unbounded(self):
        # A fan/hiss CAN read as speech at this layer (raising the floor
        # mid-speech would gate out real monologues — the worse bug). The
        # contract is: chunk emission is bounded by the max_chunk_s ceiling,
        # and downstream decode-VAD turns hiss chunks into nothing.
        ck = Chunker(max_chunk_s=2.0)
        hiss = np.full(BLOCK, 0.02, dtype=np.float32)
        chunks, _ = run_blocks(ck, [hiss] * 100)   # 10s of noisy room
        self.assertLessEqual(len(chunks), 6,
                             "hiss must not emit unbounded per-block chunks")

    def test_quiet_room_noise_floor_adapts(self):
        ck = Chunker()
        murmur = np.full(BLOCK, 0.003, dtype=np.float32)  # below abs floor
        run_blocks(ck, [murmur] * 100)
        self.assertGreater(ck._noise, 0.002,
                           "idle blocks must feed the noise estimate")


class _FakeTranscriber:
    def transcribe(self, audio):
        return [Segment(f"({len(audio) // BLOCK} blocks)", 0.0, 1.0)]


class TestMeetingSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="svara-meet-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        patcher = mock.patch("mywhisper.paths.meetings_dir",
                             return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _session(self, summary_result="- summary line", summary=True):
        llm = mock.MagicMock()
        llm.run_prompt.return_value = summary_result
        s = MeetingSession(get_transcriber=lambda: _FakeTranscriber(),
                           llm=llm, mcfg={"summary": summary},
                           notify=lambda *_: None)
        # start() without capture threads: set up the file exactly as start does
        with mock.patch.object(s, "_capture_mic"), \
                mock.patch.object(s, "_capture_loopback"), \
                mock.patch.object(s, "_transcribe_worker"):
            s.start()
        return s, llm

    def test_entries_append_live_and_finalise_sorted(self):
        s, llm = self._session()
        s._handle(12.0, "Them", np.zeros(BLOCK * 5, dtype=np.float32))
        s._handle(3.0, "You", np.zeros(BLOCK * 3, dtype=np.float32))
        live = s.path.read_text(encoding="utf-8")
        self.assertIn("**Them:**", live)

        s._stop.set()
        s._finish()
        final = s.path.read_text(encoding="utf-8")
        self.assertLess(final.index("**You:**"), final.index("**Them:**"),
                        "final transcript must be time-sorted")
        self.assertIn("## Summary", final)
        self.assertIn("- summary line", final)
        self.assertIn("never leave this machine", final)
        # the LLM saw a speaker-labelled transcript
        sent = llm.run_prompt.call_args[0][1]
        self.assertIn("You:", sent)
        self.assertIn("Them:", sent)

    def test_no_llm_still_writes_transcript(self):
        s, _ = self._session(summary_result=None)
        s._handle(1.0, "You", np.zeros(BLOCK * 3, dtype=np.float32))
        s._stop.set()
        s._finish()
        text = s.path.read_text(encoding="utf-8")
        self.assertIn("No local LLM was running", text)
        self.assertIn("**You:**", text)

    def test_empty_meeting_leaves_no_file(self):
        s, _ = self._session()
        s._stop.set()
        s._finish()
        self.assertFalse(s.path.exists(), "an empty meeting must not litter")

    def test_transcriber_failure_skips_entry(self):
        s, _ = self._session()
        broken = mock.MagicMock()
        broken.transcribe.side_effect = RuntimeError("model reloading")
        s.get_transcriber = lambda: broken
        s._handle(1.0, "You", np.zeros(BLOCK, dtype=np.float32))
        self.assertEqual(s.entries, [])

    def test_timestamp_format(self):
        self.assertEqual(_ts(62), "01:02")
        self.assertEqual(_ts(3723), "1:02:03")

    def test_unique_filenames(self):
        s1, _ = self._session()
        s2, _ = self._session()
        self.assertNotEqual(s1.path, s2.path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
