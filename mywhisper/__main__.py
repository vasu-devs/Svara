"""Entry point: python -m mywhisper [options]"""

import argparse
import ctypes
import logging
import os
import sys
from pathlib import Path


def _single_instance() -> bool:
    """Named-mutex guard so two copies never fight over the hotkey/mic."""
    if os.name != "nt":
        return True
    if getattr(sys, "_mywhisper_mutex", None):
        return True  # already held by this process (supervisor restart)
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "MyWhisper_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return False
    sys._mywhisper_mutex = handle  # keep the handle alive for process lifetime
    return True


def _exe_stamp() -> str:
    """Identity of the running exe (size + mtime). The setup-done flag stores
    this, so a newly downloaded or updated Svara.exe re-runs first-run setup
    instead of silently inheriting a stale flag next to it."""
    try:
        st = Path(sys.executable).stat()
        return f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return "unknown"


def _splash(text: str | None = None, close: bool = False) -> None:
    """Drive the PyInstaller onefile splash screen (no-op in any other build)."""
    try:
        import pyi_splash

        if text is not None:
            pyi_splash.update_text(text)
        if close:
            pyi_splash.close()
    except Exception:  # noqa: BLE001
        pass


def _info_box(text: str, title: str = "Svara") -> None:
    """Topmost native message box — the windowed exe has no console, so this is
    the only way a headless launch can talk to the user."""
    if os.name != "nt":
        return
    try:
        MB_ICONINFORMATION, MB_TOPMOST, MB_SETFOREGROUND = 0x40, 0x40000, 0x10000
        ctypes.windll.user32.MessageBoxW(
            None, text, title, MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    # The keyboard hook thread shares the GIL with rendering/transcription —
    # a snappier switch interval keeps system-wide keyboard input responsive.
    sys.setswitchinterval(0.001)

    # Per-monitor DPI awareness: without this, Windows bitmap-stretches our
    # overlay on scaled displays and it looks blurry ("720p").
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(
        prog="mywhisper",
        description="Local, free, system-wide dictation (Wispr Flow replacement).",
    )
    parser.add_argument("--config", default=None,
                        help="path to config.yaml (default: alongside the package)")
    parser.add_argument("--model", default=None,
                        help="override model name (tiny/base/small/medium/large-v3/large-v3-turbo)")
    parser.add_argument("--cpu", action="store_true", help="force CPU (int8)")
    parser.add_argument("--no-tray", action="store_true", help="disable the tray icon")
    parser.add_argument("--test", type=int, nargs="?", const=5, default=None,
                        metavar="SECONDS",
                        help="record N seconds from the mic, print the transcription, exit")
    parser.add_argument("--doctor", action="store_true",
                        help="run environment diagnostics and exit")
    parser.add_argument("--probe", action="store_true",
                        help="press keys to see their names/codes (find your Fn key)")
    parser.add_argument("--list-devices", action="store_true",
                        help="list audio input devices and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    # Windows consoles often default to cp1252, which can't print ● ✓ 🔒 etc.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    handlers: list[logging.Handler] = []
    if sys.stderr is not None:  # absent when launched via pythonw.exe (silent mode)
        handlers.append(logging.StreamHandler())
    try:
        from logging.handlers import RotatingFileHandler

        from .paths import logs_dir

        handlers.append(RotatingFileHandler(
            logs_dir() / "mywhisper.log", maxBytes=1_000_000, backupCount=2,
            encoding="utf-8",
        ))
    except OSError:
        pass
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    # ctranslate2/faster_whisper are chatty at DEBUG
    logging.getLogger("faster_whisper").setLevel(logging.INFO)

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0

    if args.probe:
        from .hotkey import run_probe

        run_probe()
        return 0

    _splash("Starting Svara — preparing the audio engine…")

    # MUST happen before faster_whisper/ctranslate2 imports:
    from . import cuda_setup

    dll_dirs = cuda_setup.setup()

    from . import config as config_mod

    from .paths import ensure_config, state_path

    cfg_path = args.config or ensure_config()
    cfg = config_mod.load(cfg_path)

    # Last theme/visualizer picked via tray or pill buttons wins over config.
    sp = state_path()
    if sp.is_file():
        try:
            import json

            saved = json.loads(sp.read_text(encoding="utf-8"))
            if saved.get("theme"):
                cfg["ui"]["theme"] = saved["theme"]
            if saved.get("wave"):
                cfg["ui"]["wave"] = saved["wave"]
            if saved.get("bg"):
                cfg["ui"]["bg"] = saved["bg"]
            if saved.get("pos"):
                cfg["ui"]["pos"] = saved["pos"]
            if saved.get("language"):  # "auto" or a whisper language code
                cfg["model"]["language"] = (
                    None if saved["language"] == "auto" else saved["language"])
        except (OSError, ValueError):
            pass

    if args.model:
        cfg["model"]["name"] = args.model
    if args.cpu:
        cfg["model"]["device"] = "cpu"
        cfg["model"]["compute_type"] = "int8"

    if args.doctor:
        from .doctor import run_doctor

        return run_doctor(cfg, dll_dirs)

    if args.test is not None:
        from .app import run_mic_test

        run_mic_test(cfg, args.test)
        return 0

    if not _single_instance():
        _splash(close=True)
        logging.getLogger(__name__).warning(
            "MyWhisper is already running — this copy will exit. "
            "(Check the tray for the mic icon.)"
        )
        # Ask the RUNNING instance to open its Svara window (how-to + test
        # area) — the user's double-click gets a real answer, from the app
        # itself, not a dialog from this doomed copy.
        signaled = False
        if os.name == "nt":
            try:
                EVENT_MODIFY_STATE = 0x0002
                k32 = ctypes.windll.kernel32
                h = k32.OpenEventW(EVENT_MODIFY_STATE, False, "Svara_ShowHowTo")
                if h:
                    signaled = bool(k32.SetEvent(h))
                    k32.CloseHandle(h)
            except Exception:  # noqa: BLE001
                pass
        if not signaled and getattr(sys, "frozen", False):
            # Fallback (an older build without the listener is running).
            hk = cfg["recording"].get("hotkey", "right alt")
            _info_box(
                "Svara is already running.\n\n"
                f"Double-tap  {hk}  in any text field and speak — your words "
                "type at the cursor.\n\n"
                "To change settings or quit, right-click the round mic icon "
                "in the system tray (bottom-right, near the clock — it may be "
                "hidden behind the ^ arrow)."
            )
        return 0

    # First run of the packaged app: show a setup window (welcome + how-to +
    # model chooser) and pre-load the chosen model so the app isn't a silent
    # mystery while the model downloads. Also re-shown to heal a config left
    # by an older build that pinned a big model to the CPU despite an NVIDIA
    # GPU being present (unusably slow — 20-30s per utterance).
    transcriber = None
    from .paths import base_dir
    setup_flag = base_dir() / ".svara_ready"
    stamp = _exe_stamp()
    setup_done = False
    try:
        setup_done = setup_flag.read_text(encoding="utf-8").strip() == stamp
    except OSError:
        pass
    # CPU-viable models: setup_ui._CPU_OK plus legacy ids from older installs
    # (not imported: that module pulls tkinter). The heal only targets big
    # models stranded on the CPU of a GPU machine.
    cpu_ok = ("tiny", "base", "small", "tiny.en", "base.en", "small.en",
              "Systran/faster-distil-whisper-small.en",
              "collabora/faster-whisper-small-hindi")
    stale_cpu_cfg = False
    try:
        from .cuda_setup import gpu_present
        stale_cpu_cfg = (cfg["model"].get("device") == "cpu"
                         and cfg["model"].get("name") not in cpu_ok
                         and gpu_present())
    except Exception:  # noqa: BLE001
        pass
    if (getattr(sys, "frozen", False)
            and (not setup_done or stale_cpu_cfg)
            and not args.no_tray and cfg["ui"].get("tray", True)):
        _splash(close=True)
        try:
            from .setup_ui import run_setup
            model, transcriber = run_setup(cfg, cfg_path)
            if model:
                cfg["model"]["name"] = model
                if transcriber is not None:  # setup loaded it on this device
                    cfg["model"]["device"] = transcriber.device_used
                    cfg["model"]["compute_type"] = transcriber.compute_used
                try:
                    setup_flag.write_text(stamp, encoding="utf-8")
                except OSError:
                    pass
        except Exception:  # noqa: BLE001 — never let setup block the app
            logging.getLogger(__name__).debug("setup window failed", exc_info=True)

    from .app import MyWhisperApp

    _splash(f"Loading the {cfg['model']['name'].split('/')[-1]} speech model…")
    app = MyWhisperApp(cfg, no_tray=args.no_tray, transcriber=transcriber)
    _splash(close=True)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
