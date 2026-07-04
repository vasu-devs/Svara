"""MyWhisper application — wires everything together.

Flow:  long-press hotkey ▶ Recorder (pre-roll + mic) ▶ queue ▶ worker thread
       worker: faster-whisper ▶ cleanup pipeline ▶ Win32 text injection
       UX:     on-screen pill overlay + tray icon + audio feedback
"""

import json
import logging
import os
import queue
import sys
import threading
import time

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
    import math
    import struct
    import winsound

    _SR = 44100
    _TONE_CACHE: dict[tuple[float, int, float], bytes] = {}

    def _make_tone(freq: float, ms: int, vol: float) -> bytes:
        """A short, soft sine-wave chime — winsound.Beep is a raw square wave
        with hard on/off edges (a harsh click), so this shapes a sine with a
        smooth attack/release envelope instead: pleasant, not alarming."""
        n = int(_SR * ms / 1000)
        attack = max(1, int(_SR * 0.008))
        release = max(1, int(_SR * 0.05))
        samples = bytearray()
        for i in range(n):
            env = min(1.0, i / attack) * min(1.0, (n - i) / release)
            s = math.sin(2 * math.pi * freq * i / _SR) * vol * env
            samples += struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + len(samples), b"WAVE", b"fmt ", 16, 1, 1, _SR,
            _SR * 2, 2, 16, b"data", len(samples))
        return header + bytes(samples)

    def _chime(freq: float, ms: int = 130, vol: float = 0.3):
        key = (freq, ms, vol)
        wav = _TONE_CACHE.get(key)
        if wav is None:
            wav = _make_tone(freq, ms, vol)
            _TONE_CACHE[key] = wav

        def _play():
            try:
                winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_play, daemon=True).start()
except ImportError:  # non-Windows dev machine
    def _chime(freq: float, ms: int = 130, vol: float = 0.3):
        pass


