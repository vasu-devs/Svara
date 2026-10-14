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
from itertools import count
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

# Paper, ink and one amber — the same palette as the website's transcript page
# and the pill. Ink is the words; amber is what Svara does to them. Buttons are
# ink-filled squares so the pill shape belongs to the pill alone.
BG = "#f4f2ed"           # paper
CARD = "#faf9f5"         # a lighter sheet laid on the paper
CARD_ON = "#f3e8d4"      # selected: an amber wash over the sheet
FG = "#17140f"           # ink
SUB = "#6f675e"          # faded ink (secondary text)
ACCENT = "#a8681a"       # amber ink: labels, marks, the selected dot
ACCENT_HOVER = "#c27a1f"
AMBER = "#d9922b"        # amber light: progress, caret, the selected bar
RULE = "#d9d5cc"         # hairlines
BTN = "#17140f"          # primary buttons are ink
BTN_HOVER = "#000000"
BTN_TEXT = "#f4f2ed"     # paper text on an ink button
ERROR = "#b23b2e"

# Proof-reader's inks, for the transform diff. Two marks on the same paper —
# not "terminal red/green", which belongs to a dark editor and is what makes a
# light window look like two designs stitched together.
#
# DIFF_DEL is a deeper red-brown than the amber accent on purpose: struck-out
# text must never read as a highlight. Both inks are matched for weight on
# CARD so neither additions nor deletions shout louder than the other.
DIFF_DEL = "#a8341c"     # struck out
DIFF_ADD = "#2f6b4f"     # written in


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
    """The brand mark: three amber strands, pre-rendered as frames."""
    from PIL import Image, ImageDraw
    cols = [(242, 184, 90), (232, 163, 61), (193, 87, 58)]  # amber triad
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
            d.line(pts, fill=c + (70,), width=max(3, h // 8), joint="curve")
            d.line(pts, fill=c + (255,), width=max(1, h // 22), joint="curve")
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


def smooth_fraction(done: int, total: int, floor: float = 0.0) -> float:
    """Download progress that never moves backwards.

    The reported total GROWS during a multi-file download: huggingface_hub
    creates one tqdm bar per file, as each file starts, so the denominator is
    only complete once every file is under way. A naive done/total therefore
    climbs, then jumps back the instant the next file's size lands, and the bar
    visibly jitters for the whole download.

    Clamping to a high-water mark fixes the jitter without lying: the byte
    counts shown next to the bar stay exact, and the percentage simply refuses
    to regress. Also clamped to 1.0, since a total that resolves late can
    briefly leave done > total.
    """
    if total <= 0:
        return floor
    return max(floor, min(1.0, done / total))


def _progress_tqdm(dl):
    """A tqdm stand-in that feeds byte progress into the shared ``dl`` dict.

    Depending on the hub version/backend there is either one aggregate byte
    bar (Xet: created with total=0, total assigned later as sizes resolve) or
    one bar per file — so totals are re-read on every update and summed per
    bar. Downloads run in worker threads, hence the lock.
    """
    from tqdm.auto import tqdm as _tqdm

    lock = threading.Lock()
    totals: dict = {}   # bar key -> last known byte total
    counter = count()   # NOT id(): see below

    class _Tqdm(_tqdm):
        def __init__(self, *a, **k):
            k["disable"] = True  # never render — we only want the numbers
            self._bytes = k.get("unit") == "B"
            # id() is reused after garbage collection, so a finished bar's id
            # can be handed to a later one. Combined with the max() below that
            # permanently inflates the total, and the bar then stalls short of
            # 100% for the rest of the download. A counter cannot alias.
            self._key = next(counter)
            super().__init__(*a, **k)

        def update(self, n=1):
            if not self._bytes:
                return
            with lock:
                if n:
                    dl["done"] += n
                totals[self._key] = max(totals.get(self._key, 0), self.total or 0)
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
    mcfg = dict(cfg["model"])
    mcfg.update(name=model, device=dev, compute_type=comp)
    dl.update(phase="model_dl", done=0, total=0)
    _download_model(model, mcfg, dl)
    dl["phase"] = "model"
    from .transcriber import Transcriber
    # required=True: first-run setup has a human watching a progress bar. A
    # failure here must surface as "Setup failed — Try again", not as a window
    # that closes onto an app that cannot transcribe.
    transcriber = Transcriber(mcfg, required=True)  # may fall back to cpu internally
    # Write the ACTUAL outcome, not the plan — Transcriber's own fallback
    # ladder can quietly land on cpu/int8 even when use_gpu was true (e.g.
    # a CUDA/cuDNN mismatch that only surfaces during kernel init), and
    # writing the planned cuda/int8_float16 here would leave config.yaml
    # permanently claiming a device that doesn't actually work — every
    # future launch would retry and fail CUDA before falling back, forever.
    _apply_config(cfg_path, model, transcriber.device_used, transcriber.compute_used)
    return transcriber


def _hotkey_label(hk: str) -> str:
    """'right alt' → 'Right Alt', 'ctrl+shift+space' → 'Ctrl+Shift+Space'."""
    return "+".join(" ".join(p.capitalize() for p in part.split())
                    for part in hk.split("+"))


# --------------------------------------------------------------------------- #
#  Modern UI (CustomTkinter)                                                   #
# --------------------------------------------------------------------------- #

def _run_setup_ctk(cfg, cfg_path):
    import customtkinter as ctk

    from . import __version__
    from .ui_fonts import DEVANAGARI, serif_family, ui_family

    ctk.set_appearance_mode("light")
    use_gpu, mlist, default = _plan(cfg)
    result = {"model": None, "transcriber": None, "error": None}
    dl = {"phase": "", "done": 0, "total": 0}

    root = ctk.CTk()
    root.title("Svara — Setup")
    root.configure(fg_color=BG)
    W = 600
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    # winfo_screenheight() reports PHYSICAL pixels (the process is per-monitor
    # DPI aware), while CTk's geometry() is in LOGICAL ones and scales them up.
    # So `min(760, sh - 80)` looked like it left an 80px margin and actually
    # rendered 950px tall on a 125% display, pushing the model list and the
    # status line past the bottom edge — on the first screen a new user sees.
    # Convert the available height into the same units geometry() speaks.
    try:
        scale = float(ctk.ScalingTracker.get_window_scaling(root))
    except Exception:  # noqa: BLE001
        scale = 1.0
    usable = int((sh - 56) / max(scale, 0.1))
    H = max(580, min(880, usable))
    root.geometry(f"{W}x{H}+{(sw - W) // 2}"
                  f"+{max(0, int((sh - H * scale) / 2) - 20)}")
    root.minsize(540, 560)
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

    SERIF, UI = serif_family(), ui_family()
    MONO = "Cascadia Mono"
    try:
        import tkinter.font as tkfont
        if "Cascadia Mono" not in set(tkfont.families(root)):
            MONO = "Consolas"
    except Exception:  # noqa: BLE001
        MONO = "Consolas"
    f_serif = ctk.CTkFont(family=SERIF, size=30)
    f_ui = ctk.CTkFont(family=UI, size=13)
    f_ui_b = ctk.CTkFont(family=UI, size=13, weight="bold")
    f_ui_s = ctk.CTkFont(family=UI, size=12)
    f_mono = ctk.CTkFont(family=MONO, size=11)
    f_mono_xs = ctk.CTkFont(family=MONO, size=10)
    PX = 28  # the window's side margin

    def _mark(parent, wpx=40, hpx=20, delay=250):
        """The animated strings mark (pre-rendered frames, cycled)."""
        try:
            frames = [ctk.CTkImage(f, size=(wpx, hpx)) for f in _make_wave_frames(wpx * 2, hpx * 2, 26)]
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
    #  Footer first, so it is anchored and can never be pushed off-screen #
    # ------------------------------------------------------------------ #
    action = ctk.CTkFrame(root, fg_color="transparent")
    action.pack(side="bottom", fill="x", padx=PX, pady=(8, 20))
    btn = ctk.CTkButton(action, text="Start Svara  →", height=48, corner_radius=8,
                        fg_color=BTN, hover_color=BTN_HOVER, text_color=BTN_TEXT,
                        font=ctk.CTkFont(family=UI, size=15, weight="bold"))
    btn.pack(fill="x")
    prog = ctk.CTkProgressBar(action, mode="indeterminate", progress_color=AMBER,
                              fg_color=RULE, height=4, corner_radius=2)
    status = ctk.CTkLabel(action, text=(
        "Runs on your NVIDIA GPU. The first launch downloads GPU support (~1.3 GB) once."
        if use_gpu else "No NVIDIA GPU found — runs on the CPU. Large models are GPU-only."),
        text_color=SUB, font=f_mono_xs, wraplength=W - 2 * PX - 4, justify="left", anchor="w")
    status.pack(fill="x", pady=(10, 0))

    # ------------------------------------------------------------------ #
    #  Header: mark, wordmark, version                                     #
    # ------------------------------------------------------------------ #
    head = ctk.CTkFrame(root, fg_color="transparent")
    head.pack(side="top", fill="x", padx=PX, pady=(18, 0))
    m = _mark(head)
    if m:
        m.pack(side="left", padx=(0, 8))
    ctk.CTkLabel(head, text="Svara", text_color=FG, font=ctk.CTkFont(family=UI, size=14, weight="bold")).pack(side="left")
    ctk.CTkLabel(head, text="स्वर", text_color=SUB, font=ctk.CTkFont(family=DEVANAGARI, size=12)).pack(side="left", padx=(6, 0))
    ctk.CTkLabel(head, text=f"v{__version__}", text_color=SUB, font=f_mono_xs).pack(side="right")

    # ------------------------------------------------------------------ #
    #  The words                                                           #
    # ------------------------------------------------------------------ #
    ctk.CTkLabel(root, text="Talk into any app.\nNothing leaves your PC.", text_color=FG,
                 font=f_serif, justify="left", anchor="w").pack(fill="x", padx=PX, pady=(18, 0))
    ctk.CTkLabel(root, text="Pick a speech model. Everything runs on this machine, and nothing you say leaves it.",
                 text_color=SUB, font=f_ui, anchor="w", justify="left", wraplength=W - 2 * PX - 4
                 ).pack(fill="x", padx=PX, pady=(6, 0))

    # How it goes, as keycaps: what you press, what happens.
    hk_label = _hotkey_label((cfg.get("recording") or {}).get("hotkey", "right alt"))
    how = ctk.CTkFrame(root, fg_color="transparent")
    how.pack(side="top", fill="x", padx=PX, pady=(14, 0))

    def _cap(text):
        return ctk.CTkLabel(how, text=text, text_color=FG, fg_color=CARD, corner_radius=6,
                            font=f_mono_xs, padx=8, pady=3)

    def _arrow():
        return ctk.CTkLabel(how, text="→", text_color=SUB, font=f_ui_s)

    _cap(f"{hk_label}  ×2").pack(side="left")
    _arrow().pack(side="left", padx=8)
    ctk.CTkLabel(how, text="speak", text_color=FG, font=f_ui_s).pack(side="left")
    _arrow().pack(side="left", padx=8)
    _cap(hk_label).pack(side="left")
    ctk.CTkLabel(how, text="to finish, or hold it to push-to-talk", text_color=SUB,
                 font=f_ui_s).pack(side="left", padx=(10, 0))

    ctk.CTkLabel(root, text="MODEL", text_color=ACCENT, font=f_mono_xs, anchor="w"
                 ).pack(fill="x", padx=PX, pady=(20, 6))

    # ------------------------------------------------------------------ #
    #  Model list: one sheet, hairlines between rows, an amber bar marks   #
    #  the choice. An explicit height matters: without one the scrollable  #
    #  frame REQUESTS as much room as its rows need and pushes the Start   #
    #  button off the bottom; a small request lets pack hand it what is    #
    #  actually left, and it scrolls inside that.                          #
    # ------------------------------------------------------------------ #
    scroll = ctk.CTkScrollableFrame(root, fg_color=CARD, corner_radius=10, height=180,
                                    scrollbar_button_color=RULE, scrollbar_button_hover_color=SUB)
    scroll.pack(side="top", fill="both", expand=True, padx=PX)

    choice = {"value": default}
    cards: dict = {}

    def select(v):
        choice["value"] = v
        for val, c in cards.items():
            on = val == v
            c["row"].configure(fg_color=CARD_ON if on else "transparent")
            c["bar"].configure(fg_color=AMBER if on else CARD)
            c["dot"].configure(text="●" if on else "○", text_color=ACCENT if on else SUB)
            c["name"].configure(text_color=FG)

    for i, (value, name, sub) in enumerate(mlist):
        if i:
            ctk.CTkFrame(scroll, height=1, fg_color=RULE, corner_radius=0).pack(fill="x", padx=12)
        row = ctk.CTkFrame(scroll, fg_color="transparent", corner_radius=6)
        row.pack(fill="x", padx=4, pady=2)
        # CTk frames request 200×200 unless told otherwise; an unsized bar
        # would stretch every row to 200 px and hide the list behind a scroll.
        bar = ctk.CTkFrame(row, width=3, height=30, fg_color=CARD, corner_radius=2)
        bar.pack(side="left", padx=(4, 0), pady=12)
        dot = ctk.CTkLabel(row, text="○", text_color=SUB, width=22, font=ctk.CTkFont(family=UI, size=15))
        dot.pack(side="left", padx=(8, 2), pady=10)
        tf = ctk.CTkFrame(row, fg_color="transparent")
        tf.pack(side="left", fill="x", expand=True, pady=8, padx=(0, 10))
        nm = ctk.CTkLabel(tf, text=name, text_color=FG, anchor="w", font=f_ui_b)
        nm.pack(fill="x")
        ctk.CTkLabel(tf, text=sub, text_color=SUB, anchor="w", font=f_ui_s, justify="left",
                     wraplength=W - 2 * PX - 90).pack(fill="x")
        cards[value] = {"row": row, "bar": bar, "dot": dot, "name": nm}
        for w in (row, bar, dot, tf, *tf.winfo_children()):
            w.bind("<Button-1>", lambda e, vv=value: select(vv))
            try:
                w.configure(cursor="hand2")
            except Exception:  # noqa: BLE001
                pass
    select(choice["value"])

    # On a GPU machine the recommended model is fifth in the list, below the
    # fold: open the list already scrolled to it so the choice is visible.
    def _reveal_choice():
        try:
            idx = [m[0] for m in mlist].index(choice["value"])
            scroll._parent_canvas.yview_moveto(max(0.0, (idx - 0.5) / len(mlist)))
        except Exception:  # noqa: BLE001 - a private CTk attribute; cosmetic
            pass

    root.after(80, _reveal_choice)

    # CTkProgressBar re-runs its mode-switch setup (and visibly stutters) if
    # configure(mode=...) is called every tick, even to the SAME mode — so
    # only call it on an actual transition, never unconditionally per poll.
    prog_mode = {"cur": "indeterminate"}  # matches the widget's construction

    def _set_prog_mode(mode: str):
        if prog_mode["cur"] != mode:
            prog.configure(mode=mode)
            prog_mode["cur"] = mode

    # High-water mark per phase, so the bar cannot run backwards when the next
    # file's size lands and grows the denominator. Per phase, because the CUDA
    # runtime and the model are two separate downloads that each start at zero.
    seen = {"cuda": 0.0, "model_dl": 0.0}

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
            btn.configure(state="normal", text="Try again  →")
            return
        if dl["phase"] == "cuda" and dl["total"]:
            frac = smooth_fraction(dl["done"], dl["total"], seen["cuda"])
            seen["cuda"] = frac
            try:
                _set_prog_mode("determinate"); prog.set(frac)
            except Exception:  # noqa: BLE001
                pass
            status.configure(
                text=f"Downloading GPU support   {dl['done'] >> 20} / {dl['total'] >> 20} MB   ·   {int(frac * 100)}%",
                text_color=ACCENT)
        elif dl["phase"] == "model_dl" and dl["total"]:
            frac = smooth_fraction(dl["done"], dl["total"], seen["model_dl"])
            seen["model_dl"] = frac
            try:
                _set_prog_mode("determinate"); prog.set(frac)
            except Exception:  # noqa: BLE001
                pass
            status.configure(
                text=f"Downloading {display_name(choice['value'])}   {dl['done'] >> 20} / {dl['total'] >> 20} MB   ·   {int(frac * 100)}%",
                text_color=ACCENT)
        elif dl["phase"] == "model":
            try:
                if prog_mode["cur"] != "indeterminate":
                    prog.configure(mode="indeterminate")
                    prog.start()
                    prog_mode["cur"] = "indeterminate"
            except Exception:  # noqa: BLE001
                pass
            status.configure(text=f"Downloaded. Loading {display_name(choice['value'])}…", text_color=SUB)
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

    from .ui_fonts import serif_family

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
    SERIF = serif_family()
    outer = tk.Frame(root, bg=BG); outer.pack(fill="both", expand=True)
    action = tk.Frame(outer, bg=BG); action.pack(side="bottom", fill="x", padx=26, pady=(10, 18))
    btn = tk.Button(action, text="Start Svara  →", bg=BTN, fg=BTN_TEXT, activebackground=BTN_HOVER,
                    activeforeground=BTN_TEXT, font=("Segoe UI Semibold", 13), bd=0, padx=20, pady=11, cursor="hand2")
    btn.pack(fill="x")
    prog = ttk.Progressbar(action, mode="indeterminate", length=W - 52)
    status = tk.Label(action, text=("Runs on your NVIDIA GPU (downloads ~1.3 GB once)."
                                    if use_gpu else "No NVIDIA GPU found — runs on the CPU."),
                      bg=BG, fg=SUB, font=("Consolas", 9), wraplength=W - 52, justify="left")
    status.pack(fill="x", pady=(10, 0))
    head = tk.Frame(outer, bg=BG); head.pack(side="top", fill="x", padx=26, pady=(22, 0))
    tk.Label(head, text="Talk into any app.\nNothing leaves your PC.", bg=BG, fg=FG,
             font=(SERIF, 24), justify="left").pack(anchor="w")
    tk.Label(head, text="Pick a speech model. Everything runs on this machine.",
             bg=BG, fg=SUB, font=("Segoe UI", 11)).pack(anchor="w", pady=(4, 14))
    tk.Label(head, text="MODEL", bg=BG, fg=ACCENT, font=("Consolas", 9)).pack(anchor="w", pady=(6, 4))
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
        card = tk.Frame(inner, bg=CARD); card.pack(fill="x", pady=2)
        dot = tk.Label(card, text="○", bg=CARD, fg=SUB, font=("Segoe UI", 14), width=2); dot.pack(side="left", padx=(10, 2), pady=10)
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
            btn.config(state="normal", text="Try again  →"); return
        if dl["phase"] == "cuda" and dl["total"]:
            status.config(text=f"Downloading GPU support   {dl['done'] >> 20}/{dl['total'] >> 20} MB", fg=FG)
        elif dl["phase"] == "model_dl" and dl["total"]:
            status.config(text=f"Downloading {display_name(choice['value'])}   "
                               f"{dl['done'] >> 20}/{dl['total'] >> 20} MB", fg=FG)
        elif dl["phase"] == "model":
            status.config(text=f"Loading {display_name(choice['value'])}…", fg=FG)
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
