"""PyInstaller entry point for the packaged MyWhisper.exe.

Mirrors launch.pyw's supervisor (crash auto-restart), but as an importable
module PyInstaller can freeze. Windowed build → no console.
"""
import sys
import time
import traceback
from pathlib import Path


def _app_dir() -> Path:
    # Next to the .exe when frozen, else the project root.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _run_once():
    from mywhisper.__main__ import main

    return main()


def main():
    root = _app_dir()
    restarts = 0
    while True:
        started = time.monotonic()
        try:
            _run_once()
            break
        except SystemExit as e:
            if not e.code:
                break
        except KeyboardInterrupt:
            break
        except Exception:
            try:
                (root / "logs").mkdir(exist_ok=True)
                with open(root / "logs" / "crash.log", "a", encoding="utf-8") as f:
                    f.write(f"\n--- crash {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    f.write(traceback.format_exc())
            except OSError:
                pass
        if time.monotonic() - started > 3600:
            restarts = 0
        restarts += 1
        if restarts > 5:
            break
        time.sleep(3)


if __name__ == "__main__":
    main()
