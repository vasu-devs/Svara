"""First-run setup screen: welcome, a quick how-to, and a model chooser.

Primary UI is a modern CustomTkinter window (rounded, dark, on-brand). Falls
back to plain Tk if CustomTkinter is unavailable. run_setup() returns
(model_name, transcriber) — a ready Transcriber so the app doesn't reload the
model — or (None, None) if the window was closed.
"""

import logging
import math
import os
import re
import sys
import threading
import tkinter as tk
from pathlib import Path

log = logging.getLogger(__name__)


def _asset(name: str) -> str | None:
    """Path to a bundled asset (frozen _MEIPASS or the source tree)."""
    roots = [getattr(sys, "_MEIPASS", None),
             os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for base in roots:
        if base:
            p = os.path.join(base, "assets", name)
            if os.path.exists(p):
                return p
    return None

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
CARD_ON = "#0f2028"
FG = "#f2f2f4"
SUB = "#9a9aa4"
ACCENT = "#22d3ee"
ACCENT_HOVER = "#4fe0f2"


def _write_model_choice(cfg_path, model: str) -> None:
    """Persist the chosen model into config.yaml, preserving comments."""
    try:
        p = Path(cfg_path)
        text = p.read_text(encoding="utf-8")
        new = re.sub(r"(?m)^(  name:\s*)\S+", r"\g<1>" + model, text, count=1)
        p.write_text(new, encoding="utf-8")
    except OSError:
        log.debug("could not write model choice to config", exc_info=True)


# --------------------------------------------------------------------------- #
#  Modern UI (CustomTkinter)                                                   #
# --------------------------------------------------------------------------- #

def _run_setup_ctk(cfg: dict, cfg_path) -> tuple[str | None, object | None]:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    result: dict = {"model": None, "transcriber": None, "error": None}

    root = ctk.CTk()
    root.title("Svara — Setup")
    root.configure(fg_color=BG)
    W = 580
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    H = min(760, sh - 80)
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - 20)}")
    root.minsize(520, 560)
    try:
        root.attributes("-topmost", True)
        root.lift()
        root.after(120, root.focus_force)
        root.after(800, lambda: root.attributes("-topmost", False))
    except Exception:  # noqa: BLE001
        pass
    _ic = _asset("icon.ico")
    if _ic:
        try:
            root.iconbitmap(_ic)
            root.after(300, lambda: root.iconbitmap(_ic))  # CTk can reset it late
        except Exception:  # noqa: BLE001
            pass

    # ---- bottom action bar (packed first → always visible) ----
    action = ctk.CTkFrame(root, fg_color="transparent")
    action.pack(side="bottom", fill="x", padx=26, pady=(6, 20))
    btn = ctk.CTkButton(action, text="Start Svara", height=48, corner_radius=12,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#06181d",
                        font=ctk.CTkFont(size=16, weight="bold"))
    btn.pack(fill="x")
    prog = ctk.CTkProgressBar(action, mode="indeterminate", progress_color=ACCENT,
                              fg_color=CARD, height=6, corner_radius=6)
    status = ctk.CTkLabel(action, text="The model downloads once (needs internet), then runs offline.",
                          text_color=SUB, font=ctk.CTkFont(size=12), wraplength=W - 60,
                          justify="left", anchor="w")
    status.pack(fill="x", pady=(10, 0))

    # ---- header (Svara logo + wordmark) ----
    head = ctk.CTkFrame(root, fg_color="transparent")
    head.pack(side="top", fill="x", padx=26, pady=(22, 0))
    brand = ctk.CTkFrame(head, fg_color="transparent")
    brand.pack(fill="x")
    _logo = _asset("icon.png")
    if _logo:
        try:
            from PIL import Image
            _img = ctk.CTkImage(Image.open(_logo), size=(48, 48))
            _lbl = ctk.CTkLabel(brand, image=_img, text="")
            _lbl._img_ref = _img  # keep a reference
            _lbl.pack(side="left", padx=(0, 12))
        except Exception:  # noqa: BLE001
            pass
    ctk.CTkLabel(brand, text="Svara", text_color=FG,
                 font=ctk.CTkFont(size=30, weight="bold")).pack(side="left")
    ctk.CTkLabel(head, text="Private voice dictation that runs on your own machine.",
                 text_color=SUB, font=ctk.CTkFont(size=13), anchor="w").pack(fill="x", pady=(12, 14))
    howf = ctk.CTkFrame(head, fg_color=CARD, corner_radius=14)
    howf.pack(fill="x")
    for a, b in (("1   Double-tap", "Right Alt  to start listening"),
                 ("2   Speak", "your words type at the cursor"),
                 ("3   Tap", "Right Alt  to finish  (or hold to push-to-talk)")):
        r = ctk.CTkFrame(howf, fg_color="transparent")
        r.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(r, text=a, text_color=ACCENT, font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").pack(side="left")
        ctk.CTkLabel(r, text="  " + b, text_color="#dcdce0", font=ctk.CTkFont(size=13),
                     anchor="w").pack(side="left")
    ctk.CTkLabel(head, text="CHOOSE A MODEL", text_color=SUB,
                 font=ctk.CTkFont(size=11, weight="bold"), anchor="w").pack(fill="x", pady=(16, 2))

    # ---- scrollable model list ----
    scroll = ctk.CTkScrollableFrame(root, fg_color="transparent",
                                    scrollbar_button_color="#2a2a30")
    scroll.pack(side="top", fill="both", expand=True, padx=20)

    valid = [m[0] for m in MODELS]
    default = cfg.get("model", {}).get("name", "base")
    choice = {"value": default if default in valid else "base"}
    cards: dict = {}

    def select(v):
        choice["value"] = v
        for val, c in cards.items():
            on = val == v
            c["card"].configure(fg_color=CARD_ON if on else CARD,
                                border_color=ACCENT if on else CARD)
            c["dot"].configure(text="●" if on else "○", text_color=ACCENT if on else SUB)

    for value, name, sub in MODELS:
        card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=14,
                            border_width=2, border_color=CARD)
        card.pack(fill="x", pady=5)
        dot = ctk.CTkLabel(card, text="○", text_color=SUB, width=22,
                           font=ctk.CTkFont(size=17))
        dot.pack(side="left", padx=(14, 4), pady=12)
        tf = ctk.CTkFrame(card, fg_color="transparent")
        tf.pack(side="left", fill="x", expand=True, pady=8)
        nm = ctk.CTkLabel(tf, text=name, text_color=FG, anchor="w",
                          font=ctk.CTkFont(size=15, weight="bold"))
        nm.pack(fill="x")
        sb = ctk.CTkLabel(tf, text=sub, text_color=SUB, anchor="w",
                          font=ctk.CTkFont(size=12))
        sb.pack(fill="x")
        cards[value] = {"card": card, "dot": dot}
        for w in (card, dot, tf, nm, sb):
            w.bind("<Button-1>", lambda e, vv=value: select(vv))
    select(choice["value"])

    def _poll():
        if result["transcriber"] is not None:
            root.destroy()
            return
        if result["error"] is not None:
            try:
                prog.stop()
                prog.pack_forget()
            except Exception:  # noqa: BLE001
                pass
            status.configure(text=f"Could not set up the model: {result['error']}",
                             text_color="#ff7a7a")
            btn.configure(state="normal", text="Try again")
            return
        root.after(200, _poll)

    def _load(model):
        try:
            mcfg = dict(cfg["model"])
            mcfg["name"] = model
            from .transcriber import Transcriber
            result["transcriber"] = Transcriber(mcfg)
            result["model"] = model
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)

    def _start():
        model = choice["value"]
        btn.configure(state="disabled", text="Setting up…")
        status.configure(text=f"Setting up the {model} model — downloading once, please wait…",
                         text_color=FG)
        prog.pack(fill="x", pady=(10, 0), before=status)
        prog.start()
        _write_model_choice(cfg_path, model)
        result["error"] = None
        threading.Thread(target=_load, args=(model,), daemon=True).start()
        root.after(200, _poll)

    btn.configure(command=_start)
    root.bind("<Return>", lambda e: _start())
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return result["model"], result["transcriber"]


