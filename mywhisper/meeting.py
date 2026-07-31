"""Meeting mode — local meeting notes from BOTH sides of the call.

Cloud dictation tools cannot do this without shipping your calls to their
servers; Svara does it because everything already runs here. Two capture
streams — your microphone ("You") and the system's loopback audio ("Them",
whatever Zoom/Meet/Teams is playing) — are chunked at pauses, transcribed with
the full-quality engine, and appended live to a Markdown file. When the
meeting ends, the local LLM (if one is running) writes a summary at the top,
and the file opens.

Speaker separation without diarization: the two physical streams ARE the two
speakers. No model guesses who spoke — the audio path already knows.

Privacy posture, deliberately:
- Off until the user flips the tray toggle, and loudly toasted on start.
- Notes go to a Markdown file in the user's Documents — not history.db, so
  meeting content never shows up in dictation history or paste-last.
- Log lines carry durations and counts, never transcript text (redact rules).
- Capture is local WASAPI loopback: nothing about the call leaves the machine.
"""

import logging
import os
import queue
import threading
import time

import numpy as np

from .redact import shape

log = logging.getLogger(__name__)

SR = 16000
BLOCK = 1600                 # 100 ms per capture read
SUMMARY_PROMPT = (
    "You are a meeting-notes assistant. From the transcript, write:\n"
    "1. A 2-4 sentence summary.\n"
    "2. Key points as short bullets.\n"
    "3. Action items as '- [ ] owner: task' bullets (only if any were said).\n"
    "'You' is the note-taker speaking; 'Them' is everyone else on the call.\n"
    "Use only what the transcript says — never invent names, dates or "
    "decisions. Output plain Markdown, no preamble."
)


class Chunker:
    """Silence-gated segmenter — pure logic, no audio APIs, unit-testable.

    Feed 100 ms blocks; get back closed utterance chunks. Mirrors the
    recorder's adaptive noise floor so a noisy room raises the bar instead of
    producing chunks of hiss. A chunk closes after `silence_ms` of quiet or at
    `max_chunk_s` (mid-speech — long monologues must not wait to appear)."""

    def __init__(self, sr: int = SR, silence_ms: float = 700,
                 max_chunk_s: float = 15.0, min_speech_s: float = 0.4,
                 preroll_blocks: int = 3):
        self.sr = sr
        self.silence_s = silence_ms / 1000.0
        self.max_chunk_s = max_chunk_s
        self.min_speech_s = min_speech_s
        self._noise = 1e-4
        self._pre: list[np.ndarray] = []
        self._preroll_blocks = preroll_blocks
        self._buf: list[np.ndarray] = []
        self._speech_blocks = 0
        self._in_speech = False
        self._started = 0.0
        self._last_voice = 0.0

    def _threshold(self) -> float:
        return max(self._noise * 3.5, 0.005)

    # NOTE on constant background noise (fan, hiss): it can read as "speech"
    # here, because raising the floor while in-speech would eventually gate
    # out a real monologue — the worse failure. The defence is one layer
    # down: chunks are ceiling-bounded (max_chunk_s), decode-time Silero VAD
    # finds no speech in hiss, and empty transcriptions are dropped. Cost is
    # bounded CPU, not garbage notes.

    def feed(self, block: np.ndarray, now: float) -> list[tuple[float, np.ndarray]]:
        """→ [(chunk_start_time, audio)] for chunks that just closed."""
        rms = float(np.sqrt(np.mean(block * block))) if len(block) else 0.0
        out: list[tuple[float, np.ndarray]] = []
        if not self._in_speech:
            if rms > self._threshold():
                self._in_speech = True
                self._started = now - len(self._pre) * len(block) / self.sr
                self._buf = list(self._pre)
                self._buf.append(block)
                self._speech_blocks = 1
                self._last_voice = now
            else:
                self._noise = max(1e-5, 0.95 * self._noise + 0.05 * rms)
                self._pre.append(block)
                if len(self._pre) > self._preroll_blocks:
                    self._pre.pop(0)
            return out

        self._buf.append(block)
        if rms > self._threshold():
            self._last_voice = now
            self._speech_blocks += 1
        dur = now - self._started
        if now - self._last_voice >= self.silence_s or dur >= self.max_chunk_s:
            out.extend(self._close())
        return out

    def _close(self) -> list[tuple[float, np.ndarray]]:
        buf, self._buf = self._buf, []
        self._pre = []
        self._in_speech = False
        speech_s = self._speech_blocks * (len(buf[0]) / self.sr if buf else 0.1)
        self._speech_blocks = 0
        if not buf or speech_s < self.min_speech_s:
            return []   # a door slam, not an utterance
        return [(self._started, np.concatenate(buf))]

    def flush(self, now: float) -> list[tuple[float, np.ndarray]]:  # noqa: ARG002
        """Meeting ended mid-sentence — emit whatever is open."""
        del now  # kept for signature symmetry with feed()
        return self._close() if self._in_speech else []


