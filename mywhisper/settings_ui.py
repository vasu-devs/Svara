"""The Svara settings window.

Everything you can change lives here, in sections, with the control column
aligned so nothing wanders. It replaces the old arrangement, which was a status
window with five settings squeezed underneath a tutorial - against a config
file with well over a hundred keys, most of them reachable only by editing
YAML.

Design notes, because they are decisions and not accidents:

- **Ink on paper.** Same palette as the setup window and the site: paper,
  a cream card, one sienna accent. No second accent anywhere.
- **Three type roles.** Georgia sets the section titles, because the product is
  named for a musical note and the site already speaks in serif; Segoe UI does
  the work; Consolas carries keys, model ids and anything the user might type
  or copy, where fixed width is information rather than styling.
- **Label and description left, control right, one aligned column.** The old
  window put controls immediately after their labels, so five differently-sized
  dropdowns produced five different left edges and the hints beside them
  wrapped into the window frame. An aligned column cannot do that.
- **The active section is the one flourish**: a sienna rule and Georgia italic.
  Everything else stays quiet. A settings window that shows off is a bad
  settings window.

Every control drives a live setter on the app - the model actually switches,
the hotkey actually rebinds - so nothing here writes a config file and asks you
to restart, except where it genuinely must, and then it says so.
"""

import logging
import sys

from .setup_ui import ACCENT, BG, BTN_TEXT, CARD, CARD_ON, ERROR, FG, SUB

log = logging.getLogger(__name__)

DISPLAY = "Georgia"     # section titles, and the active nav item
UI = "Segoe UI"         # everything you read and click
MONO = "Consolas"       # keys, model ids, paths — fixed width is information

LANGUAGES = [
    (None, "Auto-detect"), ("en", "English"), ("hi", "Hindi"),
    ("es", "Spanish"), ("fr", "French"), ("de", "German"), ("pt", "Portuguese"),
    ("it", "Italian"), ("ru", "Russian"), ("ja", "Japanese"), ("ko", "Korean"),
    ("zh", "Chinese"), ("ar", "Arabic"), ("bn", "Bengali"), ("ta", "Tamil"),
    ("te", "Telugu"), ("mr", "Marathi"), ("gu", "Gujarati"), ("ur", "Urdu"),
]

ENGLISH_VARIANTS = [
    ("en-US", "American — color, organize"),
    ("en-GB", "British — colour, organise"),
    ("en-CA", "Canadian — colour, organize"),
    ("en-AU", "Australian — colour, organise"),
    ("en-IN", "Indian — colour, organise"),
]

CLEANUP_LEVELS = [
    ("none", "Off — exactly what you said"),
    ("light", "Light — drop um and uh"),
    ("medium", "Medium — also fix “scratch that”"),
    ("high", "High — rewrite with your local AI"),
]

STREAMING_MODES = [
    ("live", "Type as I speak"),
    ("preview", "Show in the pill, type at the end"),
    ("off", "Type everything at the end"),
]

ROMANIZE_MODES = [
    ("never", "Off — keep Devanagari"),
    ("auto", "In chat and terminals"),
    ("always", "Always"),
]

HOTKEYS = ["right alt", "right ctrl", "caps lock", "f8", "f9", "scroll lock",
           "pause", "num 0", "ctrl+shift+space", "ctrl+win", "alt+v"]


def show_settings(app) -> None:
    """Open (or raise) the settings window. Routed through howto_ui's single
    Tk root — see the note there about never creating a second interpreter."""
    from .howto_ui import _request
    _request("settings", app)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def _style(win):
    """One ttk theme for the whole window. `clam` is the only built-in theme
    that honours background colours on Windows."""
    from tkinter import ttk
    st = ttk.Style(win)
    try:
        st.theme_use("clam")
    except Exception:  # noqa: BLE001
        pass
    st.configure("S.TCombobox", fieldbackground=CARD, background=CARD,
                 foreground=FG, arrowcolor=SUB, bordercolor=CARD_ON,
                 lightcolor=CARD, darkcolor=CARD, relief="flat", padding=5)
    st.map("S.TCombobox",
           fieldbackground=[("readonly", CARD)],
           foreground=[("readonly", FG)],
           bordercolor=[("focus", ACCENT)])
    st.configure("S.Vertical.TScrollbar", background=CARD_ON, troughcolor=BG,
                 bordercolor=BG, arrowcolor=SUB, relief="flat")
    return st


