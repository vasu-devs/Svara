"""Backwards-compatible façade over `mywhisper.asr`.

Recognition moved behind a backend protocol (`asr/`) so an engine can be
swapped and benchmarked without touching the streamer. `Transcriber` remains
the name the app, the setup window and the tests use, and behaves exactly as
before once loaded.

It also absorbs a load failure rather than propagating one, for the same reason
`audio.py` absorbs a missing microphone: this object is constructed while the
app starts, and at login that can happen before the network is up, with a
half-written model cache, or on a machine whose GPU driver is still
initialising. An exception there takes the whole process down - no tray, no
hotkey, no way to find out why - and the user's experience is that Svara
stopped existing after a reboot.

So a failed load leaves a live object with `ready == False` that keeps its
config (everything else in the app reads and mutates `transcriber.cfg`) and
retries in the background. Decoding raises a clear error until it succeeds,
which the worker already catches and logs.
"""

import logging
import threading
import time

from . import asr
from .redact import E_STT_LOAD

log = logging.getLogger(__name__)

RETRY_INTERVAL_S = 20.0


class TranscriberNotReady(RuntimeError):
    """Raised by decode calls while the model has not loaded yet."""


class Transcriber:
    """Loads the configured ASR backend and forwards to it.

    Kept as a thin class rather than an alias so `transcriber.cfg[...] = x`
    keeps working - the app mutates hotwords, language and context on the live
    instance between utterances.
    """

    def __init__(self, mcfg: dict, backend: str | None = None,
                 required: bool = False):
        self.cfg = mcfg
        self._backend_name = backend or mcfg.get("backend") or "faster-whisper"
        self.backend = None
        self.error: Exception | None = None
        self._lock = threading.Lock()
        self._last_try = 0.0
        # `required=True` is for callers that genuinely cannot continue without
        # a model - first-run setup, --test, --bench - where failing loudly is
        # the correct behaviour and there is a human watching.
        self._load(raise_on_failure=required)

    # -- loading --------------------------------------------------------------

    def _load(self, raise_on_failure: bool = False) -> bool:
        with self._lock:
            self._last_try = time.monotonic()
            try:
                self.backend = asr.create(self.cfg, self._backend_name)
                self.error = None
                return True
            except Exception as e:  # noqa: BLE001
                self.backend = None
                self.error = e
                if raise_on_failure:
                    raise
                log.error("%s model failed to load (%s) — Svara stays up and "
                          "retries; dictation is unavailable until it does",
                          E_STT_LOAD, type(e).__name__)
                return False

    @property
    def ready(self) -> bool:
        return self.backend is not None

    def retry(self, min_interval_s: float = RETRY_INTERVAL_S) -> bool:
        """Called from the app's monitor thread. Rate-limited, because loading
        a model is expensive and a machine that is genuinely offline should not
        spend every spare cycle finding that out again."""
        if self.ready:
            return True
        if time.monotonic() - self._last_try < min_interval_s:
            return False
        return self._load()

    # -- forwarding -----------------------------------------------------------

    def _require(self):
        if self.backend is None:
            raise TranscriberNotReady(
                f"{E_STT_LOAD} speech model not loaded"
                + (f" ({type(self.error).__name__})" if self.error else ""))
        return self.backend

    @property
    def model(self):
        return self.backend.model if self.backend else None

    @property
    def device_used(self) -> str:
        return self.backend.device_used if self.backend else "loading"

    @property
    def compute_used(self) -> str:
        return self.backend.compute_used if self.backend else "-"

    @property
    def capabilities(self):
        if self.backend is None:
            # Nothing is known yet; claim multilingual so the language picker
            # is not hidden on a model that would in fact support it.
            from .asr.base import BackendCaps
            return BackendCaps(name="loading")
        return self.backend.capabilities

    def transcribe(self, audio):
        return self._require().transcribe(audio)

    def transcribe_partial(self, audio, prompt: str | None = None):
        return self._require().transcribe_partial(audio, prompt=prompt)

    def transcribe_final_window(self, audio):
        backend = self._require()
        fn = getattr(backend, "transcribe_final_window", None)
        if fn is None:  # a minimal third-party backend — partials suffice
            return backend.transcribe_partial(audio)
        return fn(audio)
