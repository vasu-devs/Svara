"""Hybrid engine: Moonshine for the streaming partials, faster-whisper for the
final pass — each engine doing the one thing it is best at.

Streaming partials run every ~180 ms and their cost IS the perceived latency;
Moonshine decodes a 1 s window ~5× faster than Whisper on this machine's CPU
(see `asr/moonshine.py` header). The final pass runs once per utterance where
quality, hotword boosting, timings and multilingual support matter — Whisper's
home turf.

The seam that makes this safe is `streaming.align_remainder`: the stream/tail
boundary is matched by *content*, not by word count, and was hardened for
exactly the case where two decoders tokenise differently ("get hub" vs
"GitHub"). A hybrid was viable the day that landed.

Dynamic degradation: Moonshine is English-only, and the language can change at
runtime (tray ▸ Language). Rather than refusing to start, every partial checks
the live config — non-English routes partials to faster-whisper too, and the
app behaves exactly as before, no restart, no ceremony.
"""

import logging

import numpy as np

from .base import AsrBackend, BackendCaps, Segment

log = logging.getLogger(__name__)


class HybridBackend(AsrBackend):
    def __init__(self, mcfg: dict):
        from .faster_whisper import FasterWhisperBackend
        from .moonshine import MoonshineBackend

        import threading

        self.cfg = mcfg
        # Moonshine first, synchronously: it is what the first live words
        # need. Whisper (the big one, possibly on the GPU) loads behind it;
        # the first final-quality decode waits for it. If Moonshine fails
        # (no onnxruntime, blocked download) everything routes to Whisper.
        self._moon = None
        try:
            self._moon = MoonshineBackend(mcfg)
        except Exception as e:  # noqa: BLE001
            log.warning("hybrid: moonshine unavailable (%s: %s) — running "
                        "pure faster-whisper", type(e).__name__, e)
        self._fw_backend = None
        self._fw_error: Exception | None = None

        def load():
            try:
                self._fw_backend = FasterWhisperBackend(mcfg)
            except Exception as e:  # noqa: BLE001
                self._fw_error = e
                log.error("hybrid: faster-whisper failed to load (%s)", type(e).__name__)

        self._fw_thread = threading.Thread(target=load, daemon=True, name="whisper-load")
        self._fw_thread.start()
        if self._moon is None:
            self._fw_thread.join()
            if self._fw_backend is None:
                raise self._fw_error or RuntimeError("faster-whisper failed to load")

    @property
    def _fw(self):
        """The Whisper backend, waiting for its background load."""
        self._fw_thread.join()
        if self._fw_backend is None:
            raise self._fw_error or RuntimeError("faster-whisper failed to load")
        return self._fw_backend

    @property
    def whisper_ready(self) -> bool:
        return self._fw_backend is not None

    # -- surface parity with the other backends -------------------------------

    @property
    def device_used(self) -> str:
        return self._fw.device_used if self.whisper_ready else "loading"

    @device_used.setter
    def device_used(self, v):  # the protocol declares it as an attribute
        self._fw.device_used = v

    @property
    def compute_used(self) -> str:
        base = self._fw.compute_used if self.whisper_ready else "-"
        return f"{base}+moonshine" if self._moon else base

    @compute_used.setter
    def compute_used(self, v):
        self._fw.compute_used = v

    @property
    def model(self):
        return self._fw.model

    @property
    def capabilities(self) -> BackendCaps:
        fw = self._fw.capabilities
        return BackendCaps(name="hybrid" if self._moon else fw.name,
                           streaming_native=False,
                           multilingual=fw.multilingual,
                           word_timings=fw.word_timings,
                           translate=fw.translate, hotwords=fw.hotwords)

    def _english(self) -> bool:
        # cfg is mutated live by the app when the user switches language.
        return (self.cfg.get("language") or "en") == "en" \
            and self.cfg.get("task", "transcribe") == "transcribe"

    # -- decoding -------------------------------------------------------------

    def transcribe(self, audio: np.ndarray,
                   prompt: str | None = None) -> list[Segment]:
        if prompt:
            return self._fw.transcribe(audio, prompt=prompt)
        return self._fw.transcribe(audio)

    def transcribe_partial(self, audio: np.ndarray,
                           prompt: str | None = None) -> list[Segment]:
        # On a GPU, Whisper decodes a live window in ~0.25 s whatever its
        # length and hears accents far better than Moonshine; Moonshine only
        # covers the seconds before Whisper has finished loading. On CPU
        # Whisper partials cost ~0.8 s, so Moonshine keeps them.
        whisper_live = (self.whisper_ready
                        and self._fw_backend.device_used == "cuda")
        if self._moon is not None and self._english() and not whisper_live:
            return self._moon.transcribe_partial(audio, prompt=prompt)
        return self._fw.transcribe_partial(audio, prompt=prompt)

    def transcribe_final_window(self, audio: np.ndarray) -> list[Segment]:
        """The live-mode finaliser. Full Whisper quality (beam, hotwords,
        timings) over the trimmed window; `align_remainder` absorbs any
        tokenisation drift against the Moonshine-typed prefix."""
        return self._fw.transcribe_partial(audio)