class Section:
    """A titled group of rows with an aligned control column."""

    def __init__(self, parent, title: str, blurb: str = ""):
        import tkinter as tk
        self.frame = tk.Frame(parent, bg=BG)
        self.frame.columnconfigure(0, weight=1)   # label + description
        self.frame.columnconfigure(1, minsize=250)  # the control column
        self._row = 0

        tk.Label(self.frame, text=title, bg=BG, fg=FG,
                 font=(DISPLAY, 19), anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self._row = 1
        if blurb:
            tk.Label(self.frame, text=blurb, bg=BG, fg=SUB, font=(UI, 10),
                     anchor="w", justify="left", wraplength=520).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))
            self._row = 2

    def rule(self):
        import tkinter as tk
        tk.Frame(self.frame, bg=CARD_ON, height=1).grid(
            row=self._row, column=0, columnspan=2, sticky="ew", pady=(6, 12))
        self._row += 1

    def row(self, label: str, description: str = "", mono: bool = False):
        """Returns the cell the caller puts a control into. Label and
        description stack on the left; the control sits in a fixed-width right
        column so every control on the page shares one edge."""
        import tkinter as tk
        left = tk.Frame(self.frame, bg=BG)
        left.grid(row=self._row, column=0, sticky="w", pady=(0, 14))
        tk.Label(left, text=label, bg=BG, fg=FG,
                 font=(MONO if mono else UI, 10, "bold" if not mono else "normal"),
                 anchor="w").pack(anchor="w")
        if description:
            tk.Label(left, text=description, bg=BG, fg=SUB, font=(UI, 9),
                     anchor="w", justify="left", wraplength=316).pack(anchor="w")
        cell = tk.Frame(self.frame, bg=BG)
        cell.grid(row=self._row, column=1, sticky="ne", pady=(0, 14))
        self._row += 1
        return cell

    def full(self):
        """A row spanning both columns, for things that need the width."""
        import tkinter as tk
        cell = tk.Frame(self.frame, bg=BG)
        cell.grid(row=self._row, column=0, columnspan=2, sticky="ew",
                  pady=(0, 14))
        self._row += 1
        return cell


def _combo(cell, values, current, on_pick, width=22):
    """A read-only combobox. Read-only because every one of these is a choice
    from a known set — a free-text field would invite a typo that silently
    does nothing."""
    import tkinter as tk
    from tkinter import ttk

    labels = [label for _v, label in values]
    var = tk.StringVar(value=next((lb for v, lb in values if v == current),
                                  labels[0] if labels else ""))
    box = ttk.Combobox(cell, values=labels, textvariable=var, state="readonly",
                       style="S.TCombobox", width=width, font=(UI, 10))
    box.pack(anchor="e")

    def picked(_e=None):
        for value, label in values:
            if label == var.get():
                on_pick(value)
                return

    box.bind("<<ComboboxSelected>>", picked)
    return box


def _switch(cell, text, get, toggle, warn: str = ""):
    """A checkbox that reads its state from the app, so it can never disagree
    with reality the way the old Startup box did."""
    import tkinter as tk
    var = tk.BooleanVar(value=bool(get()))

    def flip():
        toggle(bool(var.get()))
        var.set(bool(get()))          # re-read: the app has the last word

    tk.Checkbutton(cell, text=text, variable=var, command=flip, bg=BG, fg=FG,
                   activebackground=BG, activeforeground=ACCENT,
                   selectcolor=CARD, font=(UI, 10), bd=0, highlightthickness=0,
                   cursor="hand2", anchor="e").pack(anchor="e")
    if warn:
        tk.Label(cell, text=warn, bg=BG, fg=ERROR, font=(UI, 8),
                 wraplength=220, justify="right").pack(anchor="e")
    return var


