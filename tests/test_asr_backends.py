"""Unit tests for the multi-engine ASR layer (v0.6): registry fallbacks,
Moonshine's decode guards, and hybrid routing. All engines are mocked — the
real-model integration lives in test_livepath.py and local `--bench` runs.

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_asr_backends -v
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from mywhisper import asr  # noqa: E402
from mywhisper.asr.base import Segment  # noqa: E402
from mywhisper.asr.moonshine import (_bucket_pad, _dedupe_loop,  # noqa: E402
                                     _looping)
from mywhisper.transcriber import Transcriber  # noqa: E402

MCFG = {"name": "base.en", "device": "cpu", "compute_type": "int8",
        "language": "en", "task": "transcribe", "beam_size": 2,
        "partial_beam_size": 2, "initial_prompt": None, "download_root": None,
        "stream_language": "en", "moonshine": "tiny", "batched": "off"}


class TestRegistry(unittest.TestCase):
    def test_unknown_backend_falls_back(self):
        with mock.patch("mywhisper.asr.faster_whisper.FasterWhisperBackend") as fw:
            asr.create(dict(MCFG), "quantum-decoder")
            fw.assert_called_once()

    def test_moonshine_refused_for_non_english(self):
        with mock.patch("mywhisper.asr.faster_whisper.FasterWhisperBackend") as fw:
            asr.create(dict(MCFG, language="hi"), "moonshine")
            fw.assert_called_once()

    def test_moonshine_load_failure_falls_back(self):
        with mock.patch("mywhisper.asr.moonshine.MoonshineBackend",
                        side_effect=RuntimeError("no onnxruntime")), \
                mock.patch("mywhisper.asr.faster_whisper.FasterWhisperBackend") as fw:
            asr.create(dict(MCFG), "moonshine")
            fw.assert_called_once()


class TestDecodeGuards(unittest.TestCase):
    def test_looping_detects_repeated_tail(self):
        base = [1, 5, 9, 3]
        self.assertTrue(_looping(base + [7, 8, 2, 4] + [7, 8, 2, 4]))
        self.assertFalse(_looping(base + [7, 8, 2, 4] + [7, 8, 2, 5]))
        self.assertFalse(_looping([1, 2, 3]))  # too short to loop

    def test_bucket_pad_bounds_shapes(self):
        for n, want in ((100, 8000), (8000, 8000), (8001, 16000),
                        (40000, 40000)):
            out = _bucket_pad(np.zeros(n, dtype=np.float32))
            self.assertEqual(len(out), want, f"n={n}")
        # padding is silence, and the original samples are untouched
        a = np.ones(1000, dtype=np.float32)
        out = _bucket_pad(a)
        self.assertTrue((out[:1000] == 1.0).all())
        self.assertTrue((out[1000:] == 0.0).all())

    def test_dedupe_loop_collapses_phrase_repeats(self):
        self.assertEqual(
            _dedupe_loop("This is the sub. This is the sub. This is the sub."),
            "This is the sub.")
        clean = "had had a word and that that was fine"
        self.assertEqual(_dedupe_loop(clean), clean)  # 2 repeats stay


class _FakeEngine:
    """Records which methods were called; returns tagged segments."""

    device_used = "cpu"
    compute_used = "fake"
    model = None

    def __init__(self, tag):
        self.tag = tag
        self.calls = []

    @property
    def capabilities(self):
        from mywhisper.asr.base import BackendCaps
        return BackendCaps(name=self.tag)

    def transcribe(self, audio):
        self.calls.append("transcribe")
        return [Segment(f"{self.tag}-final", 0.0, 1.0)]

    def transcribe_partial(self, audio, prompt=None):
        self.calls.append("partial")
        return [Segment(f"{self.tag}-partial", 0.0, 1.0)]

    def transcribe_final_window(self, audio):
        self.calls.append("final_window")
        return [Segment(f"{self.tag}-window", 0.0, 1.0)]


class TestHybridRouting(unittest.TestCase):
    def _hybrid(self, language="en"):
        from mywhisper.asr.hybrid import HybridBackend
        cfg = dict(MCFG, language=language)
        with mock.patch("mywhisper.asr.faster_whisper.FasterWhisperBackend",
                        return_value=_FakeEngine("fw")), \
                mock.patch("mywhisper.asr.moonshine.MoonshineBackend",
                           return_value=_FakeEngine("moon")):
            h = HybridBackend(cfg)
        return h, cfg

    def test_partials_go_to_moonshine_finals_to_whisper(self):
        h, _ = self._hybrid()
        audio = np.zeros(1600, dtype=np.float32)
        self.assertEqual(h.transcribe_partial(audio)[0].text, "moon-partial")
        self.assertEqual(h.transcribe(audio)[0].text, "fw-final")
        # the live finaliser must be whisper-quality, not moonshine
        self.assertEqual(h.transcribe_final_window(audio)[0].text, "fw-partial")

    def test_language_switch_reroutes_partials_live(self):
        h, cfg = self._hybrid()
        audio = np.zeros(1600, dtype=np.float32)
        cfg["language"] = "hi"   # user picks Hindi in the tray, no restart
        self.assertEqual(h.transcribe_partial(audio)[0].text, "fw-partial")
        cfg["language"] = "en"
        self.assertEqual(h.transcribe_partial(audio)[0].text, "moon-partial")

    def test_translate_task_reroutes_partials(self):
        h, cfg = self._hybrid()
        cfg["task"] = "translate"  # moonshine cannot translate
        audio = np.zeros(1600, dtype=np.float32)
        self.assertEqual(h.transcribe_partial(audio)[0].text, "fw-partial")

    def test_moonshine_failure_degrades_to_pure_whisper(self):
        from mywhisper.asr.hybrid import HybridBackend
        with mock.patch("mywhisper.asr.faster_whisper.FasterWhisperBackend",
                        return_value=_FakeEngine("fw")), \
                mock.patch("mywhisper.asr.moonshine.MoonshineBackend",
                           side_effect=RuntimeError("download blocked")):
            h = HybridBackend(dict(MCFG))
        audio = np.zeros(1600, dtype=np.float32)
        self.assertEqual(h.transcribe_partial(audio)[0].text, "fw-partial")
        self.assertEqual(h.capabilities.name, "fw")


class TestTranscriberForwarding(unittest.TestCase):
    def test_final_window_falls_back_to_partial_on_minimal_backend(self):
        class Minimal:
            device_used = compute_used = "x"

            def transcribe(self, audio):
                return []

            def transcribe_partial(self, audio, prompt=None):
                return [Segment("partial-only", 0.0, 1.0)]

        with mock.patch("mywhisper.asr.create", return_value=Minimal()):
            t = Transcriber(dict(MCFG))
        out = t.transcribe_final_window(np.zeros(160, dtype=np.float32))
        self.assertEqual(out[0].text, "partial-only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
