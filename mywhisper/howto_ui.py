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

from .setup_ui import (ACCENT, BG, BTN_TEXT, CARD, CARD_ON, DIFF_ADD, DIFF_DEL,
                       FG, SUB)

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


def show_dictionary(app) -> None:
    """The dictionary table editor (words / replacements / snippets)."""
    _request("dictionary", app)


def show_diff(app, before: str, after: str, label: str = "Transform",
              mode: str = "confirm", timeout_s: float = 120.0) -> bool:
    """Show the change and block until the user accepts or rejects it.

    `mode="confirm"` gates an unapplied transform (Apply / Keep original).
    `mode="review"` inspects one that already landed (Close / Copy original).

    Called from a transform worker thread; the window is built on the UI
    thread. The `Event` is the handshake — without it the worker would paste
    before the user had looked. A timeout is included because a modal that can
    wedge a background thread forever is a bug waiting for a bad day; on
    timeout the answer is *no*, because silently applying an unreviewed rewrite
    is the outcome this whole feature exists to prevent.
    """
    decision = {"accept": False}
    done = threading.Event()
    _request("diff", app, before=before, after=after, label=label, mode=mode,
             decision=decision, done=done)
    if not done.wait(timeout_s):
        log.warning("diff preview timed out after %.0fs — treating as reject",
                    timeout_s)
        return False
    return bool(decision["accept"])


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
                    elif kind == "dictionary":
                        _build_dictionary(root, app)
                    elif kind == "diff":
                        _build_diff(root, app, **kw)
                except Exception:  # noqa: BLE001 — a broken window must not kill the thread
                    log.exception("%s window failed", kind)
                    # A blocked worker waiting on this window must be released,
                    # or the transform thread hangs for the whole timeout.
                    ev = kw.get("done")
                    if ev is not None:
                        ev.set()
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


def _diff_colors(app=None) -> tuple[str, str]:
    """(addition, deletion) — from the WINDOW's palette, not the overlay theme.

    This originally pulled each theme's `done` and `dot` colours, on the theory
    that borrowing the theme's own semantic colours would make the diff look
    native everywhere. It does the opposite. Those colours are chosen to sit on
    a theme's background — `minimal-dark`'s mint `#58d5a2` is tuned for
    `#101216` — and this window is not themed at all; it is the same warm cream
    card as History and Setup. Mint on cream measures **1.56:1**, which is not
    low contrast, it is invisible. The recording red managed 2.54:1.

    So the diff uses two inks from the palette the window actually belongs to
    (5.4:1 and 5.6:1 on CARD, both AA). One page, one set of inks.
    """
    return DIFF_ADD, DIFF_DEL


def _build_diff(root, app, before="", after="", label="Transform",
                mode="confirm", decision=None, done=None):
    """Review a rewrite before it replaces your text.

    Additions and deletions are shown inline in one flow (rather than
    side-by-side) because a transform is usually a light edit and the eye
    tracks a single column better at that density. Enter accepts, Esc rejects —
    the two keys that need no explanation.
    """
    import tkinter as tk

    from .transforms.diff import DELETE, EQUAL, INSERT, summarize, word_diff

    decision = decision if decision is not None else {}

    win = getattr(root, "_svara_diff", None)
    if win is not None and win.winfo_exists():
        win.destroy()
    win = tk.Toplevel(root)
    root._svara_diff = win
    _style_toplevel(win, f"Svara — {label}", 660, 480)

    add_fg, del_fg = _diff_colors(app)
    added, removed = summarize(before, after)

    head = tk.Frame(win, bg=BG)
    head.pack(fill="x", padx=18, pady=(16, 8))
    tk.Label(head, text=label.upper(), bg=BG, fg=SUB,
             font=("Segoe UI", 9, "bold")).pack(side="left")
    tk.Label(head, text=f"+{added}", bg=BG, fg=add_fg,
             font=("Segoe UI Semibold", 10)).pack(side="right")
    tk.Label(head, text=f"−{removed}  ", bg=BG, fg=del_fg,
             font=("Segoe UI Semibold", 10)).pack(side="right")

    # tk.Text asks for 24 lines by default — more than this window is tall —
    # so packing it before the footer let it claim every pixel and push the
    # Apply / Keep original buttons clean off the bottom edge. The window
    # rendered fine and was unusable by mouse.
    #
    # Two belts: an explicit height so the request can never exceed the window,
    # and the footer packed to the bottom FIRST so its space is reserved
    # whatever the body asks for.
    body = tk.Text(win, bg=CARD, fg=FG, relief="flat", bd=0, wrap="word",
                   font=("Segoe UI", 11), padx=14, pady=12, height=8,
                   insertbackground=ACCENT, cursor="arrow")
    body.tag_configure(INSERT, foreground=add_fg)
    body.tag_configure(DELETE, foreground=del_fg, overstrike=True)
    body.tag_configure(EQUAL, foreground=FG)
    for op, chunk in word_diff(before, after):
        body.insert("end", chunk, op)
    body.configure(state="disabled")

    def finish(accept: bool):
        decision["accept"] = accept
        if done is not None:
            done.set()
        try:
            win.destroy()
        except Exception:  # noqa: BLE001
            pass

    reviewing = mode == "review"
    hint = ("Enter to close · Esc to copy your original back"
            if reviewing else
            "Enter to apply · Esc to keep your original")
    accept_label = "Close" if reviewing else "Apply"
    reject_label = "Copy original" if reviewing else "Keep original"

    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x", padx=18, pady=(0, 16))
    body.pack(fill="both", expand=True, padx=18, pady=(0, 10))
    tk.Label(foot, text=hint, bg=BG, fg=SUB,
             font=("Segoe UI", 9)).pack(side="left")
    tk.Button(foot, text=reject_label, bg=CARD, fg=FG, bd=0, padx=16,
              pady=6, cursor="hand2", font=("Segoe UI", 9),
              command=lambda: finish(False)).pack(side="right", padx=(8, 0))
    tk.Button(foot, text=accept_label, bg=ACCENT, fg=BTN_TEXT, bd=0, padx=20,
              pady=6, cursor="hand2", font=("Segoe UI Semibold", 9),
              command=lambda: finish(True)).pack(side="right")

    win.bind("<Return>", lambda _e: finish(True))
    win.bind("<Escape>", lambda _e: finish(False))
    # Closing the window is a rejection, never an accept — and it must release
    # the waiting worker thread.
    win.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    win.focus_force()


