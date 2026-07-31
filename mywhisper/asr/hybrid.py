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

        self.cfg = mcfg
        # Whisper first: it is the engine dictation cannot run without. If
        # Moonshine then fails to load (no onnxruntime, blocked download),
        # the property degrades to pure faster-whisper with one warning.
        self._fw = FasterWhisperBackend(mcfg)
        self._moon = None
        try:
            self._moon = MoonshineBackend(mcfg)
        except Exception as e:  # noqa: BLE001
            log.warning("hybrid: moonshine unavailable (%s: %s) — running "
                        "pure faster-whisper", type(e).__name__, e)

    # -- surface parity with the other backends -------------------------------

    @property
    def device_used(self) -> str:
        return self._fw.device_used

    @device_used.setter
    def device_used(self, v):  # the protocol declares it as an attribute
        self._fw.device_used = v

    @property
    def compute_used(self) -> str:
        base = self._fw.compute_used
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

    def transcribe(self, audio: np.ndarray) -> list[Segment]:
        return self._fw.transcribe(audio)

    def transcribe_partial(self, audio: np.ndarray,
                           prompt: str | None = None) -> list[Segment]:
        if self._moon is not None and self._english():
            return self._moon.transcribe_partial(audio, prompt=prompt)
        return self._fw.transcribe_partial(audio, prompt=prompt)

    def transcribe_final_window(self, audio: np.ndarray) -> list[Segment]:
        """The live-mode finaliser. Full Whisper quality (beam, hotwords,
        timings) over the trimmed window; `align_remainder` absorbs any
        tokenisation drift against the Moonshine-typed prefix."""
        return self._fw.transcribe_partial(audio)
