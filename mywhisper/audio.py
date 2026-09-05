"""Microphone capture with an always-on pre-roll ring buffer.

The input stream runs for the whole session. When not recording, the last
``preroll_ms`` of audio is kept in a small ring buffer; when recording starts,
that pre-roll is prepended so the first word is never clipped even if you
start speaking slightly before pressing the hotkey (the whisper-local trick).

Audio only ever lives in RAM, and only ~0.5 s of it outside a recording.
"""

import collections
import logging
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from .redact import E_AUDIO_DEV

log = logging.getLogger(__name__)


class Recorder:
    def __init__(self, audio_cfg: dict, rec_cfg: dict,
                 on_device_change=None):
        self.sr = int(audio_cfg["sample_rate"])
        self.block = int(audio_cfg["block_size"])
        self._block_ms = 1000.0 * self.block / self.sr
        # Whisper mode: software gain so near-silent speech still clears the
        # VAD and decodes well. Applied before anything sees the audio.
        self.gain = float(audio_cfg.get("gain", 1.0) or 1.0)

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
        self._policy = str(audio_cfg.get("device_policy", "preferred"))
        self._on_device_change = on_device_change
        self._last_device_scan = 0.0
        # A failure here must NOT kill the app.
        #
        # At login the HKCU Run entry fires early — routinely before the
        # Windows Audio service has finished enumerating endpoints, and later
        # still for a USB or Bluetooth headset. sd.InputStream() then raises,
        # and an unguarded construction takes the whole process down: no tray,
        # no hotkey, dictation silently gone until the user launches it by
        # hand. Which looks exactly like "it stopped working after I rebooted".
        #
        # The monitor thread already calls ensure_alive() every 3 seconds and
        # already handles a missing stream, so starting without one is
        # recoverable by machinery that exists. Starting not at all is not.
        self._stream = None
        try:
            self._stream = self._make_stream()
        except Exception:  # noqa: BLE001 — PortAudioError and friends
            log.warning("%s no microphone at startup — the app stays up and "
                        "retries every few seconds", E_AUDIO_DEV, exc_info=True)

        # Crash-safe spill: while recording, raw audio is streamed to disk on
        # a writer thread (never in the audio callback), so a crash/power-loss
        # mid-dictation can be recovered at next launch. ~64 KB/s.
        self._spill_path = None
        self._spill_q: queue.SimpleQueue = queue.SimpleQueue()
        self._closed = False
        self._spill_thread = threading.Thread(target=self._spill_writer, daemon=True,
                                              name="audio-spill")
        self._spill_thread.start()

    # -- crash-safe spill -----------------------------------------------------

    def set_spill_path(self, path):
        self._spill_path = path

    def discard_recovery(self):
        """The dictation was fully processed — its recovery file is obsolete."""
        self._spill_q.put(("discard", None))

    def _spill_writer(self):
        fh = None
        while True:
            op, payload = self._spill_q.get()
            if op == "quit":
                if fh:
                    fh.close()
                return
            try:
                if op == "open" and self._spill_path:
                    if fh:
                        fh.close()
                    fh = open(self._spill_path, "wb")
                    for b in payload or []:
                        fh.write(b.tobytes())
                elif op == "data" and fh:
                    fh.write(payload.tobytes())
                elif op == "close" and fh:
                    fh.flush()
                    fh.close()
                    fh = None
                elif op == "discard":
                    if fh:
                        fh.close()
                        fh = None
                    if self._spill_path:
                        try:
                            self._spill_path.unlink(missing_ok=True)
                        except OSError:
                            pass
            except OSError:
                log.debug("audio spill failed (op=%s)", op, exc_info=True)
                fh = None

    def _make_stream(self, device=...) -> sd.InputStream:
        return sd.InputStream(
            samplerate=self.sr,
            channels=1,
            dtype="float32",
            blocksize=self.block,
            device=self._device if device is ... else device,
            callback=self._callback,
        )

    # -- stream lifecycle ---------------------------------------------------

    def open(self) -> bool:
        """Start capturing. Returns whether a microphone is live.

        Same reasoning as the constructor: at login this can fail because the
        audio stack is not up yet, and that must not stop the hotkey being
        armed. `ensure_alive()` picks it up within a few seconds, and the user
        gets a toast naming the device when it does.
        """
        if self._closed:
            return False
        try:
            if self._stream is None:
                self._stream = self._make_stream()
            self._stream.start()
            dev = sd.query_devices(self._stream.device, "input")
            log.info("Microphone: %s @ %d Hz", dev["name"], self.sr)
            return True
        except Exception:  # noqa: BLE001
            log.warning("%s microphone not available yet — retrying in the "
                        "background", E_AUDIO_DEV, exc_info=True)
            self._close_stream()
            return False

    def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            stream.close()
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._close_stream()
        with self._lock:
            self._recording = False
            self._spill_q.put(("quit", None))
        self._spill_thread.join(timeout=2)

    @property
    def available(self) -> bool:
        try:
            return not self._closed and self._stream is not None and bool(self._stream.active)
        except Exception:
            return False

    def _candidates(self) -> list:
        """Devices to try, in policy order (see `audio_policy`)."""
        from .audio_policy import rank_devices

        try:
            devices = list(sd.query_devices())
        except Exception:  # noqa: BLE001
            return [self._device, None]
        return rank_devices(devices, self._policy, preferred=self._device)

    def current_device_name(self) -> str:
        try:
            return sd.query_devices(self._stream.device, "input")["name"]
        except Exception:  # noqa: BLE001
            return ""

    def reevaluate_device(self, min_interval_s: float = 5.0) -> bool:
        """Under `external_first`, move to a better mic when one appears.

        Called from the monitor thread while idle — never mid-recording, where
        swapping the input stream would truncate the utterance being spoken.
        """
        if self._policy != "external_first" or self._recording:
            return False
        now = time.monotonic()
        if now - self._last_device_scan < min_interval_s:
            return False
        self._last_device_scan = now
        from .audio_policy import should_switch

        try:
            devices = list(sd.query_devices())
        except Exception:  # noqa: BLE001
            return False
        current = self.current_device_name()
        if not should_switch(self._policy, current, devices):
            return False
        log.info("device policy: a preferred microphone is available "
                 "(currently on '%s') — switching", current)
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass
        return self.ensure_alive()

    def ensure_alive(self) -> bool:
        """Reopen the stream if it died (headset unplugged, sleep/resume…).

        Always-on resilience: called periodically by the app's monitor thread.
        If the configured device is gone, falls back to the system default,
        then to any working input device — a dead mic must never mean
        silently dead dictation.
        """
        if self._closed:
            return False
        try:
            if self._stream is not None and self._stream.active:
                self._retry_logged = False
                return True
        except Exception:  # noqa: BLE001
            pass
        # This runs every 3 seconds. On a machine with no microphone at all
        # that would be a warning every 3 seconds forever, so say it once and
        # drop to debug until a device actually comes back.
        if not getattr(self, "_retry_logged", False):
            self._retry_logged = True
            log.warning("%s audio stream unavailable — reopening…", E_AUDIO_DEV)
        else:
            log.debug("audio stream still unavailable — retrying")
        self._close_stream()
        try:
            # Re-query so a new default device (e.g. headset → laptop mic)
            # is picked up.
            sd._terminate()
            sd._initialize()
        except Exception:  # noqa: BLE001
            pass
        candidates = self._candidates()
        for cand in candidates:
            try:
                self._stream = self._make_stream(device=cand)
                self._stream.start()
                dev = sd.query_devices(self._stream.device, "input")
                if cand != self._device:
                    log.warning("mic fallback: now using '%s'", dev["name"])
                    if self._on_device_change:
                        try:
                            self._on_device_change(dev["name"])
                        except Exception:  # noqa: BLE001
                            pass
                else:
                    log.info("audio stream reopened on: %s", dev["name"])
                return True
            except Exception as e:  # noqa: BLE001
                log.debug("mic candidate %r failed: %s", cand, e)
                self._close_stream()
        # Leaving a half-constructed stream here would make the next call
        # think one exists and try to .close() it forever.
        self._stream = None
        # Every-3-seconds error logging fills the file on any machine that
        # simply has no microphone. The first one already said it.
        log.debug("no working microphone found — will keep retrying")
        return False

    # -- audio callback (keep it light!) -------------------------------------

    def _callback(self, indata, frames, time_info, status):
        if status:
            log.debug("audio status: %s", status)
        mono = indata[:, 0].copy()
        if self.gain != 1.0:  # whisper mode — boost before anything sees it
            np.multiply(mono, self.gain, out=mono)
            np.clip(mono, -1.0, 1.0, out=mono)
        rms = float(np.sqrt(np.mean(mono * mono))) if len(mono) else 0.0
        self._last_rms = rms
        with self._lock:
            if self._recording:
                self._rec.append(mono)
                self._spill_q.put(("data", mono))
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
            self._spill_q.put(("open", list(self._rec)))
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
            self._spill_q.put(("close", None))
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