class MyWhisperApp:
    def __init__(self, cfg: dict, no_tray: bool = False, transcriber=None,
                 show_welcome: bool = False):
        self.cfg = cfg
        self.show_welcome = show_welcome  # setup just finished → open You're-all-set
        self.paused = False
        self._stop_lock = threading.Lock()
        self._shutdown = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._stream_ctx: dict | None = None
        self._stopping = False
        self._voice_rms: float | None = None  # your speaking-loudness baseline

        self._model_switch = False
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

    def _refresh_tray(self):
        """pystray only rebuilds its native menu after one of ITS OWN item
        clicks fires (or at startup) — a change made from the Svara window
        never runs through that path, so the tray would keep showing stale
        checked-state/text until the user happened to click some unrelated
        tray item. Call this after any out-of-band state change."""
        if self.tray and self.tray.icon:
            try:
                self.tray.icon.update_menu()
            except Exception:  # noqa: BLE001
                pass

    # -- model switching -------------------------------------------------------

    @property
    def is_multilingual(self) -> bool:
        """Whether the ACTIVE model understands non-English speech (gates the
        language picker — offering Hindi on an English-only model is a trap)."""
        try:
            return bool(self.transcriber.model.model.is_multilingual)
        except Exception:  # noqa: BLE001
            return True

    def set_model(self, value: str):
        """Switch models live from the tray: download if needed (toast
        progress), load in a worker thread, swap atomically, persist.
        Dictation keeps working on the old model until the new one is ready."""
        if self._model_switch or value == self.cfg["model"]["name"]:
            return
        if self.recorder.recording:
            # A live switch mid-utterance would hand the streamer/worker a
            # different model than the one whose partial-word hypothesis
            # they're already mid-way through aligning against — garbled or
            # duplicated text, silently. Simplest safe rule: finish first.
            if self.tray:
                self.tray.notify("Finish this dictation first, then switch "
                                 "models — mid-recording switches can garble "
                                 "the live text.")
            return
        self._model_switch = True

        def work():
            try:
                from . import cuda_setup as cuda
                from .paths import ensure_config
                from .setup_ui import (_CPU_OK, _apply_config, _download_model,
                                       display_name)
                name = display_name(value)
                dev = self.transcriber.device_used
                comp = self.transcriber.compute_used
                # A GPU-tier model with no GPU present would otherwise load
                # silently on CPU (tens of seconds per utterance) — exactly
                # what the CPU-first default was chosen to avoid.
                if value not in _CPU_OK and not cuda.gpu_present():
                    if self.tray:
                        self.tray.notify(
                            f"{name} needs an NVIDIA GPU, which this machine "
                            "doesn't have — staying on the current model.")
                    return
                # Upgrading to a big model on a GPU machine still running CPU:
                # fetch the CUDA runtime so the upgrade actually delivers.
                if (value not in _CPU_OK and dev == "cpu"
                        and cuda.gpu_present() and not cuda.cuda_available()):
                    if self.tray:
                        self.tray.notify(
                            f"Downloading GPU support (~1.3 GB) for {name}— "
                            "one time, please wait…")
                    if cuda.download_cuda():
                        cuda.setup()
                        dev, comp = "cuda", "int8_float16"
                if self.tray:
                    self.tray.notify(f"Getting {name} ready — dictation keeps "
                                     "working on the current model meanwhile…")
                mcfg = dict(self.cfg["model"])
                mcfg.update(name=value, device=dev, compute_type=comp)
                _download_model(value, mcfg, {"done": 0, "total": 0})
                new = Transcriber(mcfg)  # loads + warms up
                self.transcriber = new
                self.cfg["model"]["name"] = value
                self.cfg["model"]["device"] = new.device_used
                self.cfg["model"]["compute_type"] = new.compute_used
                _apply_config(ensure_config(), value, new.device_used,
                              new.compute_used)
                if self.tray:
                    self.tray.notify(f"✓ {name} is now active "
                                     f"(on {new.device_used})")
                log.info("model → %s on %s", value, new.device_used)
            except Exception:  # noqa: BLE001
                log.exception("model switch failed")
                if self.tray:
                    self.tray.notify("Model switch failed — still on "
                                     f"{self.cfg['model']['name']}. "
                                     "See logs/mywhisper.log")
            finally:
                self._model_switch = False
                self._refresh_tray()

        threading.Thread(target=work, daemon=True, name="model-switch").start()

    @property
    def gpu_available(self) -> bool:
        """Whether an NVIDIA GPU is present (gates the Device menu's GPU option)."""
        try:
            from . import cuda_setup as cuda
            return cuda.gpu_present()
        except Exception:  # noqa: BLE001
            return False

    def set_device(self, device: str):
        """Switch the CURRENT model to run on cpu or cuda, live from the tray.
        Downloads the CUDA runtime on first switch to GPU if needed."""
        if self._model_switch or device == self.transcriber.device_used:
            return
        if self.recorder.recording:
            if self.tray:
                self.tray.notify("Finish this dictation first, then switch "
                                 "devices — mid-recording switches can garble "
                                 "the live text.")
            return
        self._model_switch = True

        def work():
            try:
                from . import cuda_setup as cuda
                from .paths import ensure_config
                from .setup_ui import _apply_config

                if device == "cuda":
                    if not cuda.gpu_present():
                        if self.tray:
                            self.tray.notify("No NVIDIA GPU detected on this machine.")
                        return
                    if not cuda.cuda_available():
                        if self.tray:
                            self.tray.notify(
                                "Downloading GPU support (~1.3 GB) — one time, "
                                "please wait…")
                        if not cuda.download_cuda():
                            if self.tray:
                                self.tray.notify(
                                    "Couldn't download GPU support — staying on CPU.")
                            return
                    cuda.setup()
                    comp = "int8_float16"
                else:
                    comp = "int8"
                if self.tray:
                    self.tray.notify(f"Switching to {device.upper()} — dictation "
                                     "keeps working on the current device "
                                     "meanwhile…")
                mcfg = dict(self.cfg["model"])
                mcfg.update(device=device, compute_type=comp)
                new = Transcriber(mcfg)  # loads + warms up
                self.transcriber = new
                self.cfg["model"]["device"] = new.device_used
                self.cfg["model"]["compute_type"] = new.compute_used
                _apply_config(ensure_config(), self.cfg["model"]["name"],
                              new.device_used, new.compute_used)
                if self.tray:
                    self.tray.notify(f"✓ Now running on {new.device_used.upper()}")
                log.info("device → %s (%s)", new.device_used, new.compute_used)
            except Exception:  # noqa: BLE001
                log.exception("device switch failed")
                if self.tray:
                    self.tray.notify("Device switch failed — still on "
                                     f"{self.transcriber.device_used.upper()}. "
                                     "See logs/mywhisper.log")
            finally:
                self._model_switch = False
                self._refresh_tray()

        threading.Thread(target=work, daemon=True, name="device-switch").start()

    # -- streaming ------------------------------------------------------------

    def set_streaming_mode(self, mode: str):
        """live = type as you speak · preview = show while speaking, type after
        · off = classic batch. Takes effect on the next recording, persists."""
        self.cfg["streaming"]["mode"] = mode
        self._save_state(streaming_mode=mode)
        self._refresh_tray()
        log.info("streaming → %s", mode)

    # -- language ------------------------------------------------------------

    @property
    def current_language(self):
        """Whisper language code in effect, or None for auto-detect."""
        return self.transcriber.cfg.get("language")

    def set_language(self, code):
        """Switch the transcription language live (None = auto-detect)."""
        # transcriber.cfg is its OWN dict (setup_ui builds a fresh copy of
        # cfg["model"] to construct it) — writing only there meant the next
        # set_model()/set_device() would rebuild from the original, still-
        # stale cfg["model"] and silently revert the language just picked.
        # cfg["model"] is the source of truth; keep the live transcriber in
        # sync too so the change takes effect immediately, not just later.
        self.cfg["model"]["language"] = code
        self.transcriber.cfg["language"] = code
        self._save_state(language=code or "auto")
        self._refresh_tray()
        log.info("language → %s", code or "auto-detect")

    # -- the Svara window (how-to + live test + language) ---------------------

    def show_howto(self, first_run: bool = False):
        from .howto_ui import show_howto

        show_howto(self, first_run=first_run)

    def _howto_signal_listener(self):
        """When the user double-clicks Svara.exe again, that doomed copy
        signals this named event — respond by opening the Svara window
        instead of leaving the click unanswered."""
        if os.name != "nt":
            return
        import ctypes

        k32 = ctypes.windll.kernel32
        handle = k32.CreateEventW(None, False, False, "Svara_ShowHowTo")
        if not handle:
            return
        try:
            while not self._shutdown.is_set():
                if k32.WaitForSingleObject(handle, 500) == 0:  # WAIT_OBJECT_0
                    log.info("second launch detected — opening the Svara window")
                    self.show_howto()
        finally:
            k32.CloseHandle(handle)

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
        # No sound here by design — the pill's appearance is the "you're being
        # heard" cue; a tone on every single dictation start got old fast.
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
            _chime(784, 130, 0.3)  # G5 — soft, bright: "now hands-free"
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
                _chime(440, 90, 0.2)  # A4 — soft, brief: "discarded, no big deal"
            log.info("✕ cancelled (tap)")

    def stop_recording(self):
        """Stop with a ~0.4s tail-grace: the mic keeps capturing briefly so the
        word you were finishing when you tapped never gets cut off."""
        if self._stopping or not self.recorder.recording:
            return
        self._stopping = True
        self.overlay.hide()  # pill closes right at your tap — no tick, no counter
        if self.cfg["ui"]["sounds"]:
            _chime(587, 150, 0.32)  # D5 — warm: "done, working on it"
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
        threading.Thread(target=self._howto_signal_listener, daemon=True,
                         name="howto-signal").start()

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

        # Setup just completed: open the "You're all set" window — its live
        # test runs THIS pipeline (pill overlay + streaming words), so what
        # the user tries is exactly what they get everywhere else.
        if self.show_welcome:
            threading.Timer(0.8, lambda: self.show_howto(first_run=True)).start()

        # Packaged app: a double-click must never look like "nothing happened".
        # Flash the pill briefly and toast from the tray once the icon is up.
        if getattr(sys, "frozen", False):
            self.overlay.show("listening")
            threading.Timer(1.8, lambda: (
                self.overlay.hide() if not self.recorder.recording else None
            )).start()
            if self.tray and not self.show_welcome:
                threading.Timer(1.2, lambda: self.tray.notify(
                    f"Ready — double-tap {hk} in any text field and speak. "
                    "I live in the system tray (near the clock).")).start()

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