def _build_dictionary(root, app):
    """The dictionary table editor — words, replacements, snippets, and CSV.

    Quick-add plus hand-edited YAML got Svara this far, but "teach it my
    vocabulary" is the highest-value thing a dictation user does and it should
    not require knowing what YAML is.
    """
    import tkinter as tk
    from tkinter import filedialog, ttk

    from .dictionary_io import (export_csv, import_csv, load_dictionary,
                                save_dictionary)

    win = getattr(root, "_svara_dict", None)
    if win is not None and win.winfo_exists():
        win.destroy()
    win = tk.Toplevel(root)
    root._svara_dict = win
    _style_toplevel(win, "Svara — Dictionary", 720, 560)

    data = load_dictionary()

    tk.Label(win, text="YOUR WORDS", bg=BG, fg=SUB,
             font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
    tk.Label(win, text="Names and jargon Svara should recognise, plus exact "
                       "fixes and spoken shortcuts. Changes apply immediately.",
             bg=BG, fg=SUB, font=("Segoe UI", 9), wraplength=660,
             justify="left").pack(anchor="w", padx=18, pady=(0, 10))

    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:  # noqa: BLE001
        pass
    style.configure("Svara.TNotebook", background=BG, borderwidth=0)
    style.configure("Svara.TNotebook.Tab", background=CARD, foreground=FG,
                    padding=(16, 7), borderwidth=0)
    style.map("Svara.TNotebook.Tab",
              background=[("selected", CARD_ON)],
              foreground=[("selected", ACCENT)])

    tabs = ttk.Notebook(win, style="Svara.TNotebook")
    tabs.pack(fill="both", expand=True, padx=18)

    def _list_tab(title: str, hint: str):
        frame = tk.Frame(tabs, bg=BG)
        tabs.add(frame, text=title)
        tk.Label(frame, text=hint, bg=BG, fg=SUB, font=("Segoe UI", 9),
                 wraplength=640, justify="left").pack(anchor="w", pady=(10, 6))
        box = tk.Listbox(frame, bg=CARD, fg=FG, relief="flat", bd=0,
                         font=("Consolas", 10), selectbackground=CARD_ON,
                         selectforeground=ACCENT, activestyle="none")
        box.pack(fill="both", expand=True, pady=(0, 8))
        return frame, box

    words_frame, words_box = _list_tab(
        "Words", "Boosted during recognition — Svara literally hears these "
                 "better. One per line.")
    repl_frame, repl_box = _list_tab(
        "Replacements", "Exact fixes applied after transcription: heard → typed.")
    snip_frame, snip_box = _list_tab(
        "Snippets", "Say the trigger, type the block: trigger → text.")

    def refresh():
        words_box.delete(0, "end")
        for w in data.get("words") or []:
            words_box.insert("end", w)
        repl_box.delete(0, "end")
        for heard, typed in (data.get("replacements") or {}).items():
            repl_box.insert("end", f"{heard}  →  {typed}")
        snip_box.delete(0, "end")
        for trigger, text in (data.get("snippets") or {}).items():
            snip_box.insert("end", f"{trigger}  →  {text!r}")

    def _add_row(frame, placeholder_a, placeholder_b, on_add):
        bar = tk.Frame(frame, bg=BG)
        bar.pack(fill="x", pady=(0, 10))
        a = tk.Entry(bar, bg=CARD, fg=FG, relief="flat", insertbackground=ACCENT,
                     font=("Segoe UI", 10))
        a.pack(side="left", fill="x", expand=True, ipady=4, ipadx=6)
        b = None
        if placeholder_b:
            tk.Label(bar, text="→", bg=BG, fg=SUB).pack(side="left", padx=8)
            b = tk.Entry(bar, bg=CARD, fg=FG, relief="flat",
                         insertbackground=ACCENT, font=("Segoe UI", 10))
            b.pack(side="left", fill="x", expand=True, ipady=4, ipadx=6)

        def add(*_):
            left = a.get().strip()
            right = b.get().strip() if b is not None else ""
            if not left or (b is not None and not right):
                return
            on_add(left, right)
            a.delete(0, "end")
            if b is not None:
                b.delete(0, "end")
            persist()

        a.bind("<Return>", add)
        if b is not None:
            b.bind("<Return>", add)
        tk.Button(bar, text="Add", bg=ACCENT, fg=BTN_TEXT, bd=0, padx=16,
                  pady=4, cursor="hand2", font=("Segoe UI Semibold", 9),
                  command=add).pack(side="right", padx=(8, 0))

    def persist():
        save_dictionary(data)
        app.reload_dictionary(quiet=True)
        refresh()

    def _delete(box, kind):
        sel = box.curselection()
        if not sel:
            return
        idx = sel[0]
        if kind == "words":
            words = list(data.get("words") or [])
            if idx < len(words):
                words.pop(idx)
                data["words"] = words
        else:
            keys = list((data.get(kind) or {}).keys())
            if idx < len(keys):
                data[kind].pop(keys[idx], None)
        persist()

    _add_row(words_frame, "word or phrase", None,
             lambda a, _b: data.setdefault("words", []).append(a))
    _add_row(repl_frame, "heard", "typed",
             lambda a, b: data.setdefault("replacements", {}).__setitem__(a, b))
    _add_row(snip_frame, "trigger", "text",
             lambda a, b: data.setdefault("snippets", {}).__setitem__(a, b))

    for box, kind in ((words_box, "words"), (repl_box, "replacements"),
                      (snip_box, "snippets")):
        box.bind("<Delete>", lambda _e, b=box, k=kind: _delete(b, k))

    foot = tk.Frame(win, bg=BG)
    foot.pack(fill="x", padx=18, pady=14)
    tk.Label(foot, text="Select a row and press Delete to remove it",
             bg=BG, fg=SUB, font=("Segoe UI", 9)).pack(side="left")

    def do_import():
        path = filedialog.askopenfilename(
            parent=win, title="Import dictionary CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        report = import_csv(path, data)
        save_dictionary(data)
        app.reload_dictionary(quiet=True)
        refresh()
        app._notify(report.summary())

    def do_export():
        path = filedialog.asksaveasfilename(
            parent=win, title="Export dictionary CSV", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")])
        if path:
            n = export_csv(path, data)
            app._notify(f"Exported {n} dictionary entries.")

    tk.Button(foot, text="Export CSV…", bg=CARD, fg=FG, bd=0, padx=14, pady=5,
              cursor="hand2", font=("Segoe UI", 9),
              command=do_export).pack(side="right", padx=(8, 0))
    tk.Button(foot, text="Import CSV…", bg=CARD, fg=FG, bd=0, padx=14, pady=5,
              cursor="hand2", font=("Segoe UI", 9),
              command=do_import).pack(side="right")
    refresh()


def _toggle_scratchpad(root, app):
    """The scratchpad: multiple notes, autosaved, with a version log.

    Every save records where the text came from — typed, dictated, or a
    transform. That provenance is the point: when a local model rewrites a
    note, you can see which version it replaced and go back. Toggles — the
    shortcut shows it when hidden, hides it when shown.
    """
    import time as _time
    import tkinter as tk
    from tkinter import simpledialog, ttk

    store = app.scratchpad

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
    _style_toplevel(win, "Svara — Scratchpad", 620, 520)

    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:  # noqa: BLE001
        pass
    style.configure("Scratch.TNotebook", background=BG, borderwidth=0)
    style.configure("Scratch.TNotebook.Tab", background=CARD, foreground=FG,
                    padding=(14, 6), borderwidth=0)
    style.map("Scratch.TNotebook.Tab", background=[("selected", CARD_ON)],
              foreground=[("selected", ACCENT)])

    # Footer first, bottom-anchored: the note editor is a tk.Text asking for 24
    # lines, which otherwise swallows the window and clips New note / History /
    # Rename / Delete off the bottom.
    foot = tk.Frame(win, bg=BG)
    foot.pack(side="bottom", fill="x", padx=14, pady=(0, 14))

    tabs = ttk.Notebook(win, style="Scratch.TNotebook")
    tabs.pack(fill="both", expand=True, padx=14, pady=(14, 6))

    editors: dict[str, tuple[int, tk.Text]] = {}
    save_job = [None]

    def save_current(*_):
        current = tabs.select()
        if not current or current not in editors:
            return
        note_id, widget = editors[current]
        store.save(note_id, widget.get("1.0", "end-1c"))

    def schedule_save(*_):
        if save_job[0]:
            try:
                win.after_cancel(save_job[0])
            except Exception:  # noqa: BLE001
                pass
        save_job[0] = win.after(800, save_current)

    def add_tab(note_id: int, title: str):
        frame = tk.Frame(tabs, bg=BG)
        widget = tk.Text(frame, bg=CARD, fg=FG, insertbackground=ACCENT,
                         relief="flat", font=("Segoe UI", 11), wrap="word",
                         padx=12, pady=10, undo=True, height=10)
        widget.pack(fill="both", expand=True)
        widget.insert("1.0", store.body(note_id))
        widget.bind("<KeyRelease>", schedule_save)
        tabs.add(frame, text=title)
        editors[str(frame)] = (note_id, widget)
        return frame

    for note_id, title, _updated in store.notes() or []:
        add_tab(note_id, title)
    if not editors:
        add_tab(store.ensure_one(), "Scratchpad")

    def new_note():
        save_current()
        note_id = store.create(f"Note {len(editors) + 1}")
        if note_id:
            frame = add_tab(note_id, f"Note {len(editors)}")
            tabs.select(frame)

    def rename_note():
        current = tabs.select()
        if current not in editors:
            return
        note_id, _ = editors[current]
        title = simpledialog.askstring("Rename note", "Tab name:", parent=win)
        if title:
            store.rename(note_id, title)
            tabs.tab(current, text=title)

    def delete_note():
        current = tabs.select()
        if current not in editors or len(editors) <= 1:
            app._notify("Keep at least one note.")
            return
        note_id, _ = editors.pop(current)
        store.delete(note_id)
        tabs.forget(current)

    def show_versions():
        save_current()
        current = tabs.select()
        if current not in editors:
            return
        note_id, widget = editors[current]
        rows = store.versions(note_id)
        if not rows:
            app._notify("No earlier versions of this note yet.")
            return
        picker = tk.Toplevel(win)
        _style_toplevel(picker, "Svara — Note history", 520, 380)
        tk.Label(picker, text="Every save, tagged with where the text came "
                              "from. Double-click to restore.",
                 bg=BG, fg=SUB, font=("Segoe UI", 9), wraplength=470,
                 justify="left").pack(anchor="w", padx=16, pady=(14, 8))
        box = tk.Listbox(picker, bg=CARD, fg=FG, relief="flat", bd=0,
                         font=("Segoe UI", 10), selectbackground=CARD_ON,
                         selectforeground=ACCENT, activestyle="none")
        box.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        for _vid, ts, source, body in rows:
            stamp = _time.strftime("%d %b %H:%M", _time.localtime(ts))
            preview = " ".join(body.split())[:60]
            box.insert("end", f"{stamp}  ·  {source:<9}  {preview}")

        def restore(*_):
            sel = box.curselection()
            if not sel:
                return
            version_id = rows[sel[0]][0]
            if store.restore(note_id, version_id):
                widget.delete("1.0", "end")
                widget.insert("1.0", store.body(note_id))
                picker.destroy()
                app._notify("Note restored.")

        box.bind("<Double-Button-1>", restore)

    for label, command in (("History…", show_versions), ("Rename", rename_note),
                           ("Delete", delete_note)):
        tk.Button(foot, text=label, bg=CARD, fg=FG, bd=0, padx=12, pady=5,
                  cursor="hand2", font=("Segoe UI", 9),
                  command=command).pack(side="right", padx=(8, 0))
    tk.Button(foot, text="New note", bg=ACCENT, fg=BTN_TEXT, bd=0, padx=14,
              pady=5, cursor="hand2", font=("Segoe UI Semibold", 9),
              command=new_note).pack(side="right", padx=(8, 0))
    tk.Label(foot, text="Autosaves as you type", bg=BG, fg=SUB,
             font=("Segoe UI", 9)).pack(side="left")

    tabs.bind("<<NotebookTabChanged>>", lambda _e: save_current())
    win.protocol("WM_DELETE_WINDOW", lambda: (save_current(), win.withdraw()))


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
