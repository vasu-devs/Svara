"""Microphone capture with an always-on pre-roll ring buffer.

The input stream runs for the whole session. When not recording, the last
``preroll_ms`` of audio is kept in a small ring buffer; when recording starts,
that pre-roll is prepended so the first word is never clipped even if you
start speaking slightly before pressing the hotkey (the whisper-local trick).

Audio only ever lives in RAM, and only ~0.5 s of it outside a recording.
"""

import collections
import logging
import threading
import time

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)


class Recorder:
    def __init__(self, audio_cfg: dict, rec_cfg: dict):
        self.sr = int(audio_cfg["sample_rate"])
        self.block = int(audio_cfg["block_size"])
        self._block_ms = 1000.0 * self.block / self.sr

        preroll_blocks = max(1, int(rec_cfg["preroll_ms"] / self._block_ms) + 1)
        self._ring: collections.deque = collections.deque(maxlen=preroll_blocks)

        self._lock = threading.Lock()
        self._rec: list[np.ndarray] = []
        self._recording = False
        self._started_at = 0.0

        # Adaptive silence detection (for toggle-mode auto-stop).
        self._noise_rms = 1e-4
        self._last_voice = 0.0
        self._speech_ms = 0.0
        self._last_rms = 0.0  # for the overlay level meter

        self._device = audio_cfg["input_device"]
        self._stream = self._make_stream()

    def _make_stream(self) -> sd.InputStream:
        return sd.InputStream(
            samplerate=self.sr,
            channels=1,
            dtype="float32",
            blocksize=self.block,
            device=self._device,
            callback=self._callback,
        )

    # -- stream lifecycle ---------------------------------------------------

    def open(self):
        self._stream.start()
        dev = sd.query_devices(self._stream.device, "input")
        log.info("Microphone: %s @ %d Hz", dev["name"], self.sr)

    def close(self):
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass

    def ensure_alive(self) -> bool:
        """Reopen the stream if it died (headset unplugged, sleep/resume…).

        Always-on resilience: called periodically by the app's monitor thread.
        """
        try:
            if self._stream.active:
                return True
        except Exception:  # noqa: BLE001
            pass
        log.warning("audio stream inactive — reopening…")
        try:
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            # Re-query so a new default device (e.g. headset → laptop mic)
            # is picked up.
            sd._terminate()
            sd._initialize()
            self._stream = self._make_stream()
            self._stream.start()
            dev = sd.query_devices(self._stream.device, "input")
            log.info("audio stream reopened on: %s", dev["name"])
            return True
        except Exception as e:  # noqa: BLE001
            log.error("could not reopen audio stream (%s) — will retry", e)
            return False

    # -- audio callback (keep it light!) -------------------------------------

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.debug("audio status: %s", status)
        mono = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(mono * mono))) if len(mono) else 0.0
        self._last_rms = rms
        with self._lock:
            if self._recording:
                self._rec.append(mono)
                if rms > self._voice_threshold():
                    self._last_voice = time.monotonic()
                    self._speech_ms += self._block_ms
            else:
                self._ring.append(mono)
                # Slowly track the ambient noise floor while idle.
                self._noise_rms = max(1e-5, 0.95 * self._noise_rms + 0.05 * rms)

    def _voice_threshold(self) -> float:
        return max(self._noise_rms * 3.5, 0.005)

    # -- recording control ----------------------------------------------------

    def start(self):
        with self._lock:
            if self._recording:
                return
            self._rec = list(self._ring)  # include the pre-roll
            self._recording = True
            now = time.monotonic()
            self._started_at = now
            self._last_voice = now
            self._speech_ms = 0.0

    def snapshot(self) -> np.ndarray | None:
        """Copy of the audio captured so far, without stopping (for streaming)."""
        with self._lock:
            if not self._recording or not self._rec:
                return None
            blocks = list(self._rec)
        return np.concatenate(blocks)

    def stop(self, keep_tail: bool = False) -> np.ndarray | None:
        """End the recording and return its audio.

        keep_tail=True (cancelled taps): feed the tail back into the pre-roll
        ring so a double-tap's 2nd recording loses no audio continuity.
        keep_tail=False (real stops): CLEAR the ring so this session's speech
        can never leak into the start of the next one.
        """
        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            blocks, self._rec = self._rec, []
            self._ring.clear()
            if keep_tail:
                for b in blocks[-self._ring.maxlen:]:
                    self._ring.append(b)
        if not blocks:
            return None
        audio = np.concatenate(blocks)
        if len(audio) < int(0.2 * self.sr):  # < 200 ms — nothing useful
            return None
        return audio

    # -- state queries (used by the monitor thread) ---------------------------

    @property
    def recording(self) -> bool:
        return self._recording

    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._recording else 0.0

    def silence_ms(self) -> float:
        """Milliseconds since the last block that looked like speech."""
        if not self._recording:
            return 0.0
        return 1000.0 * (time.monotonic() - self._last_voice)

    def speech_ms(self) -> float:
        return self._speech_ms

    @property
    def level(self) -> float:
        """Current mic level, normalized 0..1 (for the overlay meter)."""
        return min(1.0, self._last_rms / 0.08)
