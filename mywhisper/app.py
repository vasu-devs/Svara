"""MyWhisper application — wires everything together.

Flow:  long-press hotkey ▶ Recorder (pre-roll + mic) ▶ queue ▶ worker thread
       worker: faster-whisper ▶ cleanup pipeline ▶ Win32 text injection
       UX:     on-screen pill overlay + tray icon + audio feedback
"""

import json
import logging
import queue
import threading
import time
from pathlib import Path

import numpy as np

from .audio import Recorder
from .cleanup import CleanupPipeline
from .hotkey import create_listener
from .injector import TextInjector
from .overlay import Overlay
from .transcriber import Transcriber
from .tray import Tray

log = logging.getLogger(__name__)

try:
    import winsound

    def _beep(freq: int, ms: int):
        threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()
except ImportError:  # non-Windows dev machine
    def _beep(freq: int, ms: int):
        pass


class MyWhisperApp:
    def __init__(self, cfg: dict, no_tray: bool = False, transcriber=None):
        self.cfg = cfg
        self.paused = False
        self._stop_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._stream_ctx: dict | None = None
        self._stopping = False
        self._voice_rms: float | None = None  # your speaking-loudness baseline

        self.recorder = Recorder(cfg["audio"], cfg["recording"])
        self.injector = TextInjector(cfg["injection"])
        self.cleanup = CleanupPipeline(cfg["cleanup"])
        self.current_theme = cfg["ui"].get("theme", "minimal-dark")
        self.current_wave = cfg["ui"].get("wave", "strings")
        self.current_bg = cfg["ui"].get("bg", "gradient")
        self.session_words = 0
        self.overlay = Overlay(
            cfg["ui"],
            get_level=lambda: self.recorder.level,
            on_click=self._pill_clicked,
            on_cycle=self.cycle_theme,
            on_cycle_wave=self.cycle_wave,
            on_cycle_bg=self.cycle_bg,
            get_stats=lambda: (
                self.recorder.elapsed(),
                self.session_words,
                f"{self.current_theme} · {self.current_wave} · {self.current_bg}",
            ),
            on_move=lambda x, y: self._save_state(pos=[x, y]),
        )
        # Reuse a transcriber already loaded during first-run setup, else load now.
        self.transcriber = transcriber or Transcriber(cfg["model"])  # loads + warms up

        self.hotkey = create_listener(
            cfg["recording"],
            on_start=self.start_recording,
            on_commit=self.stop_recording,
            on_cancel=self.cancel_recording,
            on_lock=self.on_lock,
            is_recording=lambda: self.recorder.recording,
        )
        self.tray = Tray(self) if (cfg["ui"]["tray"] and not no_tray) else None

    # -- properties for the tray -------------------------------------------

    @property
    def model_label(self) -> str:
        return (
            f"{self.cfg['model']['name']} on {self.transcriber.device_used} "
            f"({self.transcriber.compute_used})"
        )

    def toggle_paused(self):
        self.paused = not self.paused
        log.info("Paused" if self.paused else "Resumed")

    def toggle_fillers(self):
        self.cleanup.strip_fillers_enabled = not self.cleanup.strip_fillers_enabled

    def toggle_llm(self):
        self.cleanup.llm.cfg["enabled"] = not self.cleanup.llm.cfg["enabled"]

    def _save_state(self, **kv):
        from .paths import state_path

        sp = state_path()
        try:
            state = {}
            if sp.is_file():
                state = json.loads(sp.read_text(encoding="utf-8"))
            state.update(kv)
            sp.write_text(json.dumps(state), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def cycle_theme(self):
        """◐ button on the pill: next color theme, live. Persists."""
        from .themes import theme_names

        names = theme_names()
        idx = names.index(self.current_theme) if self.current_theme in names else -1
        self.set_theme(names[(idx + 1) % len(names)])

    def cycle_wave(self):
        """✦ button on the pill: next visualizer style, live. Persists."""
        from .overlay import WAVES

        idx = WAVES.index(self.current_wave) if self.current_wave in WAVES else -1
        self.set_wave_named(WAVES[(idx + 1) % len(WAVES)])

    def cycle_bg(self):
        """▦ button / right-click the pill: next background style. Persists."""
        from .overlay import BGS

        idx = BGS.index(self.current_bg) if self.current_bg in BGS else -1
        self.set_bg_named(BGS[(idx + 1) % len(BGS)])

    def set_wave_named(self, name: str):
        self.current_wave = name
        self.overlay.set_wave(name)
        self._save_state(wave=name)
        log.info("visualizer → %s", name)

    def set_bg_named(self, name: str):
        self.current_bg = name
        self.overlay.set_bg(name)
        self._save_state(bg=name)
        log.info("background → %s", name)

    def set_theme(self, name: str):
        """Switch the overlay theme live and remember it across restarts."""
        self.current_theme = name
        self.overlay.set_theme(name)
        if not self.recorder.recording:  # brief preview of the new look
            self.overlay.show("listening")
            threading.Timer(1.4, lambda: (
                self.overlay.hide() if not self.recorder.recording else None
            )).start()
        self._save_state(theme=name)
        log.info("theme → %s", name)

    # -- recording control ----------------------------------------------------

    def start_recording(self):
        if self.paused or self.recorder.recording:
            return
        self.recorder.start()
        self.overlay.show("listening")
        if self.cfg["ui"]["sounds"]:
            _beep(1175, 60)
        if self.tray:
            self.tray.set_recording(True)
        if self.cfg["streaming"]["mode"] in ("preview", "live"):
            self._stream_ctx = {"typed_total": 0}
            threading.Thread(target=self._streamer, args=(self._stream_ctx,),
                             daemon=True, name="streamer").start()
        log.info("● recording…")

    def on_lock(self):
        """Double-tap: hands-free mode — recording continues until next tap."""
        self.overlay.show("locked")
        if self.cfg["ui"]["sounds"]:
            _beep(1568, 60)
        log.info("🔒 locked (hands-free) — tap %s to finish",
                 self.cfg["recording"]["hotkey"])

    def _pill_clicked(self):
        """Clicking the pill finishes the recording (same as the hotkey)."""
        if self.recorder.recording:
            self.stop_recording()

    # -- loudness → CAPS (expressive formatting) --------------------------------

    def _seg_caps_flags(self, segs, window, update: bool = False) -> list[bool]:
        """Per-segment CAPS flags, judged against the MEDIAN loudness of the
        utterance itself (blended with a slow global baseline).

        The median is shout-proof and seed-proof: one loud segment can't drag
        it, and a quiet first segment can't poison it — the failure mode that
        made everything type in caps.
        """
        exp = self.cfg["cleanup"]["expressive"]
        sr = self.recorder.sr
        rms: list[float] = []
        for _text, start, end in segs:
            seg = window[int(start * sr):int(end * sr)]
            rms.append(float(np.sqrt(np.mean(seg * seg)))
                       if len(seg) >= sr // 10 else 0.0)
        vals = [r for r in rms if r > 1e-6]
        med = float(np.median(vals)) if vals else 0.0
        if med > 1e-6:
            if self._voice_rms is None:
                self._voice_rms = med
            elif update:
                self._voice_rms = 0.9 * self._voice_rms + 0.1 * med
        base = self._voice_rms or med
        out: list[bool] = []
        for (_text, start, end), r in zip(segs, rms):
            out.append(bool(
                exp["enabled"] and base > 1e-6
                and (end - start) >= 0.35          # sustained, not a pop
                and r >= exp["caps_ratio"] * base
            ))
        return out

    def _word_caps_flags(self, segs, window, update: bool = False) -> list[bool]:
        """Per-word CAPS flags (aligned with the joined word list of segs)."""
        seg_flags = self._seg_caps_flags(segs, window, update=update)
        flags: list[bool] = []
        for (text, _s, _e), f in zip(segs, seg_flags):
            flags.extend([f] * len(text.split()))
        return flags

    @staticmethod
    def _apply_caps(words: list[str], flags: list[bool]) -> list[str]:
        return [w.upper() if i < len(flags) and flags[i] else w
                for i, w in enumerate(words)]

    def cancel_recording(self):
        """Quick tap: discard whatever was captured, inject nothing."""
        with self._stop_lock:
            # keep_tail: a cancel is usually tap 1 of a double-tap — hand its
            # audio to the pre-roll so the locked recording hears everything
            audio = self.recorder.stop(keep_tail=True)
        self._stream_ctx = None  # stops the streamer thread
        self.overlay.hide()
        if self.tray:
            self.tray.set_recording(False)
        if audio is not None:
            if self.cfg["ui"]["sounds"]:
                _beep(440, 50)
            log.info("✕ cancelled (tap)")

    def stop_recording(self):
        """Stop with a ~0.4s tail-grace: the mic keeps capturing briefly so the
        word you were finishing when you tapped never gets cut off."""
        if self._stopping or not self.recorder.recording:
            return
        self._stopping = True
        self.overlay.hide()  # pill closes right at your tap — no tick, no counter
        if self.cfg["ui"]["sounds"]:
            _beep(880, 60)
        threading.Timer(0.4, self._finalize_stop).start()

    def _finalize_stop(self):
        try:
            with self._stop_lock:
                audio = self.recorder.stop()  # clears pre-roll: no tail leaks
            ctx, self._stream_ctx = self._stream_ctx, None
            if self.tray:
                self.tray.set_recording(False)
            if audio is None:
                self.overlay.hide()
                return
            self._queue.put((audio, ctx))
        finally:
            self._stopping = False

    # -- background threads -----------------------------------------------------

    def _monitor(self):
        """Auto-stop on silence, max-duration cap, and mic health (always-on)."""
        rec_cfg = self.cfg["recording"]
        auto = rec_cfg["auto_stop"]
        last_health = time.monotonic()
        while not self._shutdown.is_set():
            time.sleep(0.05)
            if not self.recorder.recording:
                # Every 3s while idle: revive the mic stream if it died
                # (headset unplug, sleep/resume, device switch).
                now = time.monotonic()
                if now - last_health >= 3.0:
                    last_health = now
                    self.recorder.ensure_alive()
                continue
            if self.recorder.elapsed() > rec_cfg["max_seconds"]:
                log.info("max duration reached — stopping")
                self.stop_recording()
            elif (
                rec_cfg["mode"] == "press_to_toggle"
                and auto["enabled"]
                and not self.hotkey.locked
                and self.recorder.speech_ms() >= auto["min_speech_ms"]
                and self.recorder.silence_ms() >= auto["silence_ms"]
            ):
                log.info("silence detected — stopping")
                self.stop_recording()

    def _streamer(self, ctx: dict):
        """While recording: re-transcribe the rolling buffer every interval.

        preview → live words shown inside the pill (nothing typed until stop).
        live    → words typed at the cursor once two consecutive passes agree
                  on them (LocalAgreement); the final pass appends the rest.

        Latency control: audio whose words are fully committed gets TRIMMED at
        segment (silence) boundaries, so each pass only re-transcribes a small
        recent window — the pass time stays ~constant however long you talk.
        """
        scfg = self.cfg["streaming"]
        interval = scfg["interval_ms"] / 1000.0
        sr = self.recorder.sr
        min_samples = int(scfg["min_audio_s"] * sr)
        live = scfg["mode"] == "live"
        # Shared with the worker: the final pass MUST see the same window and
        # committed words, so its hypothesis aligns 1:1 with what was typed.
        ctx.setdefault("t0", 0)          # samples trimmed (their words are typed)
        ctx.setdefault("committed", [])  # words typed since t0
        last_words: list[str] = []
        while (self.recorder.recording and ctx is self._stream_ctx
               and not self._shutdown.is_set()):
            t_start = time.perf_counter()
            if live and self.hotkey.held:
                # Long-press in progress: nothing can be typed while the key is
                # down, so don't burn GPU on passes whose window only grows —
                # the release-finalization transcribes it all in one go.
                time.sleep(0.1)
                continue
            audio = self.recorder.snapshot()
            if audio is not None and len(audio) - ctx["t0"] >= min_samples:
                try:
                    window = audio[ctx["t0"]:] if live else audio[-20 * sr:]
                    segs = self.transcriber.transcribe_partial(window)
                    if not (self.recorder.recording and ctx is self._stream_ctx):
                        break
                    words = " ".join(t for t, _, _ in segs).split()
                    if not live:
                        self.overlay.set_preview(" ".join(words))
                    elif words:
                        committed = ctx["committed"]
                        agree = 0
                        for a, b in zip(words, last_words):
                            if a != b:
                                break
                            agree += 1
                        if words == last_words:
                            # hypothesis fully settled (you paused / stopped
                            # talking) → release everything, incl. the last word
                            stable = words
                        else:
                            stable = words[:max(agree - 1, 0)]  # hold back 1 word
                        new = stable[len(committed):]
                        # While the hotkey (Alt!) is physically held, synthetic
                        # keystrokes would arrive as Alt+char and get eaten by
                        # the app — buffer instead; the release-finalization
                        # types everything the moment the key comes up.
                        if new and not self.hotkey.held:
                            # loudness → CAPS on the way out; committed stays raw
                            # so hypothesis alignment is never disturbed
                            flags = self._word_caps_flags(segs, window)
                            styled = self._apply_caps(
                                words, flags)[len(committed):len(stable)]
                            self.injector.inject_stream(" ".join(styled) + " ")
                            committed.extend(new)
                            ctx["typed_total"] += len(new)
                            self.session_words += len(new)
                        last_words = words
                        # Trim whole segments whose words are all typed —
                        # never the last (still-active) segment.
                        win_dur = len(window) / sr
                        cum, trim_sec = 0, 0.0
                        for text, _start, end in segs[:-1]:
                            wc = len(text.split())
                            if cum + wc <= len(committed) and end < win_dur - 0.5:
                                cum += wc
                                trim_sec = end
                            else:
                                break
                        if cum:
                            ctx["t0"] += int(trim_sec * sr)
                            ctx["committed"] = committed[cum:]
                            last_words = last_words[cum:] if cum <= len(last_words) else []
                except Exception:  # noqa: BLE001
                    log.debug("streaming pass failed", exc_info=True)
            time.sleep(max(0.05, interval - (time.perf_counter() - t_start)))

    def _worker(self):
        """Transcribe → clean → inject, in arrival order."""
        while not self._shutdown.is_set():
            try:
                audio, ctx = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                dur = len(audio) / self.recorder.sr
                typed = (ctx or {}).get("typed_total", 0)
                if typed:
                    # Live mode already typed a prefix. Finalize with the SAME
                    # decoder over the SAME trimmed window the streamer used —
                    # the hypothesis aligns word-for-word with what was typed,
                    # so nothing gets dropped or duplicated. Also much faster
                    # than re-transcribing the whole utterance.
                    t0 = time.perf_counter()
                    window = audio[(ctx or {}).get("t0", 0):]
                    segs = self.transcriber.transcribe_partial(window)
                    t_stt = time.perf_counter() - t0
                    words = " ".join(t for t, _, _ in segs).split()
                    committed = (ctx or {}).get("committed", [])
                    flags = self._word_caps_flags(segs, window, update=True)
                    remainder = self._apply_caps(words, flags)[len(committed):]
                    tail = " ".join(remainder)
                    n = self.injector.inject(tail) if tail else 0
                    self.session_words += len(remainder)
                    self.overlay.hide()
                    log.info("✓ %.1fs audio → live-typed, +%d final chars in %.2fs",
                             dur, n, t_stt)
                    continue
                t0 = time.perf_counter()
                segs = self.transcriber.transcribe(audio)
                t_stt = time.perf_counter() - t0
                if not segs:
                    self.overlay.hide()
                    log.info("(no speech detected — %.1fs of audio)", dur)
                    continue
                # loudness → CAPS per segment, then the cleanup pipeline
                seg_flags = self._seg_caps_flags(segs, audio, update=True)
                text = " ".join(
                    (seg_text.upper() if loud else seg_text)
                    for (seg_text, _s, _e), loud in zip(segs, seg_flags))
                t0 = time.perf_counter()
                text = self.cleanup.run(text)
                t_clean = time.perf_counter() - t0
                n = self.injector.inject(text)
                self.session_words += len(text.split())
                self.overlay.hide()
                preview = text if len(text) <= 80 else text[:77] + "…"
                log.info(
                    "✓ %.1fs audio → %d chars in %.2fs stt + %.2fs cleanup | %s",
                    dur, n, t_stt, t_clean, preview,
                )
            except Exception:  # noqa: BLE001 — one bad utterance must not kill the app
                self.overlay.hide()
                log.exception("failed to process utterance")

    # -- lifecycle -------------------------------------------------------------------

    def run(self):
        self.recorder.open()
        self.hotkey.start()
        threading.Thread(target=self._monitor, daemon=True, name="monitor").start()
        threading.Thread(target=self._worker, daemon=True, name="worker").start()

        hk = self.cfg["recording"]["hotkey"]
        mode = self.cfg["recording"]["mode"]
        if mode == "press_to_toggle":
            log.info("MyWhisper ready — press %s to start, press again "
                     "(or click the pill) to stop.", hk)
        elif "+" in hk:
            log.info("MyWhisper ready — hold %s and speak.", hk)
        else:
            log.info("MyWhisper ready — long-press [%s] and speak "
                     "(tap = cancel, double-tap = hands-free lock).", hk)

        try:
            if self.tray and self.tray.icon:
                self.tray.run()  # blocks until tray Quit
            else:
                while not self._shutdown.is_set():
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        if self._shutdown.is_set():
            return
        log.info("shutting down…")
        self._shutdown.set()
        try:
            self.hotkey.stop()
        except Exception:  # noqa: BLE001
            pass
        self.recorder.close()
        self.overlay.stop()
        if self.tray:
            self.tray.stop()


def run_mic_test(cfg: dict, seconds: int):
    """`--test N`: record N seconds from the mic and print the transcription."""
    print(f"Loading model '{cfg['model']['name']}'…")
    transcriber = Transcriber(cfg["model"])
    recorder = Recorder(cfg["audio"], cfg["recording"])
    recorder.open()
    time.sleep(0.5)  # let the stream + pre-roll settle
    print(f"\n🎙  SPEAK NOW — recording {seconds}s…")
    recorder.start()
    for i in range(seconds, 0, -1):
        print(f"   …{i}", flush=True)
        time.sleep(1)
    audio = recorder.stop()
    recorder.close()
    if audio is None:
        print("No audio captured — check your microphone (--list-devices).")
        return
    t0 = time.perf_counter()
    segs = transcriber.transcribe(audio)
    text = " ".join(t for t, _, _ in segs)
    dt = time.perf_counter() - t0
    print(f"\nTranscribed {len(audio) / recorder.sr:.1f}s of audio in {dt:.2f}s "
          f"on {transcriber.device_used} ({transcriber.compute_used}):")
    print(f"\n  ➜ {text or '(no speech detected)'}\n")