def _button(cell, text, command, primary=False):
    import tkinter as tk
    return tk.Button(
        cell, text=text, command=command,
        bg=ACCENT if primary else CARD, fg=BTN_TEXT if primary else FG,
        activebackground=ACCENT if primary else CARD_ON,
        activeforeground=BTN_TEXT if primary else FG,
        bd=0, padx=14, pady=5, cursor="hand2",
        font=(UI, 9, "bold" if primary else "normal"))


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _speech(parent, app):
    from .setup_ui import MODELS, _CPU_OK

    s = Section(parent, "Speech",
                "Which model listens, what it runs on, and how quickly words "
                "reach your cursor.")

    offered = MODELS if app.gpu_available else [m for m in MODELS if m[0] in _CPU_OK]
    _combo(s.row("Model", "Bigger models are more accurate and slower. "
                          "Switching downloads it once, then works offline."),
           [(value, name) for value, name, _sub in offered],
           app.cfg["model"]["name"], app.set_model)

    devices = [("cpu", "CPU")]
    if app.gpu_available:
        devices.append(("cuda", "GPU (NVIDIA)"))
    _combo(s.row("Runs on", "Your GPU is several times faster. The first "
                            "switch downloads GPU support once."),
           devices, app.transcriber.device_used, app.set_device)

    if app.is_multilingual:
        _combo(s.row("Language", "Auto-detect works well. Pick one to lock it "
                                 "if you only dictate in that language."),
               LANGUAGES, app.current_language, app.set_language)

    _combo(s.row("Words appear", "Live typing shows words about a second "
                                 "behind you. Terminals always wait for the end."),
           STREAMING_MODES, app.cfg["streaming"]["mode"], app.set_streaming_mode)

    _switch(s.row("Whisper mode", "Boosts a quiet voice, for dictating late at "
                                  "night or in an open office."),
            "Boost quiet speech",
            lambda: app.whisper_mode, lambda _v: app.toggle_whisper_mode())
    return s.frame


def _writing(parent, app):
    s = Section(parent, "Writing",
                "How your words are cleaned up and spelled once they have been "
                "heard.")

    _combo(s.row("Clean-up", "Higher settings tidy more. High uses your own "
                             "local AI, if one is running."),
           CLEANUP_LEVELS, app.cleanup.level, app.set_cleanup_level)

    _combo(s.row("English spelling", "Canadian is British spelling with "
                                     "American -ize, which is correct."),
           ENGLISH_VARIANTS, app.english_variant, app.set_english_variant)

    _combo(s.row("Hindi in Latin script",
                 "Writes Hindi as kya haal hai rather than in Devanagari. "
                 "English words are left alone."),
           ROMANIZE_MODES, app.romanize_mode, app.set_romanize)
    return s.frame


def _words(parent, app):
    import tkinter as tk

    s = Section(parent, "Your words",
                "Names and jargon Svara should recognise, fixes for words it "
                "gets wrong, and shortcuts that expand as you speak.")

    cell = s.row("Add a word", "Names, products, anything unusual. Svara hears "
                               "these better straight away.")
    box = tk.Frame(cell, bg=BG)
    box.pack(anchor="e")
    entry = tk.Entry(box, bg=CARD, fg=FG, relief="flat", width=16,
                     insertbackground=ACCENT, font=(UI, 10))
    entry.pack(side="left", ipady=4, ipadx=6)

    def add(_e=None):
        word = entry.get().strip()
        if word:
            app.add_dictionary_word(word)
            entry.delete(0, "end")

    entry.bind("<Return>", add)
    _button(box, "Add", add, primary=True).pack(side="left", padx=(6, 0))

    _button(s.row("Everything else", "Fixes, snippets and bulk import live in "
                                     "the full editor."),
            "Open word editor", app.show_dictionary).pack(anchor="e")

    _button(s.row("History", "Everything Svara has typed, searchable, on this "
                             "machine only."),
            "Open history", app.show_history).pack(anchor="e")
    return s.frame


def _shortcuts(parent, app):
    import tkinter as tk

    s = Section(parent, "Shortcuts",
                "The dictation key, and the chords for everything else.")

    _combo(s.row("Dictation key", "Double-tap to start, tap to finish. Hold to "
                                  "push-to-talk. Changes apply instantly."),
           [(k, k) for k in HOTKEYS], app.cfg["recording"]["hotkey"],
           app.set_hotkey)

    cell = s.full()
    tk.Label(cell, text="Also available", bg=BG, fg=FG, font=(UI, 10, "bold"),
             anchor="w").pack(anchor="w", pady=(0, 8))
    grid = tk.Frame(cell, bg=BG)
    grid.pack(fill="x")
    sc = app.cfg.get("shortcuts") or {}
    pairs = [(sc.get("paste_last"), "Paste the last dictation again"),
             (sc.get("copy_last"), "Copy the last dictation"),
             (sc.get("polish"), "Rewrite the selected text"),
             (sc.get("view_diff"), "See what the last rewrite changed"),
             (sc.get("scratchpad"), "Open the scratchpad")]
    for i, (combo, what) in enumerate([p for p in pairs if p[0]]):
        pretty = (str(combo).replace("<cmd>", "Win").replace("<alt>", "Alt")
                  .replace("<shift>", "Shift").replace("<ctrl>", "Ctrl")
                  .replace("+", " + "))
        tk.Label(grid, text=pretty, bg=BG, fg=ACCENT, font=(MONO, 9),
                 anchor="w").grid(row=i, column=0, sticky="w", padx=(0, 16),
                                  pady=1)
        tk.Label(grid, text=what, bg=BG, fg=SUB, font=(UI, 9),
                 anchor="w").grid(row=i, column=1, sticky="w", pady=1)
    return s.frame


