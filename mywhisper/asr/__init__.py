"""Speech-recognition backends.

`model.backend` is the config key. Three engines:

- **faster-whisper** — the default: quality, hotwords, 90+ languages.
- **moonshine** — English-only ONNX engine whose cost scales with audio length
  instead of a fixed 30 s pad; ~5× faster on the short windows live streaming
  decodes every 180 ms. No hotwords, chunk-level timings.
- **hybrid** — Moonshine for the partials, faster-whisper for the final pass:
  streaming latency from one, final quality from the other. The recommended
  way to run Moonshine; degrades to pure faster-whisper for non-English or
  when Moonshine can't load.
"""

import logging

from .base import AsrBackend, BackendCaps, Segment

log = logging.getLogger(__name__)

__all__ = ["AsrBackend", "BackendCaps", "Segment", "BACKENDS", "create"]

BACKENDS = ("faster-whisper", "moonshine", "hybrid")


def create(mcfg: dict, backend: str = "faster-whisper") -> AsrBackend:
    name = str(backend or "faster-whisper").lower()
    if name not in BACKENDS:
        log.warning("unknown model.backend %r — using faster-whisper "
                    "(available: %s)", backend, ", ".join(BACKENDS))
        name = "faster-whisper"
    if name == "moonshine" and (mcfg.get("language") or "en") != "en":
        # English-only engine, and unlike hybrid it has no second engine to
        # fall back on per-call — refuse up front rather than mid-dictation.
        log.warning("model.backend=moonshine is English-only but language=%r "
                    "— using faster-whisper", mcfg.get("language"))
        name = "faster-whisper"
    if name == "hybrid":
        from .hybrid import HybridBackend
        return HybridBackend(mcfg)
    if name == "moonshine":
        from .moonshine import MoonshineBackend
        try:
            return MoonshineBackend(mcfg)
        except Exception as e:  # noqa: BLE001 — missing onnxruntime, blocked DL
            log.warning("moonshine unavailable (%s: %s) — using faster-whisper",
                        type(e).__name__, e)
    from .faster_whisper import FasterWhisperBackend

    return FasterWhisperBackend(mcfg)
