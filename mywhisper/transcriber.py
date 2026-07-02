"""faster-whisper wrapper: load, warm up, transcribe.

- int8_float16 on CUDA: ~1.5 GB VRAM for large-v3-turbo, <0.1% WER cost.
- Warmup at boot runs one dummy transcribe so the first real dictation is instant.
- Falls back to CPU (int8) automatically if CUDA/cuDNN is unavailable.
"""

import logging
import threading
import time

import numpy as np

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, mcfg: dict):
        self.cfg = mcfg
        self.device_used = "?"
        self.compute_used = "?"
        self.model = None
        self._lock = threading.Lock()  # serialize streaming partials vs finals
        self._load()

    def _load(self):
        from faster_whisper import WhisperModel  # deferred: after cuda_setup.setup()

        name = self.cfg["name"]
        attempts = [(self.cfg["device"], self.cfg["compute_type"])]
        if self.cfg["device"] != "cpu":
            attempts.append(("cpu", "int8"))  # graceful fallback

        last_err = None
        for device, compute in attempts:
            try:
                t0 = time.perf_counter()
                log.info("Loading model '%s' on %s (%s)…", name, device, compute)
                model = WhisperModel(
                    name,
                    device=device,
                    compute_type=compute,
                    download_root=self.cfg["download_root"],
                )
                load_s = time.perf_counter() - t0

                # Warmup: run a dummy transcribe so CUDA kernels/cuDNN plans are
                # compiled now, not on your first real dictation.
                t0 = time.perf_counter()
                segs, _ = model.transcribe(
                    np.zeros(int(0.5 * 16000), dtype=np.float32),
                    beam_size=1,
                    language=self.cfg["language"] or "en",
                    vad_filter=False,
                )
                list(segs)  # generator — must be consumed to actually run
                warm_s = time.perf_counter() - t0

                self.model = model
                self.device_used = device
                self.compute_used = compute
                log.info(
                    "Model ready on %s (%s) — load %.1fs, warmup %.1fs",
                    device, compute, load_s, warm_s,
                )
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("Could not initialize on %s (%s): %s", device, compute, e)

        raise RuntimeError(f"Failed to load Whisper model '{name}': {last_err}")

    def transcribe(self, audio: np.ndarray) -> list[tuple[str, float, float]]:
        """Full-quality pass. Returns [(text, start_s, end_s), …] per segment —
        the timings enable loudness-aware (CAPS) formatting downstream."""
        with self._lock:
            segments, _info = self.model.transcribe(
                audio,
                beam_size=int(self.cfg["beam_size"]),
                language=self.cfg["language"],
                initial_prompt=self.cfg["initial_prompt"],
                vad_filter=True,                  # Silero VAD (bundled) trims silence
                condition_on_previous_text=False, # avoids hallucination loops
            )
            return [(s.text.strip(), float(s.start), float(s.end))
                    for s in segments if s.text.strip()]

    def transcribe_partial(self, audio: np.ndarray) -> list[tuple[str, float, float]]:
        """Fast greedy pass over an in-progress buffer (streaming preview/live).

        Returns [(text, start_s, end_s), …] — timings let the streamer trim
        fully-committed audio (passes stay fast forever) and measure loudness.
        vad_filter=True is essential: without it, greedy decoding over buffers
        with silence hallucinates repeated words ("hello hello hello").
        """
        with self._lock:
            segments, _info = self.model.transcribe(
                audio,
                beam_size=1,
                language=self.cfg["language"] or "en",
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return [(s.text.strip(), float(s.start), float(s.end))
                    for s in segments if s.text.strip()]