def _privacy(parent, app):
    s = Section(parent, "Privacy",
                "Nothing you say leaves this machine. The three settings below "
                "are off because they read more than your voice. Turn one on "
                "only if you want what it does.")

    _switch(s.row("Read around your cursor",
                  "Lets Svara continue a sentence without capitalising it. "
                  "Reads up to 200 characters you typed, and stores none."),
            "Read text near my cursor",
            lambda: bool(app.cfg["context"].get("read_caret_text")),
            lambda v: _set_caret(app, v))

    _switch(s.row("Learn my corrections",
                  "Notices when you fix the same word repeatedly and offers to "
                  "add it. Only ever suggests, never edits by itself."),
            "Suggest words from my edits",
            lambda: bool(app.auto_learner.enabled),
            lambda v: _set_learn(app, v),
            warn="Needs reading around your cursor too.")

    _switch(s.row("Write transcripts to the log",
                  "For reporting a bug. Everything you dictate is written to "
                  "the log in plain text until you turn this off."),
            "Log what I dictate",
            _transcripts_on,
            lambda v: _set_transcripts(app, v),
            warn="Turn this off when you are done.")

    s.rule()
    _switch(s.row("Start with Windows",
                  "Svara is ready the moment you log in, without launching it."),
            "Start when Windows starts",
            lambda: app.autostart_enabled,
            lambda _v: app.toggle_autostart())
    return s.frame


def _transcripts_on() -> bool:
    from . import redact
    return redact.transcripts_enabled()


def _set_transcripts(app, on: bool):
    from . import redact
    app.cfg.setdefault("logging", {})["debug_transcripts"] = bool(on)
    redact.install(app.cfg["logging"])


def _set_caret(app, on: bool):
    # ContextProvider re-reads cfg on every capture, so this lands on the next
    # dictation with no restart.
    app.cfg["context"]["read_caret_text"] = bool(on)
    if not on and app.auto_learner.enabled:
        app.auto_learner.enabled = False
        app.cfg["dictionary"]["auto_learn"] = False


def _set_learn(app, on: bool):
    # Gated on the caret permission: this is built on reading text Svara did
    # not produce, so it cannot be switched on by itself.
    if on and not app.cfg["context"].get("read_caret_text"):
        app._notify("Turn on reading around your cursor first. Learning your "
                    "corrections is built on it.")
        return
    app.cfg["dictionary"]["auto_learn"] = bool(on)
    app.auto_learner.enabled = bool(on)


def _about(parent, app):
    import tkinter as tk

    from . import __version__

    s = Section(parent, "About",
                "Svara is free and open source, and runs entirely on this "
                "machine.")

    for label, value in (("Version", f"v{__version__}"),
                         ("Model", app.model_label),
                         ("Settings file", "config.yaml, next to the app")):
        tk.Label(s.row(label), text=value, bg=BG, fg=SUB, font=(MONO, 9),
                 anchor="e").pack(anchor="e")

    if getattr(sys, "frozen", False):
        _button(s.row("Updates", "Svara checks quietly and installs only when "
                                 "you say so."),
                "Check now", app.check_updates_now).pack(anchor="e")

    s.rule()
    _button(s.row("How to use it", "The walkthrough, and a box to try "
                                   "dictation in."),
            "Open the guide", app.show_howto, primary=True).pack(anchor="e")
    return s.frame


SECTIONS = [
    ("Speech", _speech),
    ("Writing", _writing),
    ("Your words", _words),
    ("Shortcuts", _shortcuts),
    ("Privacy", _privacy),
    ("About", _about),
]


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

