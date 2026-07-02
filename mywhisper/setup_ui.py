"""First-run setup window: welcome, a quick how-to, and a model chooser.

Shown once on the first launch of the packaged app so it isn't a silent
mystery. The user picks a Whisper model (downloaded on demand, with a
progress indicator) and sees how to dictate before the app starts.

run_setup() returns (model_name, transcriber) — a ready-to-use Transcriber so
the app doesn't reload the model — or (None, None) if the window was closed.
"""

import logging
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)

# (value, title, subtitle)
MODELS = [
    ("base", "Base", "Recommended · fast, good accuracy · ~150 MB"),
    ("small", "Small", "Better accuracy, a little slower · ~480 MB"),
    ("medium", "Medium", "Great accuracy, slower on CPU · ~1.5 GB"),
    ("tiny", "Tiny", "Fastest, roughest · ~75 MB"),
    ("large-v3-turbo", "Large v3 Turbo", "Best accuracy · ~1.5 GB · GPU recommended"),
]

BG = "#0b0b0d"
CARD = "#16161b"
FG = "#f2f2f4"
SUB = "#9a9aa2"
ACCENT = "#22d3ee"


def _write_model_choice(cfg_path, model: str) -> None:
    """Persist the chosen model into config.yaml, preserving comments."""
    try:
        p = Path(cfg_path)
        text = p.read_text(encoding="utf-8")
        new = re.sub(r"(?m)^(  name:\s*)\S+", r"\g<1>" + model, text, count=1)
        p.write_text(new, encoding="utf-8")
    except OSError:
        log.debug("could not write model choice to config", exc_info=True)


def run_setup(cfg: dict, cfg_path) -> tuple[str | None, object | None]:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:  # noqa: BLE001 — no GUI available, skip setup
        return None, None

    result: dict = {"model": None, "transcriber": None, "error": None}

    root = tk.Tk()
    root.title("Svara — Setup")
    root.configure(bg=BG)
    root.resizable(False, False)
    W, H = 540, 660
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 3)}")

    pad = tk.Frame(root, bg=BG)
    pad.pack(fill="both", expand=True, padx=28, pady=24)

    tk.Label(pad, text="Welcome to Svara", bg=BG, fg=FG,
             font=("Segoe UI Semibold", 22)).pack(anchor="w")
    tk.Label(pad, text="Private voice dictation that runs on your own machine.",
             bg=BG, fg=SUB, font=("Segoe UI", 11)).pack(anchor="w", pady=(2, 18))

    how = tk.Frame(pad, bg=CARD)
    how.pack(fill="x", pady=(0, 18), ipady=8)
    for s in (
        "1.   Double-tap   Right Alt   to start listening",
        "2.   Speak — your words type at the cursor",
        "3.   Tap   Right Alt   once to finish   (or hold to push-to-talk)",
    ):
        tk.Label(how, text=s, bg=CARD, fg=FG, font=("Segoe UI", 10),
                 anchor="w", justify="left").pack(fill="x", padx=16, pady=3)

    tk.Label(pad, text="CHOOSE A MODEL", bg=BG, fg=SUB,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 6))

    valid = [m[0] for m in MODELS]
    default = cfg.get("model", {}).get("name", "base")
    choice = tk.StringVar(value=default if default in valid else "base")

    for value, name, sub in MODELS:
        row = tk.Frame(pad, bg=CARD)
        row.pack(fill="x", pady=3)
        tk.Radiobutton(row, variable=choice, value=value, bg=CARD, fg=ACCENT,
                       activebackground=CARD, selectcolor=CARD,
                       highlightthickness=0, bd=0, takefocus=0).pack(
            side="left", padx=(12, 4), pady=8)
        txt = tk.Frame(row, bg=CARD)
        txt.pack(side="left", fill="x", expand=True)
        tk.Label(txt, text=name, bg=CARD, fg=FG, font=("Segoe UI Semibold", 11),
                 anchor="w").pack(fill="x")
        tk.Label(txt, text=sub, bg=CARD, fg=SUB, font=("Segoe UI", 9),
                 anchor="w").pack(fill="x")

    status = tk.Label(pad, text="The model downloads once (needs internet), then runs offline.",
                      bg=BG, fg=SUB, font=("Segoe UI", 9), wraplength=W - 56, justify="left")
    status.pack(anchor="w", pady=(14, 6))

    prog = ttk.Progressbar(pad, mode="indeterminate", length=W - 56)

    btn = tk.Button(pad, text="Start Svara", bg=ACCENT, fg="#08080a",
                    activebackground="#5fe0f0", activeforeground="#08080a",
                    font=("Segoe UI Semibold", 12), bd=0, relief="flat",
                    padx=20, pady=10, cursor="hand2")
    btn.pack(fill="x", pady=(10, 0))

    def _load_thread(model: str) -> None:
        try:
            mcfg = dict(cfg["model"])
            mcfg["name"] = model
            from .transcriber import Transcriber
            result["transcriber"] = Transcriber(mcfg)
            result["model"] = model
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)

    def _poll() -> None:
        if result["transcriber"] is not None:
            root.destroy()
            return
        if result["error"] is not None:
            try:
                prog.stop()
                prog.pack_forget()
            except Exception:  # noqa: BLE001
                pass
            status.config(text=f"Could not set up the model: {result['error']}", fg="#ff6b6b")
            btn.config(state="normal", text="Try again")
            return
        root.after(200, _poll)

    def _start() -> None:
        model = choice.get()
        btn.config(state="disabled", text="Setting up…")
        status.config(text=f"Setting up the {model} model — downloading once, please wait…", fg=FG)
        prog.pack(fill="x", pady=(6, 0))
        prog.start(12)
        _write_model_choice(cfg_path, model)
        result["error"] = None
        threading.Thread(target=_load_thread, args=(model,), daemon=True).start()
        root.after(200, _poll)

    btn.config(command=_start)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    try:
        root.mainloop()
    except Exception:  # noqa: BLE001
        log.debug("setup window error", exc_info=True)
    return result["model"], result["transcriber"]
