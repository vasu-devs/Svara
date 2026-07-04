"""The Svara window — how-to, live dictation test area, language picker.

Opened by the running app when:
  - the user double-clicks Svara.exe again (the doomed second copy signals us),
  - or from the tray menu ("How to use / Test").

One tk.Tk() root is created ONCE, lazily, on a dedicated persistent daemon
thread, and reused for the rest of the process — never a fresh Tk() per call.
Tcl's Windows notifier is not reliably safe to (re-)initialize repeatedly
across threads in a long-running process; creating a brand-new interpreter
every time this window was requested was intermittently producing a window
that showed (native title bar drawn by the OS) but never actually painted —
its message pump had silently failed to attach. Reusing one root for the
whole process lifetime removes the entire class of that failure: "close"
just withdraws the window, and it's redisplayed (rebuilt in place) on the
next request via a thread-safe queue.

The window never closes itself — only the user closes (hides) it.
"""

import logging
import queue
import threading

from .setup_ui import ACCENT, BG, BTN_TEXT, CARD, CARD_ON, FG, SUB

log = logging.getLogger(__name__)

# (whisper language code | None = auto-detect, label)
LANGS = [
    (None, "Auto-detect"),
    ("en", "English"),
    ("hi", "हिन्दी Hindi"),
    ("bn", "বাংলা Bengali"),
    ("ta", "தமிழ் Tamil"),
    ("te", "తెలుగు Telugu"),
    ("mr", "मराठी Marathi"),
    ("gu", "ગુજરાતી Gujarati"),
    ("ur", "اردو Urdu"),
    ("es", "Español"),
    ("fr", "Français"),
    ("de", "Deutsch"),
    ("pt", "Português"),
    ("it", "Italiano"),
    ("ru", "Русский"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("zh", "中文"),
    ("ar", "العربية"),
]

_queue: "queue.Queue[tuple]" = queue.Queue()
_thread_lock = threading.Lock()
_thread_started = False


def show_howto(app, first_run: bool = False) -> None:
    """Request the Svara how-to/test window be (re)shown.

    first_run=True is the post-setup "You're all set" welcome — same window,
    celebratory copy. The live test is the REAL pipeline: double-tap the
    hotkey and the pill overlay appears while words stream into the textbox.
    """
    global _thread_started
    with _thread_lock:
        if not _thread_started:
            _thread_started = True
            threading.Thread(target=_ui_main, daemon=True,
                             name="howto-ui").start()
    _queue.put((app, first_run))


def _ui_main():
    """The one persistent UI thread — one Tk root for the process lifetime."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()  # hidden until the first real request arrives

    def _poll():
        try:
            while True:
                app, first_run = _queue.get_nowait()
                try:
                    _build(root, app, first_run)
                except Exception:  # noqa: BLE001 — a broken window must not kill the thread
                    log.exception("how-to window failed")
        except queue.Empty:
            pass
        root.after(150, _poll)

    root.after(150, _poll)
    root.mainloop()


def _build(root, app, first_run=False):
    import tkinter as tk

    for w in root.winfo_children():
        w.destroy()

    cfg = app.cfg
    hk = cfg["recording"].get("hotkey", "right alt")

    root.title("Svara — You're all set" if first_run else "Svara")
    root.configure(bg=BG)
    W = 560
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    H = min(680, sh - 90)
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - 20)}")
    root.minsize(480, 520)
    root.deiconify()
    try:
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        root.after(900, lambda: root.attributes("-topmost", False))
    except Exception:  # noqa: BLE001
        pass
    try:
        from .setup_ui import _asset
        ic = _asset("icon.ico")
        if ic:
            root.iconbitmap(ic)
    except Exception:  # noqa: BLE001
        pass

    # --- animated strings banner (same look as setup) ---
    banner = None
    try:
        from PIL import ImageTk

        from .setup_ui import _make_wave_frames
        frames = [ImageTk.PhotoImage(f, master=root)
                  for f in _make_wave_frames(W - 52, 44, 24)]
        banner = tk.Label(root, image=frames[0], bg=BG, bd=0)
        banner._frames = frames  # keep references alive
        banner.pack(fill="x", padx=26, pady=(18, 4))
        idx = [0]

        def _anim():
            if not banner.winfo_exists():
                return
            idx[0] = (idx[0] + 1) % len(frames)
            banner.configure(image=frames[idx[0]])
            root.after(70, _anim)

        root.after(200, _anim)
    except Exception:  # noqa: BLE001
        pass

    tk.Label(root, text="You're all set ✓" if first_run else "Svara is running",
             bg=BG, fg=FG, font=("Segoe UI Semibold", 20), anchor="w"
             ).pack(fill="x", padx=26)
    tk.Label(root, text=("Try it right here — your words stream in live while "
                         "the pill hovers on screen." if first_run else
                         "It types wherever your cursor is — in any app."),
             bg=BG, fg=SUB, font=("Segoe UI", 11), anchor="w"
             ).pack(fill="x", padx=26, pady=(0, 10))

    steps = tk.Frame(root, bg=CARD)
    steps.pack(fill="x", padx=26)
    for n, a, b in ((" 1 ", "Double-tap", f"{hk}  — Svara starts listening"),
                    (" 2 ", "Speak", "your words type at the cursor"),
                    (" 3 ", "Tap", f"{hk}  again to finish   ·   hold it = "
                                   "push-to-talk   ·   quick tap = cancel")):
        row = tk.Frame(steps, bg=CARD)
        row.pack(fill="x", padx=14, pady=5)
        tk.Label(row, text=n + a, bg=CARD, fg=ACCENT,
                 font=("Segoe UI Semibold", 11)).pack(side="left")
        tk.Label(row, text="  " + b, bg=CARD, fg=FG,
                 font=("Segoe UI", 11)).pack(side="left")

    # --- language picker (applies live, persists) ---
    lrow = tk.Frame(root, bg=BG)
    lrow.pack(fill="x", padx=26, pady=(12, 0))
    tk.Label(lrow, text="Language", bg=BG, fg=SUB,
             font=("Segoe UI", 9, "bold")).pack(side="left")
    if getattr(app, "is_multilingual", True):
        cur = app.current_language
        labels = {code: label for code, label in LANGS}
        var = tk.StringVar(value=labels.get(cur, "Auto-detect"))

        def _pick(label):
            code = next((c for c, lbl in LANGS if lbl == label), None)
            app.set_language(code)

        opt = tk.OptionMenu(lrow, var, *[lbl for _c, lbl in LANGS], command=_pick)
        opt.configure(bg=CARD, fg=FG, activebackground=CARD,
                      activeforeground=ACCENT, highlightthickness=0, bd=0,
                      font=("Segoe UI", 10), indicatoron=True)
        opt["menu"].configure(bg=CARD, fg=FG, activebackground=CARD_ON,
                              activeforeground=ACCENT, bd=0)
        opt.pack(side="left", padx=(10, 0))
        tk.Label(lrow, text="Auto-detect just works — pick one to lock it.",
                 bg=BG, fg=SUB, font=("Segoe UI", 9)).pack(side="left",
                                                           padx=(10, 0))
    else:
        tk.Label(lrow, text="English (this model is English-tuned — switch to "
                            "the multilingual model in the tray for more)",
                 bg=BG, fg=SUB, font=("Segoe UI", 9)).pack(side="left",
                                                           padx=(10, 0))

    # --- live test area ---
    tk.Label(root, text=f"TRY IT — click below, double-tap  {hk} , and speak",
             bg=BG, fg=SUB, font=("Segoe UI", 9, "bold"), anchor="w"
             ).pack(fill="x", padx=26, pady=(14, 4))
    box = tk.Text(root, bg=CARD, fg=FG, insertbackground=ACCENT,
                  relief="flat", font=("Segoe UI", 12), wrap="word",
                  padx=12, pady=10, height=6)
    box.pack(fill="both", expand=True, padx=26)

    foot = tk.Frame(root, bg=BG)
    foot.pack(fill="x", padx=26, pady=(10, 16))
    tk.Label(foot, text=f"Model: {app.model_label}   ·   themes, pause and quit "
                        "live in the tray icon (near the clock)",
             bg=BG, fg=SUB, font=("Segoe UI", 9), anchor="w",
             wraplength=W - 150, justify="left").pack(side="left", fill="x",
                                                      expand=True)
    tk.Button(foot, text="Finish  →" if first_run else "Close",
              bg=ACCENT, fg=BTN_TEXT,
              font=("Segoe UI Semibold", 10), bd=0, padx=22, pady=7,
              cursor="hand2", command=root.withdraw).pack(side="right")

    box.focus_set()
    root.protocol("WM_DELETE_WINDOW", root.withdraw)  # hide, not destroy — reused next time