# --------------------------------------------------------------------------- #
#  Plain Tk fallback                                                           #
# --------------------------------------------------------------------------- #

def _run_setup_tk(cfg: dict, cfg_path) -> tuple[str | None, object | None]:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:  # noqa: BLE001
        return None, None

    result: dict = {"model": None, "transcriber": None, "error": None}
    root = tk.Tk()
    root.title("Svara — Setup")
    root.configure(bg=BG)
    root.minsize(500, 520)
    W = 560
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    H = min(720, sh - 90)
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - 20)}")
    try:
        root.attributes("-topmost", True); root.lift(); root.focus_force()
        root.after(700, lambda: root.attributes("-topmost", False))
    except Exception:  # noqa: BLE001
        pass
    outer = tk.Frame(root, bg=BG); outer.pack(fill="both", expand=True)
    action = tk.Frame(outer, bg=BG); action.pack(side="bottom", fill="x", padx=26, pady=(10, 18))
    btn = tk.Button(action, text="Start Svara", bg=ACCENT, fg="#06181d",
                    font=("Segoe UI Semibold", 13), bd=0, padx=20, pady=11, cursor="hand2")
    btn.pack(fill="x")
    prog = ttk.Progressbar(action, mode="indeterminate", length=W - 52)
    status = tk.Label(action, text="The model downloads once, then runs offline.",
                      bg=BG, fg=SUB, font=("Segoe UI", 9), wraplength=W - 52, justify="left")
    status.pack(fill="x", pady=(10, 0))
    head = tk.Frame(outer, bg=BG); head.pack(side="top", fill="x", padx=26, pady=(22, 0))
    tk.Label(head, text="Welcome to Svara", bg=BG, fg=FG, font=("Segoe UI Semibold", 22)).pack(anchor="w")
    tk.Label(head, text="Private voice dictation that runs on your own machine.",
             bg=BG, fg=SUB, font=("Segoe UI", 11)).pack(anchor="w", pady=(2, 14))
    tk.Label(head, text="CHOOSE A MODEL", bg=BG, fg=SUB, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(6, 4))
    mid = tk.Frame(outer, bg=BG); mid.pack(side="top", fill="both", expand=True, padx=(26, 20))
    canvas = tk.Canvas(mid, bg=BG, highlightthickness=0, bd=0)
    vbar = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=BG)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True); vbar.pack(side="right", fill="y")
    inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))
    valid = [m[0] for m in MODELS]
    default = cfg.get("model", {}).get("name", "base")
    choice = {"value": default if default in valid else "base"}
    cards: dict = {}

    def select(v):
        choice["value"] = v
        for val, c in cards.items():
            on = val == v; bg = CARD_ON if on else CARD
            for w in (c["card"], c["dot"], c["txt"], c["name"], c["sub"]):
                w.config(bg=bg)
            c["dot"].config(text="●" if on else "○", fg=ACCENT if on else SUB)

    for value, name, sub in MODELS:
        card = tk.Frame(inner, bg=CARD); card.pack(fill="x", pady=4)
        dot = tk.Label(card, text="○", bg=CARD, fg=SUB, font=("Segoe UI", 15), width=2); dot.pack(side="left", padx=(10, 2), pady=10)
        txt = tk.Frame(card, bg=CARD); txt.pack(side="left", fill="x", expand=True, pady=8)
        lname = tk.Label(txt, text=name, bg=CARD, fg=FG, font=("Segoe UI Semibold", 12), anchor="w"); lname.pack(fill="x")
        lsub = tk.Label(txt, text=sub, bg=CARD, fg=SUB, font=("Segoe UI", 9), anchor="w"); lsub.pack(fill="x")
        cards[value] = {"card": card, "dot": dot, "txt": txt, "name": lname, "sub": lsub}
        for w in (card, dot, txt, lname, lsub):
            w.configure(cursor="hand2"); w.bind("<Button-1>", lambda e, vv=value: select(vv))
    select(choice["value"])

    def _poll():
        if result["transcriber"] is not None:
            root.destroy(); return
        if result["error"] is not None:
            try:
                prog.stop(); prog.pack_forget()
            except Exception:  # noqa: BLE001
                pass
            status.config(text=f"Could not set up the model: {result['error']}", fg="#ff6b6b")
            btn.config(state="normal", text="Try again"); return
        root.after(200, _poll)

    def _load(model):
        try:
            mcfg = dict(cfg["model"]); mcfg["name"] = model
            from .transcriber import Transcriber
            result["transcriber"] = Transcriber(mcfg); result["model"] = model
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e)

    def _start(_evt=None):
        if btn["state"] == "disabled":
            return
        model = choice["value"]
        btn.config(state="disabled", text="Setting up…")
        status.config(text=f"Setting up the {model} model — downloading once, please wait…", fg=FG)
        prog.pack(fill="x", pady=(10, 0), before=status); prog.start(12)
        _write_model_choice(cfg_path, model); result["error"] = None
        threading.Thread(target=_load, args=(model,), daemon=True).start()
        root.after(200, _poll)

    btn.config(command=_start); root.bind("<Return>", _start)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    try:
        root.mainloop()
    except Exception:  # noqa: BLE001
        log.debug("tk setup error", exc_info=True)
    return result["model"], result["transcriber"]


def run_setup(cfg: dict, cfg_path) -> tuple[str | None, object | None]:
    try:
        return _run_setup_ctk(cfg, cfg_path)
    except Exception:  # noqa: BLE001 — CustomTkinter missing → plain fallback
        log.info("modern setup unavailable, using fallback window", exc_info=True)
        return _run_setup_tk(cfg, cfg_path)
