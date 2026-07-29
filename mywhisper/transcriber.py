"""Backwards-compatible façade over `mywhisper.asr`.

Recognition moved behind a backend protocol (`asr/`) so an engine can be
swapped and benchmarked without touching the streamer. `Transcriber` remains the
name the app, the setup window and the tests use, and behaves exactly as before.
"""

import logging

from . import asr

log = logging.getLogger(__name__)


class Transcriber:
    """Loads the configured ASR backend and forwards to it.

    Kept as a thin class rather than an alias so `transcriber.cfg[...] = x`
    keeps working — the app mutates hotwords, language and context on the live
    instance between utterances.
    """

    def __init__(self, mcfg: dict, backend: str | None = None):
        self.cfg = mcfg
        self.backend = asr.create(mcfg, backend or mcfg.get("backend")
                                  or "faster-whisper")

    # The backend reads `self.cfg` by reference, so live mutations (hotwords,
    # language, context_hotwords) take effect on the next call with no reload.
    @property
    def model(self):
        return self.backend.model

    @property
    def device_used(self) -> str:
        return self.backend.device_used

    @property
    def compute_used(self) -> str:
        return self.backend.compute_used

    @property
    def capabilities(self):
        return self.backend.capabilities

    def transcribe(self, audio):
        return self.backend.transcribe(audio)

    def transcribe_partial(self, audio, prompt: str | None = None):
        return self.backend.transcribe_partial(audio, prompt=prompt)
