"""First-run setup: welcome → model + auto-GPU → animated downloads → handoff.

Auto-detects an NVIDIA GPU. If present, offers every model and downloads the
CUDA runtime once (~1.3 GB, animated progress) so the app runs on the GPU.
When the model is loaded the window closes and the caller starts the real app,
which immediately opens the "You're all set" window (howto_ui) — the live test
there runs the production pipeline: pill overlay + streaming words.

run_setup() returns (model_name, transcriber) — a ready Transcriber — or
(None, None) if the window was closed.
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

# (model id, display name, blurb). Ids can be plain whisper sizes or Hugging
# Face CT2 repo ids — faster-whisper takes both. v1 is ENGLISH-FIRST: distil
# models are distilled whisper — same-or-better English accuracy than the next
# size up, smaller and several times faster (that speed IS the live-streaming
# latency). One multilingual escape hatch stays at the bottom; the full
# multilingual lineup returns in a later release.
MODELS = [
    ("base.en", "Base",
     "Recommended — words appear live as you speak, on any PC · ~145 MB"),
    ("Systran/faster-distil-whisper-small.en", "Distil Small",
     "More accurate; live typing trails ~1 s on CPU · ~330 MB"),
    ("tiny.en", "Tiny",
     "For very old PCs — fastest possible, roughest · ~75 MB"),
    ("Systran/faster-distil-whisper-medium.en", "Distil Medium",
     "Great accuracy at half of Medium's size · ~790 MB"),
    ("distil-whisper/distil-large-v3.5-ct2", "Distil Large v3.5",
     "Most accurate English — beats Large Turbo, and faster · ~1.5 GB"),
    ("large-v3-turbo", "Large v3 Turbo · all languages",
     "The multilingual option (90+ languages) · ~1.6 GB"),
]
_CPU_OK = {"tiny.en", "base.en", "Systran/faster-distil-whisper-small.en"}
_NAMES = {value: name for value, name, _sub in MODELS}


def display_name(model: str) -> str:
    """Human label for a model id (repo ids are ugly in UI text)."""
    return _NAMES.get(model, model.split("/")[-1])

# "Ink on paper" palette — matches the website's default Sienna mood.
BG = "#e7d2be"           # paper
CARD = "#f6ebdf"         # panel — a warm cream card on the paper
CARD_ON = "#f0d3bd"      # selected-card tint (accent wash over the card)
FG = "#2c2620"           # ink
SUB = "#807367"          # faded ink (secondary text)
ACCENT = "#c1573a"       # sienna
ACCENT_HOVER = "#e08a5e"
BTN_TEXT = "#f7f2ea"     # cream text on an accent-filled button
ERROR = "#b23b2e"


def _asset(name: str) -> str | None:
    roots = [getattr(sys, "_MEIPASS", None),
             os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
    for base in roots:
        if base:
            p = os.path.join(base, "assets", name)
            if os.path.exists(p):
                return p
    return None


def _apply_config(cfg_path, model: str, device: str, compute: str) -> None:
    try:
        p = Path(cfg_path)
        t = p.read_text(encoding="utf-8")
        t = re.sub(r"(?m)^(  name:\s*)\S+", r"\g<1>" + model, t, count=1)
        t = re.sub(r"(?m)^(  device:\s*)\S+", r"\g<1>" + device, t, count=1)
        t = re.sub(r"(?m)^(  compute_type:\s*)\S+", r"\g<1>" + compute, t, count=1)
        p.write_text(t, encoding="utf-8")
    except OSError:
        log.debug("could not write config", exc_info=True)


def _make_wave_frames(w: int, h: int, n: int):
    from PIL import Image, ImageDraw
    cols = [(224, 138, 94), (193, 87, 58), (143, 58, 38)]  # sienna mood
    mid = h / 2
    frames = []
    for f in range(n):
        ph = 2 * math.pi * f / n
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for i, c in enumerate(cols):
            pts = []
            for x in range(0, w + 4, 4):
                u = x / max(1, w)
                env = math.sin(math.pi * u) ** 0.9
                y = mid + env * (h * 0.30) * math.sin(7 * u + ph + i * 0.9) \
                    + env * (h * 0.17) * math.sin(11 * u - ph * 0.8 - i * 0.6)
                pts.append((x, y))
            d.line(pts, fill=c + (85,), width=6, joint="curve")
            d.line(pts, fill=c + (255,), width=2, joint="curve")
        frames.append(img)
    return frames


def _plan(cfg):
    from . import cuda_setup as cuda
    use_gpu = cuda.gpu_present()
    mlist = MODELS if use_gpu else [m for m in MODELS if m[0] in _CPU_OK]
    valid = [m[0] for m in mlist]
    if use_gpu:
        default = "distil-whisper/distil-large-v3.5-ct2"  # best English pick
    else:
        default = (cfg.get("model") or {}).get("name") or valid[0]
    if default not in valid:
        default = valid[0]
    return use_gpu, mlist, default


def _progress_tqdm(dl):
    """A tqdm stand-in that feeds byte progress into the shared ``dl`` dict.

    Depending on the hub version/backend there is either one aggregate byte
    bar (Xet: created with total=0, total assigned later as sizes resolve) or
    one bar per file — so totals are re-read on every update and summed per
    bar. Downloads run in worker threads, hence the lock.
    """
    from tqdm.auto import tqdm as _tqdm

    lock = threading.Lock()
    totals: dict = {}  # id(bar) -> last known byte total

    class _Tqdm(_tqdm):
        def __init__(self, *a, **k):
            k["disable"] = True  # never render — we only want the numbers
            self._bytes = k.get("unit") == "B"
            super().__init__(*a, **k)

        def update(self, n=1):
            if not self._bytes:
                return
            with lock:
                if n:
                    dl["done"] += n
                totals[id(self)] = max(totals.get(id(self), 0), self.total or 0)
                dl["total"] = sum(totals.values())

    return _Tqdm


def _download_model(model: str, mcfg: dict, dl) -> None:
    """Fetch the model from Hugging Face with real byte progress (idempotent —
    cached files are skipped). faster_whisper's own downloader hardcodes a
    disabled tqdm, so we replicate its snapshot_download call with ours; if
    this fails, WhisperModel simply downloads it itself (no progress)."""
    try:
        # The Xet backend only reports progress at large chunk boundaries —
        # the bar would freeze for a minute at a time on a 1.5 GB model. The
        # classic HTTP path streams smooth per-chunk updates. (Must be set
        # before huggingface_hub is first imported in this process.)
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        import huggingface_hub
        from faster_whisper.utils import _MODELS

        kwargs = {
            "allow_patterns": ["config.json", "preprocessor_config.json",
                               "model.bin", "tokenizer.json", "vocabulary.*"],
            "tqdm_class": _progress_tqdm(dl),
        }
        if mcfg.get("download_root"):
            kwargs["cache_dir"] = mcfg["download_root"]
        huggingface_hub.snapshot_download(_MODELS.get(model, model), **kwargs)
    except Exception:  # noqa: BLE001
        log.debug("model pre-download failed — Transcriber will fetch it",
                  exc_info=True)


def _load_model(cfg, cfg_path, model, use_gpu, dl):
    from . import cuda_setup as cuda
    if use_gpu:
        if not cuda.cuda_available():
            dl["phase"] = "cuda"
            ok = cuda.download_cuda(progress=lambda d, t: dl.update(done=d, total=t))
            if not ok:
                raise RuntimeError("couldn't download GPU support (check your internet)")
        cuda.setup()
        dev, comp = "cuda", "int8_float16"
    else:
        dev, comp = "cpu", "int8"
    _apply_config(cfg_path, model, dev, comp)
    mcfg = dict(cfg["model"])
    mcfg.update(name=model, device=dev, compute_type=comp)
    dl.update(phase="model_dl", done=0, total=0)
    _download_model(model, mcfg, dl)
    dl["phase"] = "model"
    from .transcriber import Transcriber
    return Transcriber(mcfg)


# --------------------------------------------------------------------------- #
#  Modern UI (CustomTkinter)                                                   #
# --------------------------------------------------------------------------- #

def _run_setup_ctk(cfg, cfg_path):
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    use_gpu, mlist, default = _plan(cfg)
    result = {"model": None, "transcriber": None, "error": None}
    dl = {"phase": "", "done": 0, "total": 0}

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
        root.after(900, lambda: root.attributes("-topmost", False))
    except Exception:  # noqa: BLE001
        pass
    _ic = _asset("icon.ico")
    if _ic:
        try:
            root.iconbitmap(_ic)
            root.after(300, lambda: root.iconbitmap(_ic))
        except Exception:  # noqa: BLE001
            pass

    def _strings_banner(parent, wpx, hpx=56, delay=250):
        """An animated flowing-strings label (pre-rendered frames, cycled)."""
        try:
            frames = [ctk.CTkImage(f, size=(wpx, hpx)) for f in _make_wave_frames(wpx, hpx, 26)]
        except Exception:  # noqa: BLE001
            return None
        lbl = ctk.CTkLabel(parent, image=frames[0], text="")
        lbl._frames = frames
        idx = [0]

        def anim():
            if not lbl.winfo_exists():
                return
            idx[0] = (idx[0] + 1) % len(frames)
            lbl.configure(image=frames[idx[0]])
            root.after(60, anim)

        root.after(delay, anim)
        return lbl

    # ------------------------------------------------------------------ #
    #  Setup screen (pick a model)                                        #
    # ------------------------------------------------------------------ #
    action = ctk.CTkFrame(root, fg_color="transparent")
    action.pack(side="bottom", fill="x", padx=26, pady=(6, 20))
    btn = ctk.CTkButton(action, text="Start Svara", height=48, corner_radius=12,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=BTN_TEXT,
                        font=ctk.CTkFont(size=16, weight="bold"))
    btn.pack(fill="x")
    prog = ctk.CTkProgressBar(action, mode="indeterminate", progress_color=ACCENT,
                              fg_color=CARD, height=8, corner_radius=6)
    status = ctk.CTkLabel(action, text=(
        "Runs on your NVIDIA GPU. First launch downloads GPU support (~1.3 GB) once."
        if use_gpu else "No NVIDIA GPU found — runs on the CPU. (Large models are GPU-only.)"),
        text_color=SUB, font=ctk.CTkFont(size=12), wraplength=W - 60, justify="left", anchor="w")
    status.pack(fill="x", pady=(10, 0))

    head = ctk.CTkFrame(root, fg_color="transparent")
    head.pack(side="top", fill="x", padx=26, pady=(20, 0))
    b = _strings_banner(head, W - 52, 56)
    if b:
        b.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(head, text="Welcome to Svara", text_color=FG,
                 font=ctk.CTkFont(size=26, weight="bold"), anchor="w").pack(fill="x")
    ctk.CTkLabel(head, text="Private voice dictation that runs on your own machine.",
                 text_color=SUB, font=ctk.CTkFont(size=13), anchor="w").pack(fill="x", pady=(2, 14))
    howf = ctk.CTkFrame(head, fg_color=CARD, corner_radius=14)
    howf.pack(fill="x")
    for a, bb in (("1   Double-tap", "Right Alt  to start listening"),
                  ("2   Speak", "your words type at the cursor"),
                  ("3   Tap", "Right Alt  to finish  (or hold to push-to-talk)")):
        row = ctk.CTkFrame(howf, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text=a, text_color=ACCENT, font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkLabel(row, text="  " + bb, text_color=FG, font=ctk.CTkFont(size=13)).pack(side="left")
    ctk.CTkLabel(head, text="CHOOSE A MODEL", text_color=SUB,
                 font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", pady=(16, 2))

    scroll = ctk.CTkScrollableFrame(root, fg_color="transparent", scrollbar_button_color="#cbb79f")
    scroll.pack(side="top", fill="both", expand=True, padx=20)

    choice = {"value": default}
    cards: dict = {}

    def select(v):
        choice["value"] = v
        for val, c in cards.items():
            on = val == v
            c["card"].configure(fg_color=CARD_ON if on else CARD, border_color=ACCENT if on else CARD)
            c["dot"].configure(text="●" if on else "○", text_color=ACCENT if on else SUB)

    for value, name, sub in mlist:
        card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=14, border_width=2, border_color=CARD)
        card.pack(fill="x", pady=5)
        dot = ctk.CTkLabel(card, text="○", text_color=SUB, width=22, font=ctk.CTkFont(size=17))
        dot.pack(side="left", padx=(14, 4), pady=12)
        tf = ctk.CTkFrame(card, fg_color="transparent")
        tf.pack(side="left", fill="x", expand=True, pady=8)
        ctk.CTkLabel(tf, text=name, text_color=FG, anchor="w", font=ctk.CTkFont(size=15, weight="bold")).pack(fill="x")
        ctk.CTkLabel(tf, text=sub, text_color=SUB, anchor="w", font=ctk.CTkFont(size=12)).pack(fill="x")
        cards[value] = {"card": card, "dot": dot}
        for w in (card, dot, tf, *tf.winfo_children()):
            w.bind("<Button-1>", lambda e, vv=value: select(vv))
    select(choice["value"])

    # CTkProgressBar re-runs its mode-switch setup (and visibly stutters) if
    # configure(mode=...) is called every tick, even to the SAME mode — so
    # only call it on an actual transition, never unconditionally per poll.
    prog_mode = {"cur": "indeterminate"}  # matches the widget's construction

    def _set_prog_mode(mode: str):
        if prog_mode["cur"] != mode:
            prog.configure(mode=mode)
            prog_mode["cur"] = mode

    def _poll():
        if result["transcriber"] is not None:
            # Hand off: the app starts with this transcriber and immediately
            # opens the "You're all set" window — the REAL pipeline (pill
            # overlay + live streaming), not a mock test loop.
            root.destroy()
            return
        if result["error"] is not None:
            try:
                prog.stop(); prog.pack_forget()
            except Exception:  # noqa: BLE001
                pass
            status.configure(text=f"Setup failed: {result['error']}", text_color=ERROR)
            btn.configure(state="normal", text="Try again")
            return
        if dl["phase"] == "cuda" and dl["total"]:
            frac = dl["done"] / dl["total"]
            try:
                _set_prog_mode("determinate"); prog.set(frac)
            except Exception:  # noqa: BLE001
                pass
            status.configure(
                text=f"⬇  Downloading GPU support…   {dl['done'] >> 20} / {dl['total'] >> 20} MB   ·   {int(frac * 100)}%",
                text_color=ACCENT)
        elif dl["phase"] == "model_dl" and dl["total"]:
            frac = dl["done"] / dl["total"]
            try:
                _set_prog_mode("determinate"); prog.set(frac)
            except Exception:  # noqa: BLE001
                pass
            status.configure(
                text=f"⬇  Downloading the {display_name(choice['value'])} model…   {dl['done'] >> 20} / {dl['total'] >> 20} MB   ·   {int(frac * 100)}%",
                text_color=ACCENT)
        elif dl["phase"] == "model":
            try:
                if prog_mode["cur"] != "indeterminate":
                    prog.configure(mode="indeterminate")
                    prog.start()
                    prog_mode["cur"] = "indeterminate"
            except Exception:  # noqa: BLE001
                pass
            status.configure(text=f"✓ Downloaded — loading the {display_name(choice['value'])} model…", text_color=SUB)
        root.after(120, _poll)

    def _start():
        if btn.cget("state") == "disabled":  # Enter while already setting up
            return
        model = choice["value"]
        btn.configure(state="disabled", text="Setting up…")
        prog.pack(fill="x", pady=(10, 0), before=status)
        prog.start()
        result["error"] = None

        def work():
            try:
                result["transcriber"] = _load_model(cfg, cfg_path, model, use_gpu, dl)
                result["model"] = model
            except Exception as e:  # noqa: BLE001
                result["error"] = str(e)

        threading.Thread(target=work, daemon=True).start()
        root.after(120, _poll)

    btn.configure(command=_start)
    root.bind("<Return>", lambda e: _start())
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return result["model"], result["transcriber"]


# --------------------------------------------------------------------------- #
#  Plain Tk fallback (loads model, then closes — no live test)                #
# --------------------------------------------------------------------------- #

def _run_setup_tk(cfg, cfg_path):
    try:
        from tkinter import ttk
    except Exception:  # noqa: BLE001
        return None, None

    use_gpu, mlist, default = _plan(cfg)
    result = {"model": None, "transcriber": None, "error": None}
    dl = {"phase": "", "done": 0, "total": 0}
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
    _ic = _asset("icon.ico")
    if _ic:
        try:
            root.iconbitmap(_ic)
        except Exception:  # noqa: BLE001
            pass
    outer = tk.Frame(root, bg=BG); outer.pack(fill="both", expand=True)
    action = tk.Frame(outer, bg=BG); action.pack(side="bottom", fill="x", padx=26, pady=(10, 18))
    btn = tk.Button(action, text="Start Svara", bg=ACCENT, fg=BTN_TEXT,
                    font=("Segoe UI Semibold", 13), bd=0, padx=20, pady=11, cursor="hand2")
    btn.pack(fill="x")
    prog = ttk.Progressbar(action, mode="indeterminate", length=W - 52)
    status = tk.Label(action, text=("Runs on your NVIDIA GPU (downloads ~1.3 GB once)."
                                    if use_gpu else "No NVIDIA GPU found — runs on the CPU."),
                      bg=BG, fg=SUB, font=("Segoe UI", 9), wraplength=W - 52, justify="left")
    status.pack(fill="x", pady=(10, 0))
    head = tk.Frame(outer, bg=BG); head.pack(side="top", fill="x", padx=26, pady=(22, 0))
    tk.Label(head, text="Welcome to Svara", bg=BG, fg=FG, font=("Segoe UI Semibold", 22)).pack(anchor="w")
    tk.Label(head, text="Private voice dictation on your own machine.",
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
    choice = {"value": default}
    cards: dict = {}

    def select(v):
        choice["value"] = v
        for val, c in cards.items():
            on = val == v; bg = CARD_ON if on else CARD
            for w in (c["card"], c["dot"], c["txt"], c["name"], c["sub"]):
                w.config(bg=bg)
            c["dot"].config(text="●" if on else "○", fg=ACCENT if on else SUB)

    for value, name, sub in mlist:
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
            root.destroy()  # hand off: the app opens the You're-all-set window
            return
        if result["error"] is not None:
            try:
                prog.stop(); prog.pack_forget()
            except Exception:  # noqa: BLE001
                pass
            status.config(text=f"Setup failed: {result['error']}", fg=ERROR)
            btn.config(state="normal", text="Try again"); return
        if dl["phase"] == "cuda" and dl["total"]:
            status.config(text=f"Downloading GPU support… {dl['done'] >> 20}/{dl['total'] >> 20} MB", fg=FG)
        elif dl["phase"] == "model_dl" and dl["total"]:
            status.config(text=f"Downloading the {display_name(choice['value'])} model… "
                               f"{dl['done'] >> 20}/{dl['total'] >> 20} MB", fg=FG)
        elif dl["phase"] == "model":
            status.config(text=f"Loading the {display_name(choice['value'])} model…", fg=FG)
        root.after(250, _poll)

    def _start(_evt=None):
        if btn["state"] == "disabled":
            return
        model = choice["value"]
        btn.config(state="disabled", text="Setting up…")
        prog.pack(fill="x", pady=(10, 0), before=status); prog.start(12)
        result["error"] = None

        def work():
            try:
                result["transcriber"] = _load_model(cfg, cfg_path, model, use_gpu, dl)
                result["model"] = model
            except Exception as e:  # noqa: BLE001
                result["error"] = str(e)

        threading.Thread(target=work, daemon=True).start()
        root.after(200, _poll)

    btn.config(command=_start); root.bind("<Return>", _start)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    try:
        root.mainloop()
    except Exception:  # noqa: BLE001
        log.debug("tk setup error", exc_info=True)
    return result["model"], result["transcriber"]


def run_setup(cfg, cfg_path):
    try:
        return _run_setup_ctk(cfg, cfg_path)
    except Exception:  # noqa: BLE001
        log.info("modern setup unavailable, using fallback", exc_info=True)
        return _run_setup_tk(cfg, cfg_path)