def build(root, app):
    """Build (or re-show) the settings window."""
    import tkinter as tk
    from tkinter import ttk

    win = getattr(root, "_svara_settings", None)
    if win is not None and win.winfo_exists():
        win.deiconify()
        win.lift()
        win.focus_force()
        return win

    win = tk.Toplevel(root)
    root._svara_settings = win
    win.title("Svara — Settings")
    win.configure(bg=BG)
    # Wide enough that a description and its control never collide. The old
    # window was 560 and clipped text off both edges.
    W, H = 880, 620
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{W}x{H}+{(sw - W) // 2}+{max(0, (sh - H) // 2 - 20)}")
    win.minsize(760, 520)
    try:
        from .setup_ui import _asset
        ic = _asset("icon.ico")
        if ic:
            win.iconbitmap(ic)
    except Exception:  # noqa: BLE001
        pass
    _style(win)

    # -- nav rail ---------------------------------------------------------
    nav = tk.Frame(win, bg=CARD, width=196)
    nav.pack(side="left", fill="y")
    nav.pack_propagate(False)

    tk.Label(nav, text="Svara", bg=CARD, fg=FG, font=(DISPLAY, 17),
             anchor="w").pack(anchor="w", padx=20, pady=(20, 2))
    tk.Label(nav, text="Settings", bg=CARD, fg=SUB, font=(UI, 9),
             anchor="w").pack(anchor="w", padx=20, pady=(0, 16))

    # -- content ----------------------------------------------------------
    body = tk.Frame(win, bg=BG)
    body.pack(side="left", fill="both", expand=True)

    canvas = tk.Canvas(body, bg=BG, highlightthickness=0, bd=0)
    bar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview,
                        style="S.Vertical.TScrollbar")
    inner = tk.Frame(canvas, bg=BG)
    window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=bar.set)
    canvas.pack(side="left", fill="both", expand=True, padx=(32, 0), pady=26)
    bar.pack(side="right", fill="y", pady=26, padx=(0, 6))

    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(window_id, width=e.width - 26))

    def on_wheel(event):
        canvas.yview_scroll(int(-event.delta / 120), "units")

    # bind_all so the wheel works wherever the pointer is inside the window,
    # and is unbound on close so it cannot hijack the other Svara windows.
    win.bind_all("<MouseWheel>", on_wheel)

    state = {"current": None, "frame": None}
    buttons: dict[str, tuple] = {}

    def select(name: str):
        if state["current"] == name:
            return
        if state["frame"] is not None:
            state["frame"].destroy()
        for other, (rule, label) in buttons.items():
            active = other == name
            # The signature: the active section carries a sienna rule and is
            # set in the display serif. Everything else stays quiet.
            rule.configure(bg=ACCENT if active else CARD)
            label.configure(fg=FG if active else SUB,
                            font=(DISPLAY, 11, "italic") if active
                            else (UI, 10))
        builder = dict(SECTIONS)[name]
        try:
            frame = builder(inner, app)
        except Exception:  # noqa: BLE001 — one broken section must not take
            # the whole window down; the rest stays usable.
            log.exception("settings section %r failed to build", name)
            frame = tk.Frame(inner, bg=BG)
            tk.Label(frame, text=f"“{name}” could not be shown.\n"
                                 "See logs\\mywhisper.log.",
                     bg=BG, fg=ERROR, font=(UI, 10), justify="left").pack(
                anchor="w")
        frame.pack(fill="both", expand=True, anchor="nw")
        state["current"], state["frame"] = name, frame
        canvas.yview_moveto(0)

    for name, _builder in SECTIONS:
        row = tk.Frame(nav, bg=CARD, cursor="hand2")
        row.pack(fill="x")
        rule = tk.Frame(row, bg=CARD, width=3)
        rule.pack(side="left", fill="y")
        label = tk.Label(row, text=name, bg=CARD, fg=SUB, font=(UI, 10),
                         anchor="w", padx=14, pady=8)
        label.pack(side="left", fill="x", expand=True)
        buttons[name] = (rule, label)
        for widget in (row, label):
            widget.bind("<Button-1>", lambda _e, n=name: select(n))

    foot = tk.Frame(nav, bg=CARD)
    foot.pack(side="bottom", fill="x", pady=14)
    tk.Label(foot, text="Everything stays on this machine.", bg=CARD, fg=SUB,
             font=(UI, 8), wraplength=160, justify="left").pack(anchor="w",
                                                               padx=20)

    def close():
        try:
            win.unbind_all("<MouseWheel>")
        except Exception:  # noqa: BLE001
            pass
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", lambda _e: close())

    select(SECTIONS[0][0])
    try:
        win.attributes("-topmost", True)
        win.lift()
        win.after(700, lambda: win.attributes("-topmost", False))
    except Exception:  # noqa: BLE001
        pass
    return win
