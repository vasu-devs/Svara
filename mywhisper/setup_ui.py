"""First-run setup window: welcome, a quick how-to, and a model chooser.

Shown once on the first launch of the packaged app so it isn't a silent
mystery. The user picks a Whisper model (downloaded on demand, with a
progress indicator) and sees how to dictate before the app starts.

run_setup() returns (model_name, transcriber) — a ready-to-use Transcriber so
the app doesn't reload the model — or (None, None) if the window was closed.

Layout notes: the action bar (Start button + progress) is anchored to the
BOTTOM and the model list scrolls, so the button is always reachable no matter
the screen size.
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

BG = "#0a0a0c"
CARD = "#17171c"
CARD_ON = "#10222a"      # accent-tinted when selected
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
    root.minsize(500, 520)
    W = 560
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    H = min(720, sh - 90)
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - 20)}")
    # Come to the front so it isn't lost behind other windows, then release topmost.
    try:
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        root.after(700, lambda: root.attributes("-topmost", False))
    except Exception:  # noqa: BLE001
        pass

    # ttk theme for a flat dark progressbar
    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("S.Horizontal.TProgressbar", troughcolor=CARD,
                        background=ACCENT, bordercolor=CARD, lightcolor=ACCENT,
                        darkcolor=ACCENT)
    except Exception:  # noqa: BLE001
        pass

    outer = tk.Frame(root, bg=BG)
    outer.pack(fill="both", expand=True)

    # ---- bottom action bar (packed FIRST so it's always visible) ----
    action = tk.Frame(outer, bg=BG)
    action.pack(side="bottom", fill="x", padx=26, pady=(10, 18))

    btn = tk.Button(action, text="Start Svara", bg=ACCENT, fg="#06181d",
                    activebackground="#63e3f2", activeforeground="#06181d",
                    font=("Segoe UI Semibold", 13), bd=0, relief="flat",
                    padx=20, pady=11, cursor="hand2")
    btn.pack(fill="x")
    prog = ttk.Progressbar(action, mode="indeterminate", length=W - 52,
                           style="S.Horizontal.TProgressbar")
    status = tk.Label(action, text="The model downloads once (needs internet), then runs offline.",
                      bg=BG, fg=SUB, font=("Segoe UI", 9), wraplength=W - 52, justify="left")
    status.pack(fill="x", pady=(10, 0))

    # ---- top header ----
    head = tk.Frame(outer, bg=BG)
    head.pack(side="top", fill="x", padx=26, pady=(22, 0))
    tk.Label(head, text="Welcome to Svara", bg=BG, fg=FG,
             font=("Segoe UI Semibold", 22)).pack(anchor="w")
    tk.Label(head, text="Private voice dictation that runs on your own machine.",
             bg=BG, fg=SUB, font=("Segoe UI", 11)).pack(anchor="w", pady=(2, 14))

    how = tk.Frame(head, bg=CARD)
    how.pack(fill="x", ipady=8)
    for s in (
        "1.   Double-tap   Right Alt   to start listening",
        "2.   Speak — your words type at the cursor",
        "3.   Tap   Right Alt   to finish   (or hold to push-to-talk)",
    ):
        tk.Label(how, text=s, bg=CARD, fg=FG, font=("Segoe UI", 10),
                 anchor="w", justify="left").pack(fill="x", padx=16, pady=3)

    tk.Label(head, text="CHOOSE A MODEL", bg=BG, fg=SUB,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(16, 4))

    # ---- scrollable model list (fills the middle) ----
    mid = tk.Frame(outer, bg=BG)
    mid.pack(side="top", fill="both", expand=True, padx=(26, 20))
    canvas = tk.Canvas(mid, bg=BG, highlightthickness=0, bd=0)
    vbar = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=BG)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

    valid = [m[0] for m in MODELS]
    default = cfg.get("model", {}).get("name", "base")
    choice = {"value": default if default in valid else "base"}
    cards: dict = {}

    def select(v: str) -> None:
        choice["value"] = v
        for val, c in cards.items():
            on = val == v
            bg = CARD_ON if on else CARD
            for w in (c["card"], c["dot"], c["txt"], c["name"], c["sub"]):
                w.config(bg=bg)
            c["dot"].config(text="●" if on else "○", fg=ACCENT if on else SUB)
            c["bar"].config(bg=ACCENT if on else bg)

    for value, name, sub in MODELS:
        card = tk.Frame(inner, bg=CARD)
        card.pack(fill="x", pady=4)
        bar = tk.Frame(card, bg=CARD, width=4)
        bar.pack(side="left", fill="y")
        dot = tk.Label(card, text="○", bg=CARD, fg=SUB, font=("Segoe UI", 15), width=2)
        dot.pack(side="left", padx=(8, 2), pady=10)
        txt = tk.Frame(card, bg=CARD)
        txt.pack(side="left", fill="x", expand=True, pady=8)
        lname = tk.Label(txt, text=name, bg=CARD, fg=FG,
                         font=("Segoe UI Semibold", 12), anchor="w")
        lname.pack(fill="x")
        lsub = tk.Label(txt, text=sub, bg=CARD, fg=SUB, font=("Segoe UI", 9), anchor="w")
        lsub.pack(fill="x")
        cards[value] = {"card": card, "bar": bar, "dot": dot, "txt": txt,
                        "name": lname, "sub": lsub}
        for w in (card, dot, txt, lname, lsub):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", lambda e, vv=value: select(vv))

    select(choice["value"])

    # ---- model load flow ----
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

    def _start(_evt=None) -> None:
        if btn["state"] == "disabled":
            return
        model = choice["value"]
        btn.config(state="disabled", text="Setting up…")
        status.config(text=f"Setting up the {model} model — downloading once, please wait…", fg=FG)
        prog.pack(fill="x", pady=(10, 0), before=status)
        prog.start(12)
        _write_model_choice(cfg_path, model)
        result["error"] = None
        threading.Thread(target=_load_thread, args=(model,), daemon=True).start()
        root.after(200, _poll)

    btn.config(command=_start)
    root.bind("<Return>", _start)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    try:
        root.mainloop()
    except Exception:  # noqa: BLE001
        log.debug("setup window error", exc_info=True)
    return result["model"], result["transcriber"]
