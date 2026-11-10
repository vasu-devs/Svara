"""End-to-end dictation check: real engines, real pipeline, fake mic and screen.

Run (Linux):  .venv/bin/python bench/e2e_dictation.py

Each clip in bench/corpus is played as if it were the microphone, in real
time, through the app exactly as a hands-free dictation runs: live partials,
commits typed at the "cursor", trimmed audio finalized in the background,
the cleanup pipeline and the local LLM polishing each sentence, polished
spans rewritten in place, the tail finished after the stop. The "cursor" is a
text buffer that applies every keystroke, backspace and paste, so what it
holds at the end is what a text field would hold.

Checks per clip: the final text matches the reference (word error rate after
the polish, which may legitimately fix punctuation and fillers), nothing was
typed twice, release-to-done time. Uses config-linux.yaml with Whisper on the
CPU so it can run next to the live Svara on an 8 GB GPU. Not part of the unit
suite: it loads models and takes about a minute.
"""

import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from mywhisper import config as config_mod  # noqa: E402
from mywhisper.bench import wer  # noqa: E402
from test_livepath import FakeRecorder  # noqa: E402


class Screen:
    """A text field: what the injector's calls would leave on screen."""

    def __init__(self):
        self.text = ""
        self.backspaced = 0
        self.lock = threading.Lock()

    def type(self, t, ctx=None):
        with self.lock:
            self.text += t
        return len(t)

    def retract(self, n):
        with self.lock:
            self.backspaced += n
            self.text = self.text[:max(0, len(self.text) - n)]


def run_clip(wav: Path, ref: str, cfg: dict, transcriber) -> dict:
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    rec = FakeRecorder(audio, sr)
    rec.voice_threshold = 0.005
    screen = Screen()
    listener = mock.MagicMock(held=False, locked=True)
    tmp = Path(tempfile.mkdtemp(prefix="svara-e2e-", dir="/var/tmp"))
    with mock.patch("mywhisper.app.Recorder", return_value=rec), \
            mock.patch("mywhisper.app.Overlay", return_value=mock.MagicMock()), \
            mock.patch("mywhisper.app.create_listener", return_value=listener), \
            mock.patch("mywhisper.paths.base_dir", return_value=tmp):
        from mywhisper.app import MyWhisperApp
        app = MyWhisperApp(cfg, no_tray=True, transcriber=transcriber)
        app.injector = mock.MagicMock()
        app.injector.inject_stream.side_effect = screen.type
        app.injector.inject.side_effect = screen.type
        app.injector.retract.side_effect = screen.retract
        app.injector.streams_into.return_value = True
        threading.Thread(target=app._worker, daemon=True).start()
        app.start_recording()
        time.sleep(len(audio) / sr + 0.3)
        live_text = screen.text
        t_stop = time.perf_counter()
        app.stop_recording()
        deadline = time.monotonic() + 120
        time.sleep(0.6)
        while time.monotonic() < deadline and (app._processing_pending or app._stopping
                                               or not app._queue.empty()):
            time.sleep(0.05)
        after = time.perf_counter() - t_stop - 0.4   # minus the stop's tail grace
        app._shutdown.set()
    final = screen.text.strip()
    words = final.lower().split()
    doubled = any(words[i:i + 4] == words[i + 4:i + 8] for i in range(max(0, len(words) - 7)))
    return {"clip": wav.stem, "seconds": round(len(audio) / sr, 1), "wer": wer(ref, final),
            "live_words_before_stop": len(live_text.split()), "after_stop_s": round(after, 2),
            "backspaced": screen.backspaced, "doubled": doubled, "final": final}


def main() -> int:
    cfg = config_mod.load(str(ROOT / "config-linux.yaml"))
    cfg["model"].update(device="cpu", compute_type="int8")
    cfg["ui"].update(tray=False, overlay=False, sounds=False)
    cfg["injection"]["inline_preview"] = False
    cfg["context"]["enabled"] = False
    cfg["update"]["check"] = False
    cfg["history"]["enabled"] = False
    cfg["model"]["unload_after_min"] = 0
    from mywhisper.transcriber import Transcriber
    mcfg = dict(cfg["model"]); mcfg.update(cfg["asr"])
    transcriber = Transcriber(mcfg, backend=cfg["asr"]["backend"], required=True)
    transcriber.transcribe(np.zeros(16000, dtype=np.float32))   # Whisper loaded before the clock starts
    from mywhisper.pipeline.llm import LlmCleanup
    LlmCleanup(cfg["cleanup"]["llm"]).warm(cfg["cleanup"]["level"])   # as the key press does

    ok = True
    for wav in sorted((ROOT / "bench" / "corpus").glob("*.wav")):
        ref = wav.with_suffix(".txt").read_text(encoding="utf-8").strip()
        r = run_clip(wav, ref, cfg, transcriber)
        good = r["wer"] <= 0.15 and not r["doubled"] and r["live_words_before_stop"] > 0
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {r['clip']:18s} {r['seconds']:5.1f}s audio  "
              f"WER {r['wer'] * 100:5.1f}%  live words before stop {r['live_words_before_stop']:3d}  "
              f"done {r['after_stop_s']:.2f}s after stop  backspaced {r['backspaced']}  "
              f"doubled {r['doubled']}")
        print(f"      final: {r['final'][:160]}")
    print("E2E", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
