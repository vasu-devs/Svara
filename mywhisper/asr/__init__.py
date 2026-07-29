"""Speech-recognition backends.

`asr.backend` is the config key. Only `faster-whisper` ships today; the point of
the seam is that adding a second one is a module and a registry entry rather
than a rewrite of the streamer.
"""

import logging

from .base import AsrBackend, BackendCaps, Segment

log = logging.getLogger(__name__)

__all__ = ["AsrBackend", "BackendCaps", "Segment", "BACKENDS", "create"]

BACKENDS = ("faster-whisper",)


def create(mcfg: dict, backend: str = "faster-whisper") -> AsrBackend:
    name = str(backend or "faster-whisper").lower()
    if name not in BACKENDS:
        log.warning("unknown asr.backend %r — using faster-whisper "
                    "(available: %s)", backend, ", ".join(BACKENDS))
        name = "faster-whisper"
    from .faster_whisper import FasterWhisperBackend

    return FasterWhisperBackend(mcfg)
