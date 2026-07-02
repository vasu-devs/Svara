"""Silent launcher + supervisor for MyWhisper (no console window).

Run with:  .venv\\Scripts\\pythonw.exe launch.pyw
Used by MyWhisper.bat and the autostart registry entry.

Always-on behavior: if the app ever crashes, it is restarted automatically
(up to 5 times, 3s apart; the counter resets after an hour of uptime).
Crashes are appended to logs\\crash.log; normal logs go to logs\\mywhisper.log.
A clean quit (tray ▸ Quit / Ctrl+C) does NOT restart.
"""
import runpy
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

MAX_RESTARTS = 5
RESTART_DELAY_S = 3
UPTIME_RESET_S = 3600

restarts = 0
while True:
    started = time.monotonic()
    try:
        runpy.run_module("mywhisper", run_name="__main__")
        break  # returned without SystemExit — treat as clean
    except SystemExit as e:
        if not e.code:
            break  # clean quit
    except KeyboardInterrupt:
        break
    except Exception:
        try:
            (ROOT / "logs").mkdir(exist_ok=True)
            with open(ROOT / "logs" / "crash.log", "a", encoding="utf-8") as f:
                f.write(f"\n--- crash at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                f.write(traceback.format_exc())
        except OSError:
            pass

    if time.monotonic() - started > UPTIME_RESET_S:
        restarts = 0  # ran fine for a long while — fresh restart budget
    restarts += 1
    if restarts > MAX_RESTARTS:
        break
    time.sleep(RESTART_DELAY_S)