class MeetingSession:
    """One meeting: capture → chunk → transcribe → live Markdown → summary."""

    def __init__(self, get_transcriber, llm, mcfg: dict, notify=None,
                 on_entry=None):
        self.get_transcriber = get_transcriber
        self.llm = llm
        self.cfg = mcfg or {}
        self.notify = notify or (lambda *_: None)
        self.on_entry = on_entry or (lambda *_: None)
        self.entries: list[tuple[float, str, str]] = []  # (t_rel, speaker, text)
        self.path = None
        self._stop = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._file_lock = threading.Lock()
        self._t0 = 0.0
        self._started_wall = 0.0

    # -- lifecycle ------------------------------------------------------------

    @property
    def active(self) -> bool:
        return bool(self._threads) and not self._stop.is_set()

    def start(self):
        from .paths import meetings_dir
        self._t0 = time.monotonic()
        self._started_wall = time.time()
        stamp = time.strftime("%Y-%m-%d %H.%M", time.localtime(self._started_wall))
        d = meetings_dir()
        self.path = d / f"{stamp} Meeting.md"
        n = 2
        while self.path.exists():
            self.path = d / f"{stamp} Meeting ({n}).md"
            n += 1
        header = (
            f"# Meeting notes — "
            f"{time.strftime('%d %b %Y, %H:%M', time.localtime(self._started_wall))}\n\n"
            "_Recorded locally by Svara — audio and text never leave this "
            "machine._\n\n## Transcript\n\n")
        self.path.write_text(header, encoding="utf-8")

        for name, target in (("meeting-you", self._capture_mic),
                             ("meeting-them", self._capture_loopback),
                             ("meeting-stt", self._transcribe_worker)):
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            self._threads.append(t)
        log.info("meeting started → %s", self.path.name)
        self.notify("Meeting mode ON — both sides are being noted, locally. "
                    "Tray ▸ Meeting mode again to finish.")

    def stop(self):
        if self._stop.is_set():
            return
        self._stop.set()
        for t in self._threads:
            t.join(timeout=8.0)
        self._drain()
        self._finish()

    # -- capture --------------------------------------------------------------

    def _capture_mic(self):
        import soundcard as sc
        self._capture_loop("You", lambda: sc.default_microphone())

    def _capture_loopback(self):
        import soundcard as sc
        self._capture_loop(
            "Them",
            lambda: sc.get_microphone(str(sc.default_speaker().name),
                                      include_loopback=True))

    def _capture_loop(self, speaker: str, resolve):
        """Capture until stop. The device is re-resolved after any error so a
        headset swap mid-meeting picks up the new default instead of dying."""
        ck = Chunker(silence_ms=float(self.cfg.get("silence_ms", 700)),
                     max_chunk_s=float(self.cfg.get("max_chunk_s", 15)),
                     min_speech_s=float(self.cfg.get("min_speech_s", 0.4)))
        while not self._stop.is_set():
            try:
                dev = resolve()
                with dev.recorder(samplerate=SR, channels=1,
                                  blocksize=BLOCK) as rec:
                    while not self._stop.is_set():
                        block = rec.record(numframes=BLOCK)[:, 0]
                        now = time.monotonic()
                        for started, audio in ck.feed(block, now):
                            self._queue.put((started - self._t0, speaker, audio))
            except Exception as e:  # noqa: BLE001
                if self._stop.is_set():
                    break
                log.warning("meeting %s capture error (%s) — re-resolving "
                            "device in 3s", speaker, type(e).__name__)
                self._stop.wait(3.0)
        now = time.monotonic()
        for started, audio in ck.flush(now):
            self._queue.put((started - self._t0, speaker, audio))

    # -- transcription --------------------------------------------------------

    def _transcribe_worker(self):
        while not (self._stop.is_set() and self._queue.empty()):
            try:
                t_rel, speaker, audio = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue
            self._handle(t_rel, speaker, audio)

    def _drain(self):
        while True:
            try:
                t_rel, speaker, audio = self._queue.get_nowait()
            except queue.Empty:
                return
            self._handle(t_rel, speaker, audio)

    def _handle(self, t_rel: float, speaker: str, audio: np.ndarray):
        try:
            segs = self.get_transcriber().transcribe(audio)
            text = " ".join(t for t, _s, _e in segs).strip()
        except Exception:  # noqa: BLE001 — model mid-reload, or not ready yet
            log.debug("meeting chunk transcription failed", exc_info=True)
            return
        if not text:
            return
        self.entries.append((t_rel, speaker, text))
        self.on_entry(t_rel, speaker, text)
        line = f"- [{_ts(t_rel)}] **{speaker}:** {text}\n"
        try:
            with self._file_lock, open(self.path, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            log.warning("meeting file append failed", exc_info=True)
        log.info("meeting: %s spoke %.1fs → noted (%s)",
                 speaker, len(audio) / SR, shape(text))

    # -- wrap-up --------------------------------------------------------------

    def _finish(self):
        dur = time.monotonic() - self._t0
        summary = None
        if self.entries and self.cfg.get("summary", True):
            transcript = "\n".join(f"[{_ts(t)}] {s}: {x}"
                                   for t, s, x in sorted(self.entries))
            summary = self.llm.run_prompt(SUMMARY_PROMPT, transcript[-24000:])
        try:
            header = (
                f"# Meeting notes — "
                f"{time.strftime('%d %b %Y, %H:%M', time.localtime(self._started_wall))}"
                f" ({_ts(dur)})\n\n"
                "_Recorded locally by Svara — audio and text never leave this "
                "machine._\n\n")
            body = "## Transcript\n\n" + "".join(
                f"- [{_ts(t)}] **{s}:** {x}\n"
                for t, s, x in sorted(self.entries))
            if summary:
                header += f"## Summary\n\n{summary.strip()}\n\n"
            elif self.entries and self.cfg.get("summary", True):
                header += ("_No local LLM was running, so there is no "
                           "summary — the full transcript is below._\n\n")
            with self._file_lock:
                self.path.write_text(header + body, encoding="utf-8")
        except OSError:
            log.warning("meeting file finalise failed", exc_info=True)
        log.info("meeting ended — %s, %d entries%s", _ts(dur),
                 len(self.entries), ", summarised" if summary else "")
        if self.entries:
            self.notify(f"Meeting notes saved ({len(self.entries)} entries"
                        f"{', with summary' if summary else ''}) — opening.")
            try:
                os.startfile(str(self.path))  # noqa: S606
            except OSError:
                pass
        else:
            self.notify("Meeting mode off — nothing was said, no file kept.")
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


def _ts(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
