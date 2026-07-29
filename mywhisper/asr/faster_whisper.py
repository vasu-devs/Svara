"""faster-whisper / CTranslate2 backend — Svara's default engine.

- int8 on CPU, int8_float16 on CUDA (~1.5 GB VRAM for large-v3-turbo).
- Warmup at boot runs one dummy transcribe so CUDA/cuDNN kernels are compiled
  before the first real dictation, not during it.
- Falls back to CPU automatically if CUDA/cuDNN is unavailable.

Two optional accelerations, both off unless measured to help (`--bench`), both
degrading to the plain path on any error rather than taking dictation down with
them:

**Batched inference.** faster-whisper ≥1.1 ships `BatchedInferencePipeline`,
which decodes VAD-split chunks in parallel. It is a real win on the final pass
of a long utterance and does nothing for a one-second streaming window, so it is
applied only to the final pass. Its `transcribe()` does not accept every
argument the sequential one does, and which ones vary by version — so the first
call that raises disables it permanently for the session and says why once.

**Rolling context prompt.** `condition_on_previous_text=False` is correct here
(it avoids the repetition loops Whisper falls into on silence), but it also
throws away the fact that we already know what the speaker just said. Feeding
the last few committed words back as `initial_prompt` gives the decoder that
context for the cost of a few tokens. Default off: it can also *induce*
repetition, so it needs a number before it earns being on.
"""

import logging
import threading
import time

import numpy as np

from ..redact import E_STT_LOAD
from .base import AsrBackend, BackendCaps, Segment

log = logging.getLogger(__name__)


class FasterWhisperBackend(AsrBackend):
    def __init__(self, mcfg: dict):
        self.cfg = mcfg
        self.device_used = "?"
        self.compute_used = "?"
        self.model = None
        self._batched = None          # BatchedInferencePipeline, or None
        self._batched_failed = False
        self._lock = threading.Lock()  # serialize streaming partials vs finals
        self._load()

    # -- capabilities ---------------------------------------------------------

    @property
    def capabilities(self) -> BackendCaps:
        multilingual = True
        try:
            multilingual = bool(self.model.model.is_multilingual)
        except Exception:  # noqa: BLE001
            pass
        return BackendCaps(name="faster-whisper", streaming_native=False,
                           multilingual=multilingual, word_timings=True,
                           translate=True, hotwords=True)

    # -- loading --------------------------------------------------------------

    def _hotwords(self) -> str | None:
        """Personal dictionary + per-utterance context (window-title nouns),
        merged. Context is set by the app when a recording starts."""
        parts = [self.cfg.get("hotwords"), self.cfg.get("context_hotwords")]
        merged = ", ".join(p for p in parts if p)
        return merged or None

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
                    name, device=device, compute_type=compute,
                    download_root=self.cfg["download_root"])
                load_s = time.perf_counter() - t0

                # Warmup: compile CUDA kernels / cuDNN plans now, not on the
                # user's first real dictation.
                t0 = time.perf_counter()
                segs, _ = model.transcribe(
                    np.zeros(int(0.5 * 16000), dtype=np.float32),
                    beam_size=1, language=self.cfg["language"] or "en",
                    vad_filter=False)
                list(segs)  # generator — must be consumed to actually run
                warm_s = time.perf_counter() - t0

                self.model = model
                self.device_used = device
                self.compute_used = compute
                self._setup_batched()
                log.info("Model ready on %s (%s) — load %.1fs, warmup %.1fs",
                         device, compute, load_s, warm_s)
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("Could not initialize on %s (%s): %s",
                            device, compute, e)

        raise RuntimeError(f"{E_STT_LOAD} Failed to load Whisper model "
                           f"{name!r}: {last_err}")

    def _setup_batched(self):
        mode = str(self.cfg.get("batched", "auto")).lower()
        if mode in ("false", "off", "no"):
            return
        try:
            from faster_whisper import BatchedInferencePipeline
            self._batched = BatchedInferencePipeline(model=self.model)
            log.info("batched inference available (batch_size=%d) for final passes",
                     int(self.cfg.get("batch_size", 8)))
        except Exception:  # noqa: BLE001 — older faster-whisper, or no support
            self._batched = None
            log.debug("batched inference unavailable on this faster-whisper",
                      exc_info=True)

    # -- decoding -------------------------------------------------------------

    def _final_kwargs(self) -> dict:
        return {
            "beam_size": int(self.cfg["beam_size"]),
            "language": self.cfg["language"],   # None → Whisper auto-detects
            "task": self.cfg.get("task", "transcribe"),
            "initial_prompt": self.cfg["initial_prompt"],
            "hotwords": self._hotwords(),       # dictionary + app context boost
            "vad_filter": True,                 # Silero VAD (bundled)
            "condition_on_previous_text": False,  # avoids hallucination loops
        }

    def transcribe(self, audio: np.ndarray) -> list[Segment]:
        """Full-quality pass. Timings enable loudness-aware (CAPS) formatting
        and let the streamer trim committed audio."""
        with self._lock:
            kwargs = self._final_kwargs()
            if self._batched is not None and not self._batched_failed:
                try:
                    segments, _info = self._batched.transcribe(
                        audio, batch_size=int(self.cfg.get("batch_size", 8)),
                        **kwargs)
                    return _collect(segments)
                except Exception as e:  # noqa: BLE001
                    # Argument support varies across faster-whisper versions.
                    # One failure is enough — fall back for the rest of the
                    # session rather than paying the exception per utterance.
                    self._batched_failed = True
                    log.warning("batched inference rejected our arguments (%s) "
                                "— using the sequential decoder from here on",
                                type(e).__name__)
            segments, _info = self.model.transcribe(audio, **kwargs)
            return _collect(segments)

    def transcribe_partial(self, audio: np.ndarray,
                           prompt: str | None = None) -> list[Segment]:
        """Beam-searched pass over an in-progress buffer (live/preview).

        `vad_filter=True` is essential: without it, decoding over buffers that
        contain silence repeats words ("hello hello"). A single temperature is
        used because the default fallback ladder silently re-decodes an
        ambiguous window up to 5×, a latency spike a live pass cannot afford —
        the final pass keeps the fallback.
        """
        with self._lock:
            # Auto-detect is unreliable on sub-second buffers, so fall back to
            # a pinned stream language when none is set.
            stream_lang = (self.cfg["language"]
                           or self.cfg.get("stream_language", "en"))
            segments, _info = self.model.transcribe(
                audio,
                beam_size=int(self.cfg.get("partial_beam_size", 3)),
                language=stream_lang,
                task=self.cfg.get("task", "transcribe"),
                initial_prompt=prompt or self.cfg.get("initial_prompt"),
                hotwords=self._hotwords(),
                vad_filter=True,
                condition_on_previous_text=False,
                temperature=0.0,
            )
            return _collect(segments)


def _collect(segments) -> list[Segment]:
    return [Segment(s.text.strip(), float(s.start), float(s.end))
            for s in segments if s.text.strip()]
