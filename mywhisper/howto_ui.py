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


def _request(kind: str, app, **kw) -> None:
    global _thread_started
    with _thread_lock:
        if not _thread_started:
            _thread_started = True
            threading.Thread(target=_ui_main, daemon=True,
                             name="howto-ui").start()
    _queue.put((kind, app, kw))


def show_howto(app, first_run: bool = False) -> None:
    """Request the Svara how-to/test window be (re)shown.

    first_run=True is the post-setup "You're all set" welcome — same window,
    celebratory copy. The live test is the REAL pipeline: double-tap the
    hotkey and the pill overlay appears while words stream into the textbox.
    """
    _request("howto", app, first_run=first_run)


def show_history(app) -> None:
    """The dictation history browser (search / copy / clear)."""
    _request("history", app)


def show_scratchpad(app) -> None:
    """The scratchpad note window (toggle: shows if hidden, hides if shown)."""
    _request("scratchpad", app)


def _ui_main():
    """The one persistent UI thread — one Tk root for the process lifetime.
    All Svara windows (how-to, history, scratchpad) are Toplevels served by
    this root, requested through the queue from any thread."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()  # hidden until the first real request arrives

    def _poll():
        try:
            while True:
                kind, app, kw = _queue.get_nowait()
                try:
                    if kind == "howto":
                        _build(root, app, kw.get("first_run", False))
                    elif kind == "history":
                        _build_history(root, app)
                    elif kind == "scratchpad":
                        _toggle_scratchpad(root, app)
                except Exception:  # noqa: BLE001 — a broken window must not kill the thread
                    log.exception("%s window failed", kind)
        except queue.Empty:
            pass
        root.after(150, _poll)

    root.after(150, _poll)
    root.mainloop()


def _style_toplevel(win, title: str, w: int, h: int):
    import tkinter as tk  # noqa: F401
    win.title(title)
    win.configure(bg=BG)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 2)}")
    try:
        from .setup_ui import _asset
        ic = _asset("icon.ico")
        if ic:
            win.iconbitmap(ic)
    except Exception:  # noqa: BLE001
        pass
    try:
        win.attributes("-topmost", True)
        win.lift()
        win.after(900, lambda: win.attributes("-topmost", False))
    except Exception:  # noqa: BLE001
        pass


def _build_history(root, app):
    """Search + browse everything Svara typed; copy any entry back out."""
    import time as _time
    import tkinter as tk

    win = getattr(root, "_svara_history", None)
    if win is not None and win.winfo_exists():
        win.destroy()  # rebuild fresh — cheap, and rows may have changed
    win = tk.Toplevel(root)
    root._svara_history = win
    _style_toplevel(win, "Svara — History", 640, 520)

    top = tk.Frame(win, bg=BG)
    top.pack(fill="x", padx=16, pady=(14, 6))
    tk.Label(top, text="HISTORY", bg=BG, fg=SUB,
             font=("Segoe UI", 9, "bold")).pack(side="left")
    q_var = tk.StringVar()
    q_entry = tk.Entry(top, textvariable=q_var, bg=CARD, fg=FG, relief="flat",
                       insertbackground=ACCENT, font=("Segoe UI", 10))
    q_entry.pack(side="right", fill="x", expand=True, padx=(12, 0),
                 ipady=4, ipadx=6)

    box = tk.Listbox(win, bg=CARD, fg=FG, relief="flat", bd=0,
                     font=("Segoe UI", 10), selectbackground=CARD_ON,
                     selectforeground=ACCENT, activestyle="none")
    box.pack(fill="both", expand=True, padx=16, pady=(4, 6))
    rows: list[str] = []  # full texts aligned with listbox indexes

    def refresh(*_):
        box.delete(0, "end")
        rows.clear()
        for ts, app_name, kind, text in app.history.recent(
                200, q_var.get().strip() or None):
            stamp = _time.strftime("%d %b %H:%M", _time.localtime(ts))
            tag = f" · {kind}" if kind != "dictation" else ""
            src = f" · {app_name}" if app_name else ""
            preview = text if len(text) <= 90 else text[:87] + "…"
            box.insert("end", f"{stamp}{src}{tag}   {preview}")
            rows.append(text)
        if not rows:
            box.insert("end", "(nothing here yet — dictate something!)")

    q_var.trace_add("write", refresh)

    def copy_selected(*_):
        sel = box.curselection()
        if sel and sel[0] < len(rows):
            from .injector import _clipboard_set
            _clipboard_set(rows[sel[0]])
            app._notify("Copied to clipboard.")

    box.bind("<Double-Button-1>", copy_selected)

    foot = tk.Frame(win, bg=BG)
    foot.pack(fill="x", padx=16, pady=(0, 14))
    tk.Label(foot, text="Double-click a row to copy it",
             bg=BG, fg=SUB, font=("Segoe UI", 9)).pack(side="left")
    tk.Button(foot, text="Clear history", bg=CARD, fg=FG, bd=0, padx=14,
              pady=5, cursor="hand2", font=("Segoe UI", 9),
              command=lambda: (app.history.clear(), refresh())
              ).pack(side="right", padx=(8, 0))
    tk.Button(foot, text="Copy selected", bg=ACCENT, fg=BTN_TEXT, bd=0,
              padx=14, pady=5, cursor="hand2",
              font=("Segoe UI Semibold", 9),
              command=copy_selected).pack(side="right")
    refresh()


def _toggle_scratchpad(root, app):
    """A tiny always-available notepad — dictate into it, keep snippets.
    Toggles: the shortcut shows it when hidden, hides it when shown.
    Content autosaves to scratchpad.txt next to the config."""
    import tkinter as tk

    from .paths import base_dir
    path = base_dir() / "scratchpad.txt"

    win = getattr(root, "_svara_scratch", None)
    if win is not None and win.winfo_exists():
        if win.state() == "withdrawn":
            win.deiconify()
            win.lift()
        else:
            win.withdraw()
        return
    win = tk.Toplevel(root)
    root._svara_scratch = win
    _style_toplevel(win, "Svara — Scratchpad", 460, 420)

    text = tk.Text(win, bg=CARD, fg=FG, insertbackground=ACCENT,
                   relief="flat", font=("Segoe UI", 11), wrap="word",
                   padx=12, pady=10, undo=True)
    text.pack(fill="both", expand=True, padx=14, pady=14)
    try:
        if path.is_file():
            text.insert("1.0", path.read_text(encoding="utf-8"))
    except OSError:
        pass

    save_job = [None]

    def save(*_):
        try:
            path.write_text(text.get("1.0", "end-1c"), encoding="utf-8")
        except OSError:
            log.debug("scratchpad save failed", exc_info=True)

    def schedule_save(*_):
        if save_job[0]:
            win.after_cancel(save_job[0])
        save_job[0] = win.after(800, save)

    text.bind("<KeyRelease>", schedule_save)
    win.protocol("WM_DELETE_WINDOW", lambda: (save(), win.withdraw()))
    text.focus_set()


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
    H = min(760, sh - 90)
    root.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - 20)}")
    root.minsize(480, 600)
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

    # --- settings: everything the tray offers, also reachable right here —
    # this window (opened by double-clicking Svara.exe again) is how most
    # people actually find their way back in, so "change my model" must not
    # require ever discovering the tray icon. ---
    settings = tk.Frame(root, bg=BG)
    settings.pack(fill="x", padx=26, pady=(12, 0))

    def _dropdown_row(parent, label_text, options, current, on_pick, hint=None):
        """A labeled OptionMenu row, styled like the rest of this window.
        options: [(value, label), ...]. current: the value to preselect."""
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label_text, bg=BG, fg=SUB, width=9, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        labels = {v: lbl for v, lbl in options}
        var = tk.StringVar(value=labels.get(current, options[0][1]))

        def _pick(label):
            value = next((v for v, lbl in options if lbl == label), None)
            on_pick(value)

        opt = tk.OptionMenu(row, var, *[lbl for _v, lbl in options], command=_pick)
        opt.configure(bg=CARD, fg=FG, activebackground=CARD,
                      activeforeground=ACCENT, highlightthickness=0, bd=0,
                      font=("Segoe UI", 10), indicatoron=True)
        opt["menu"].configure(bg=CARD, fg=FG, activebackground=CARD_ON,
                              activeforeground=ACCENT, bd=0)
        opt.pack(side="left", padx=(10, 0))
        if hint:
            tk.Label(row, text=hint, bg=BG, fg=SUB,
                     font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        return var

    from .setup_ui import _CPU_OK, MODELS

    # Model/Device switches run in a background thread (app.py) — the
    # Language row (and the Device row's own value) can go stale for the
    # whole switch otherwise, since nothing here would know it settled.
    # app._model_switch flips True synchronously before the thread starts,
    # so polling it is a reliable "has it finished yet" signal; once it
    # clears, rebuild the window fresh (same path show_howto() itself
    # uses) so every row reflects the model that's now actually running.
    def _watch_switch_and_refresh():
        if not root.winfo_exists():
            return
        if getattr(app, "_model_switch", False):
            root.after(400, _watch_switch_and_refresh)
        elif root.state() != "withdrawn":
            # Only rebuild if the user hasn't already closed this window —
            # forcing it back open just to show settled state would be its
            # own annoyance. The next real show_howto() call rebuilds fresh
            # regardless, so a closed window never actually shows stale data.
            _build(root, app, first_run=False)

    def _pick_model(value):
        app.set_model(value)
        _watch_switch_and_refresh()

    def _pick_device(value):
        app.set_device(value)
        _watch_switch_and_refresh()

    # Same rule as the tray and first-run setup: don't offer a GPU-only
    # model on a machine with no GPU to run it on — it would silently
    # load on CPU instead (tens of seconds per utterance).
    offered_models = MODELS if getattr(app, "gpu_available", False) else [
        m for m in MODELS if m[0] in _CPU_OK]
    _dropdown_row(
        settings, "Model",
        [(value, name) for value, name, _sub in offered_models],
        cfg["model"]["name"], _pick_model)

    device_opts = [("cpu", "CPU")]
    if getattr(app, "gpu_available", False):
        device_opts.append(("cuda", "GPU (NVIDIA)"))
    _dropdown_row(settings, "Device", device_opts,
                 app.transcriber.device_used, _pick_device)

    _dropdown_row(
        settings, "Streaming",
        [("live", "Live"), ("preview", "Preview"), ("off", "Off")],
        cfg["streaming"]["mode"], app.set_streaming_mode)

    HOTKEYS = [("right alt", "Right Alt"), ("right ctrl", "Right Ctrl"),
               ("f8", "F8"), ("caps lock", "Caps Lock"),
               ("scroll lock", "Scroll Lock"), ("pause", "Pause"),
               ("num 0", "Numpad 0"), ("ctrl+win", "Ctrl+Win"),
               ("ctrl+shift+space", "Ctrl+Shift+Space")]
    cur_hk = cfg["recording"].get("hotkey", "right alt")
    if not any(v == cur_hk for v, _ in HOTKEYS):
        HOTKEYS.insert(0, (cur_hk, cur_hk))  # custom key from config stays offered
    _dropdown_row(settings, "Hotkey", HOTKEYS, cur_hk,
                 lambda v: (app.set_hotkey(v),
                            root.after(200, lambda: _build(root, app))),
                 hint="switches instantly — no restart")

    if getattr(app, "is_multilingual", True):
        cur = app.current_language
        _dropdown_row(settings, "Language", LANGS, cur, app.set_language,
                     hint="auto-detect just works — pick one to lock it")
    else:
        row = tk.Frame(settings, bg=BG)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Language", bg=BG, fg=SUB, width=9, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(row, text="English (this model is English-tuned — pick "
                          "\"Large v3 Turbo\" above for 90+ languages)",
                 bg=BG, fg=SUB, font=("Segoe UI", 9)).pack(side="left",
                                                           padx=(10, 0))

    # --- quick-add to the personal dictionary: names/jargon Svara mishears —
    # the single highest-leverage accuracy fix a user can make. ---
    row = tk.Frame(settings, bg=BG)
    row.pack(fill="x", pady=3)
    tk.Label(row, text="Dictionary", bg=BG, fg=SUB, width=9, anchor="w",
             font=("Segoe UI", 9, "bold")).pack(side="left")
    word_var = tk.StringVar()
    word_entry = tk.Entry(row, textvariable=word_var, bg=CARD, fg=FG,
                          relief="flat", insertbackground=ACCENT,
                          font=("Segoe UI", 10), width=22)
    word_entry.pack(side="left", padx=(10, 0), ipady=3, ipadx=6)

    def _add_word(*_):
        w = word_var.get().strip()
        if w:
            app.add_dictionary_word(w)
            word_var.set("")

    word_entry.bind("<Return>", _add_word)
    tk.Button(row, text="Add word", bg=CARD, fg=ACCENT, bd=0, padx=10, pady=3,
              cursor="hand2", font=("Segoe UI", 9), command=_add_word
              ).pack(side="left", padx=(6, 0))
    tk.Label(row, text="a name Svara mishears? add it",
             bg=BG, fg=SUB, font=("Segoe UI", 9)).pack(side="left",
                                                       padx=(10, 0))

    # --- start with Windows: THE reliability setting. Svara only feels
    # dependable if the hotkey works after every reboot without the user
    # ever re-launching the exe — surface the switch where they'll see it. ---
    import sys as _sys
    if getattr(_sys, "frozen", False):
        row = tk.Frame(settings, bg=BG)
        row.pack(fill="x", pady=3)
        tk.Label(row, text="Startup", bg=BG, fg=SUB, width=9, anchor="w",
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        auto_var = tk.BooleanVar(value=bool(getattr(app, "autostart_enabled",
                                                    False)))

        def _toggle_autostart():
            app.toggle_autostart()
            auto_var.set(bool(getattr(app, "autostart_enabled", False)))

        tk.Checkbutton(
            row, text="Start Svara when Windows starts  (recommended)",
            variable=auto_var, command=_toggle_autostart,
            bg=BG, fg=FG, activebackground=BG, activeforeground=ACCENT,
            selectcolor=CARD, font=("Segoe UI", 10), bd=0,
            highlightthickness=0, cursor="hand2",
        ).pack(side="left", padx=(10, 0))

    # --- live test area ---
    tk.Label(root, text=f"TRY IT — click below, double-tap  {hk} , and speak",
             bg=BG, fg=SUB, font=("Segoe UI", 9, "bold"), anchor="w"
             ).pack(fill="x", padx=26, pady=(14, 4))
    box = tk.Text(root, bg=CARD, fg=FG, insertbackground=ACCENT,
                  relief="flat", font=("Segoe UI", 12), wrap="word",
                  padx=12, pady=10, height=4)
    box.pack(fill="both", expand=True, padx=26)

    foot = tk.Frame(root, bg=BG)
    foot.pack(fill="x", padx=26, pady=(10, 16))
    from . import __version__
    tk.Label(foot, text=f"Svara v{__version__}  ·  {app.model_label}  ·  "
                        "more in the tray icon (near the clock)",
             bg=BG, fg=SUB, font=("Segoe UI", 9), anchor="w",
             wraplength=W - 150, justify="left").pack(side="left", fill="x",
                                                      expand=True)
    tk.Button(foot, text="Finish  →" if first_run else "Close",
              bg=ACCENT, fg=BTN_TEXT,
              font=("Segoe UI Semibold", 10), bd=0, padx=22, pady=7,
              cursor="hand2", command=root.withdraw).pack(side="right")

    box.focus_set()
    root.protocol("WM_DELETE_WINDOW", root.withdraw)  # hide, not destroy — reused next time
