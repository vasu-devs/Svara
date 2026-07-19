"""Integration test for the LIVE-STREAMING dictation path — the one flow no
unit test covered: MyWhisperApp's _streamer (LocalAgreement live typing) +
_worker (final tail) driven by real faster-whisper over real speech audio,
with a fake microphone replaying a TTS wav.

Verifies the v0.4 bookkeeping end-to-end: streamed words + final tail are
typed exactly once (no duplication/drops at the boundary), and the History
row matches what was typed.

Heavy (loads base.en, ~30-60s on CPU) and needs the full STT stack, so it
skips automatically where faster-whisper isn't installed (CI).

Run:  .venv\\Scripts\\python.exe -m unittest tests.test_livepath -v
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import numpy as np
    from faster_whisper import WhisperModel  # noqa: F401
    HAVE_STT = True
except ImportError:
    HAVE_STT = False

SPOKEN = ("Hello world. This is the Svara integration test. "
          "Please push the code to get hub today.")


def synthesize_tts(dest: Path) -> bool:
    """Windows SAPI TTS → 16 kHz mono wav. The test provides its own speech
    so it never depends on a microphone or a checked-in binary asset."""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
        "16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s.SetOutputToWaveFile('{dest}', $f); "
        f"$s.Speak('{SPOKEN}'); $s.Dispose()")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       check=True, capture_output=True, timeout=90)
        return dest.is_file() and dest.stat().st_size > 32000
    except (subprocess.SubprocessError, OSError):
        return False


class FakeRecorder:
    """Replays a wav as if it were live mic input: snapshot() grows in real
    time, stop() returns everything — the exact surface app.py touches."""

    def __init__(self, audio, sr):
        self._audio = audio
        self.sr = sr
        self.gain = 1.0
        self._recording = False
        self._t0 = 0.0
        self.discarded = False

    # -- control used by the app --
    def start(self):
        self._recording = True
        self._t0 = time.monotonic()

    def _pos(self):
        return min(len(self._audio),
                   int((time.monotonic() - self._t0) * self.sr))

    def snapshot(self):
        if not self._recording:
            return None
        p = self._pos()
        return self._audio[:p].copy() if p else None

    def stop(self, keep_tail=False):
        self._recording = False
        return self._audio.copy()

    @property
    def recording(self):
        return self._recording

    def elapsed(self):
        return time.monotonic() - self._t0 if self._recording else 0.0

    def silence_ms(self):
        return 0.0

    def speech_ms(self):
        return 1e9

    @property
    def level(self):
        return 0.5

    def open(self):
        pass

    def close(self):
        pass

    def ensure_alive(self):
        return True

    def set_spill_path(self, p):
        pass

    def discard_recovery(self):
        self.discarded = True


@unittest.skipUnless(HAVE_STT, "needs faster-whisper (local run only)")
@unittest.skipUnless(os.name == "nt", "uses Windows SAPI TTS")
class TestLiveStreamingPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tts_dir = Path(tempfile.mkdtemp(prefix="svara-tts-"))
        cls.tts_wav = cls.tts_dir / "tts.wav"
        if not synthesize_tts(cls.tts_wav):
            raise unittest.SkipTest("SAPI TTS unavailable")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tts_dir, ignore_errors=True)

    def test_live_typing_no_dupes_no_drops_history_matches(self):
        w = wave.open(str(self.tts_wav))
        sr = w.getframerate()
        audio = (np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                 .astype(np.float32) / 32768.0)

        tmp = Path(tempfile.mkdtemp(prefix="svara-live-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))

        typed: list[str] = []
        fake_rec = FakeRecorder(audio, sr)

        from mywhisper import config as config_mod
        cfg = config_mod.load(None)
        cfg["model"].update(name="base.en", device="cpu", compute_type="int8")
        cfg["ui"]["tray"] = False
        cfg["ui"]["overlay"] = False
        cfg["context"]["enabled"] = False   # determinism: no foreground probe
        cfg["update"]["check"] = False
        cfg["streaming"]["mode"] = "live"

        from mywhisper.transcriber import Transcriber
        transcriber = Transcriber(cfg["model"])

        overlay = mock.MagicMock()
        listener = mock.MagicMock()
        listener.held = False
        listener.locked = False

        with mock.patch("mywhisper.app.Recorder", return_value=fake_rec), \
                mock.patch("mywhisper.app.Overlay", return_value=overlay), \
                mock.patch("mywhisper.app.create_listener",
                           return_value=listener), \
                mock.patch("mywhisper.paths.base_dir", return_value=tmp):
            from mywhisper.app import MyWhisperApp
            app = MyWhisperApp(cfg, no_tray=True, transcriber=transcriber)
            app.injector = mock.MagicMock()
            app.injector.inject_stream.side_effect = \
                lambda t: (typed.append(t), len(t))[1]
            app.injector.inject.side_effect = \
                lambda t: (typed.append(t), len(t))[1]

            worker = threading.Thread(target=app._worker, daemon=True)
            worker.start()

            app.start_recording()          # spawns the real _streamer thread
            time.sleep(len(audio) / sr + 0.5)  # "speak" the whole clip
            app.stop_recording()           # 0.4s tail-grace → queue → worker

            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if not fake_rec.recording and app._queue.empty() \
                        and not app._stopping and typed:
                    time.sleep(2.0)        # let the worker finish the tail
                    if app._queue.empty():
                        break
                time.sleep(0.5)
            app._shutdown.set()

        full = " ".join(t.strip() for t in typed if t.strip())
        norm = re.sub(r"[^a-z0-9 ]", "", full.lower())
        norm = re.sub(r"\s+", " ", norm)
        print("TYPED:", full)

        self.assertTrue(typed, "nothing was typed by the live path")
        self.assertIn("hello world", norm)
        self.assertIn("integration test", norm)
        # the boundary bug this test exists for: streamed words typed again
        # by the final tail (or dropped between the two)
        for phrase in ("hello world", "integration test", "svara"):
            self.assertEqual(norm.count(phrase), 1,
                             f"{phrase!r} typed {norm.count(phrase)}x — "
                             "stream/tail boundary duplicated or dropped words")

        rows = app.history.recent(5)
        self.assertTrue(rows, "live dictation was not recorded to history")
        hist_norm = re.sub(r"[^a-z0-9 ]", "", rows[0][3].lower())
        hist_norm = re.sub(r"\s+", " ", hist_norm)
        self.assertEqual(hist_norm, norm.strip(),
                         "history text diverged from what was typed")
        self.assertTrue(fake_rec.discarded,
                        "recovery file not discarded after successful typing")
        app.history.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
